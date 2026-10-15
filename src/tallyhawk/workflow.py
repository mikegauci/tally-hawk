"""The matching workflow as a LangGraph state graph.

    check ─► lookup ─┬─────────────────► match ─► decide ─┬─► END (approve)
                     └─► investigate ──►                  ├─► draft_query ─► handoff
                       (agent, only when                  └─► handoff (review)
                        no PO was found)

- **check**: step 1's validation results and low-confidence fields become issues.
- **lookup**: deterministic. Find the supplier by tax ID or name, and the PO by the number
  printed on the invoice.
- **investigate**: the OpenAI tool-calling agent, only when the PO is missing or unknown.
- **match**: deterministic three-way match against the PO and goods receipts.
- **decide**: approve, review, or vendor_query.
- **draft_query**: draft an email to the supplier for anything they need to fix.
- **handoff**: package the case for a person. With a checkpointer and `await_human=True`
  the graph pauses here (LangGraph `interrupt`) until a reviewer resumes it.
"""

from __future__ import annotations

import operator
import time
import uuid
from collections.abc import Callable, Iterable
from typing import Annotated, Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel

from tallyhawk.agent import Resolution, Resolver, ToolCall
from tallyhawk.drafting import Drafter, VendorQuery, template_drafter
from tallyhawk.extract import Usage
from tallyhawk.matching import (
    Decision,
    LineMatch,
    MatchIssue,
    Route,
    Tolerances,
    decide,
    extraction_issues,
    three_way_match,
    vendor_matches,
)
from tallyhawk.procurement import POLine, ProcurementStore, PurchaseOrder, Vendor
from tallyhawk.schema import InvoiceData, LineItem
from tallyhawk.validation import validate_invoice


class Step(BaseModel):
    """One node of the graph as it ran: what it did, how long it took, and any model calls."""

    name: str
    summary: list[str]
    duration_ms: float
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None


# Types the graph state holds, allowed when a checkpointer reads a paused case back.
CHECKPOINT_TYPES = [
    (cls.__module__, cls.__name__)
    for cls in (
        InvoiceData,
        LineItem,
        Vendor,
        POLine,
        PurchaseOrder,
        MatchIssue,
        Route,
        Decision,
        LineMatch,
        VendorQuery,
        Usage,
        Resolution,
        ToolCall,
        Step,
    )
]


def checkpoint_serializer() -> JsonPlusSerializer:
    """Pass to a checkpointer, e.g. `InMemorySaver(serde=checkpoint_serializer())`."""
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)


class State(TypedDict, total=False):
    invoice: InvoiceData
    low_confidence: list[str]
    await_human: bool
    extraction_issues: list[MatchIssue]
    vendor: Vendor | None
    vendor_source: Literal["lookup", "po", "agent"] | None
    po: PurchaseOrder | None
    po_source: Literal["printed", "agent"] | None
    resolution: Resolution | None
    issues: list[MatchIssue]
    lines: list[LineMatch]
    decision: Decision
    draft: VendorQuery | None
    review: dict | None
    usage: Annotated[list[Usage], operator.add]
    trace: Annotated[list[str], operator.add]
    steps: Annotated[list[Step], operator.add]


class MatchOutcome(BaseModel):
    status: Literal["done", "awaiting_review"]
    thread_id: str | None
    invoice_number: str
    decision: Decision
    issues: list[MatchIssue]
    vendor_id: str | None
    vendor_source: str | None
    po_number: str | None
    po_source: str | None
    lines: list[LineMatch]
    resolution: Resolution | None
    draft: VendorQuery | None
    review: dict | None
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    trace: list[str]
    steps: list[Step] = []  # absent on outcomes stored before per-step timing


class MatchingWorkflow:
    def __init__(
        self,
        store: ProcurementStore,
        *,
        resolver: Resolver | None = None,
        drafter: Drafter | None = template_drafter,
        tolerances: Tolerances | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ):
        """`resolver=None` runs rules only: without the agent, an invoice whose PO can't be
        looked up directly is sent back to the supplier. `drafter=None` skips email drafts."""
        self.store = store
        self.resolver = resolver
        self.drafter = drafter
        self.tolerances = tolerances or Tolerances()
        self.checkpointer = checkpointer
        self.graph = self._build().compile(checkpointer=checkpointer)

    # --- nodes -------------------------------------------------------------------------

    def _check(self, state: State) -> dict:
        issues = extraction_issues(validate_invoice(state["invoice"]), state.get("low_confidence", []))
        return {"extraction_issues": issues, "trace": [f"check: {len(issues)} extraction issue(s)"]}

    def _lookup(self, state: State) -> dict:
        invoice = state["invoice"]
        vendor = next(
            (
                c.vendor
                for c in self.store.search_vendors(invoice.vendor_name, invoice.vendor_tax_id)
                if vendor_matches(invoice, c.vendor)
            ),
            None,
        )
        vendor_source = "lookup" if vendor else None
        po = self.store.get_purchase_order(invoice.po_number) if invoice.po_number else None
        if po is not None and vendor is None:
            po_vendor = self.store.get_vendor(po.vendor_id)
            if po_vendor is not None and vendor_matches(invoice, po_vendor):
                vendor, vendor_source = po_vendor, "po"
        trace = (
            f"lookup: supplier {vendor.vendor_id if vendor else 'not found'}; "
            f"PO {po.po_number + ' on file' if po else (invoice.po_number or 'none') + ' not found'}"
        )
        return {
            "vendor": vendor,
            "vendor_source": vendor_source,
            "po": po,
            "po_source": "printed" if po else None,
            "trace": [trace],
        }

    def _investigate(self, state: State) -> dict:
        resolution = self.resolver(state["invoice"])
        update: dict = {"resolution": resolution, "usage": resolution.usage}
        notes = [f"investigate: agent made {len(resolution.tool_calls)} tool call(s)"]
        if state.get("vendor") is None and resolution.vendor_id:
            vendor = self.store.get_vendor(resolution.vendor_id)
            if vendor is not None:
                update |= {"vendor": vendor, "vendor_source": "agent"}
            else:
                notes.append(f"investigate: agent named unknown supplier {resolution.vendor_id}; ignored")
        if resolution.po_number:
            po = self.store.get_purchase_order(resolution.po_number)
            if po is not None:
                update |= {"po": po, "po_source": "agent"}
            else:
                notes.append(f"investigate: agent named PO {resolution.po_number}, which isn't on file; ignored")
        notes.append(f"investigate: PO {update['po'].po_number if 'po' in update else 'not found'}")
        return update | {"trace": notes}

    def _match(self, state: State) -> dict:
        invoice, vendor, po = state["invoice"], state.get("vendor"), state.get("po")
        result = three_way_match(
            invoice,
            vendor=vendor,
            po=po,
            po_vendor=self.store.get_vendor(po.vendor_id) if po else None,
            receipts=self.store.goods_receipts(po.po_number) if po else [],
            posted=self.store.posted_invoices(vendor.vendor_id, invoice.invoice_number) if vendor else [],
            po_inferred=state.get("po_source") == "agent",
            vendor_inferred=state.get("vendor_source") == "agent",
            tolerances=self.tolerances,
        )
        issues = state["extraction_issues"] + result.issues
        return {"issues": issues, "lines": result.lines, "trace": [f"match: {len(result.issues)} match issue(s)"]}

    def _decide(self, state: State) -> dict:
        decision = decide(state["issues"])
        return {"decision": decision, "trace": [f"decide: {decision}"]}

    def _draft_query(self, state: State) -> dict:
        po = state.get("po")
        vendor = state.get("vendor") or (self.store.get_vendor(po.vendor_id) if po else None)
        draft = self.drafter(state["invoice"], vendor, po.po_number if po else None, state["issues"])
        return {
            "draft": draft,
            "usage": [draft.usage] if draft.usage else [],
            "trace": [f"draft_query: email to {draft.to or 'unknown address'}"],
        }

    def _handoff(self, state: State) -> dict:
        if not state.get("await_human"):
            return {"trace": ["handoff: queued for a person"]}
        review = interrupt(
            {
                "invoice_number": state["invoice"].invoice_number,
                "decision": state["decision"].value,
                "issues": [i.model_dump(mode="json") for i in state["issues"]],
                "draft": state["draft"].model_dump(mode="json") if state.get("draft") else None,
            }
        )
        return {"review": review, "trace": [f"handoff: reviewer chose {review.get('action', '?')}"]}

    # --- graph -------------------------------------------------------------------------

    @staticmethod
    def _timed(name: str, node: Callable[[State], dict]) -> Callable[[State], dict]:
        """Wrap a node so it also records a `Step` with its duration and model usage."""

        def run(state: State) -> dict:
            started = time.perf_counter()
            update = node(state)
            usage: list[Usage] = update.get("usage", [])
            costs = [u.cost_usd for u in usage]
            step = Step(
                name=name,
                summary=[line.split(": ", 1)[-1] for line in update.get("trace", [])],
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                llm_calls=len(usage),
                input_tokens=sum(u.input_tokens for u in usage),
                output_tokens=sum(u.output_tokens for u in usage),
                cost_usd=round(sum(costs), 6) if usage and None not in costs else None,
            )
            return update | {"steps": [step]}

        return run

    def _after_lookup(self, state: State) -> str:
        return "match" if state.get("po") is not None or self.resolver is None else "investigate"

    def _after_decide(self, state: State) -> str:
        if self.drafter is not None and any(i.route is Route.VENDOR for i in state["issues"]):
            return "draft_query"
        return END if state["decision"] is Decision.APPROVE else "handoff"

    def _build(self) -> StateGraph:
        g = StateGraph(State)
        g.add_node("check", self._timed("check", self._check))
        g.add_node("lookup", self._timed("lookup", self._lookup))
        g.add_node("investigate", self._timed("investigate", self._investigate))
        g.add_node("match", self._timed("match", self._match))
        g.add_node("decide", self._timed("decide", self._decide))
        g.add_node("draft_query", self._timed("draft_query", self._draft_query))
        g.add_node("handoff", self._timed("handoff", self._handoff))
        g.add_edge(START, "check")
        g.add_edge("check", "lookup")
        g.add_conditional_edges("lookup", self._after_lookup, ["match", "investigate"])
        g.add_edge("investigate", "match")
        g.add_edge("match", "decide")
        g.add_conditional_edges("decide", self._after_decide, ["draft_query", "handoff", END])
        g.add_edge("draft_query", "handoff")
        g.add_edge("handoff", END)
        return g

    # --- entry points ------------------------------------------------------------------

    def run(
        self,
        invoice: InvoiceData,
        *,
        low_confidence: Iterable[str] = (),
        await_human: bool = False,
        thread_id: str | None = None,
    ) -> MatchOutcome:
        """Match one invoice. With `await_human=True` (needs a checkpointer) a case that needs a
        person stops at the handoff with status `awaiting_review`; call `resume` to finish it."""
        if await_human and self.checkpointer is None:
            raise ValueError("await_human needs a checkpointer to pause and resume the graph.")
        thread_id = thread_id or (str(uuid.uuid4()) if self.checkpointer else None)
        config = {"configurable": {"thread_id": thread_id}} if thread_id else None
        state = self.graph.invoke(
            {"invoice": invoice, "low_confidence": sorted(low_confidence), "await_human": await_human},
            config,
        )
        return self._outcome(state, thread_id)

    def resume(self, thread_id: str, review: dict) -> MatchOutcome:
        """Finish a paused case with the reviewer's answer, e.g. {"action": "send_query", "note": "..."}."""
        state = self.graph.invoke(Command(resume=review), {"configurable": {"thread_id": thread_id}})
        return self._outcome(state, thread_id)

    @staticmethod
    def _outcome(state: dict, thread_id: str | None) -> MatchOutcome:
        usage: list[Usage] = state.get("usage", [])
        costs = [u.cost_usd for u in usage]
        po, vendor = state.get("po"), state.get("vendor")
        return MatchOutcome(
            status="awaiting_review" if state.get("__interrupt__") else "done",
            thread_id=thread_id,
            invoice_number=state["invoice"].invoice_number,
            decision=state["decision"],
            issues=state["issues"],
            vendor_id=vendor.vendor_id if vendor else None,
            vendor_source=state.get("vendor_source"),
            po_number=po.po_number if po else None,
            po_source=state.get("po_source"),
            lines=state["lines"],
            resolution=state.get("resolution"),
            draft=state.get("draft"),
            review=state.get("review"),
            llm_calls=len(usage),
            input_tokens=sum(u.input_tokens for u in usage),
            output_tokens=sum(u.output_tokens for u in usage),
            cost_usd=round(sum(costs), 6) if usage and None not in costs else None,
            trace=state.get("trace", []),
            steps=state.get("steps", []),
        )
