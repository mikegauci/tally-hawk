"""The PO-finding agent: an OpenAI model with tools over the procurement store.

It only runs when the deterministic lookup fails, which is when the invoice quotes no PO
or quotes one that isn't on file (a typo, an old number). The model searches vendors and
their open POs, compares the lines, and submits either a PO or "none found". Its answer is
checked against the store before it's used, and an agent-found PO always goes to a person
to confirm.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

import openai
from pydantic import BaseModel

from tallyhawk.extract import DEFAULT_MODEL, Usage, estimate_cost
from tallyhawk.procurement import ProcurementStore, PurchaseOrder
from tallyhawk.schema import InvoiceData

DEFAULT_AGENT_EFFORT = os.environ.get("TALLYHAWK_AGENT_EFFORT", "low")
MAX_TURNS = 8

AGENT_PROMPT = """\
You help an accounts payable team find the purchase order (PO) a supplier invoice belongs \
to. The invoice either quotes no PO number or quotes one that isn't on file.

Use the tools to identify the supplier, list its POs and compare them with the invoice. A \
PO matches when it is for the same supplier and its lines are the same goods or services \
(descriptions, quantities and prices broadly agree; small price differences are allowed \
and are checked later). A quoted PO number that differs from a PO on file by a typo is a \
strong hint, but the lines must still agree.

Never guess. If no PO clearly matches, submit po_number null; the invoice then goes back \
to the supplier asking for a valid PO, which is much cheaper than paying against the wrong \
one. Finish by calling submit_resolution exactly once."""


def _fn(name: str, description: str, properties: dict) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


TOOLS = [
    _fn(
        "search_vendors",
        "Find suppliers by name (fuzzy) and tax ID (exact). Returns the best candidates with a score from 0 to 1.",
        {"name": {"type": "string"}, "tax_id": {"type": ["string", "null"]}},
    ),
    _fn(
        "list_purchase_orders",
        "List a supplier's POs with their lines and totals.",
        {"vendor_id": {"type": "string"}, "include_closed": {"type": "boolean"}},
    ),
    _fn(
        "get_purchase_order",
        "Look up one PO by number. If it doesn't exist, returns similar PO numbers on file.",
        {"po_number": {"type": "string"}},
    ),
    _fn(
        "submit_resolution",
        "Submit the supplier and PO this invoice belongs to. Use null when not found.",
        {
            "vendor_id": {"type": ["string", "null"]},
            "po_number": {"type": ["string", "null"]},
            "confidence": {"type": "number", "description": "0 to 1"},
            "reasoning": {"type": "string", "description": "One or two sentences a reviewer can check."},
        },
    ),
]


class ToolCall(BaseModel):
    name: str
    arguments: dict


class Resolution(BaseModel):
    vendor_id: str | None
    po_number: str | None
    confidence: float
    reasoning: str
    tool_calls: list[ToolCall] = []
    usage: list[Usage] = []


Resolver = Callable[[InvoiceData], Resolution]


def _po_summary(po: PurchaseOrder) -> dict:
    return {
        "po_number": po.po_number,
        "vendor_id": po.vendor_id,
        "order_date": po.order_date.isoformat(),
        "currency": po.currency,
        "status": po.status,
        "total": po.total,
        "lines": [
            {"description": line.description, "quantity": line.quantity, "unit_price": line.unit_price}
            for line in po.lines
        ],
    }


def invoice_brief(invoice: InvoiceData) -> str:
    lines = "\n".join(
        f"- {item.description}: {item.quantity:g} x {item.unit_price} = {item.amount}" for item in invoice.line_items
    )
    return (
        f"Supplier: {invoice.vendor_name} (tax ID: {invoice.vendor_tax_id or 'not printed'})\n"
        f"Invoice {invoice.invoice_number} dated {invoice.invoice_date}, currency {invoice.currency}\n"
        f"PO quoted: {invoice.po_number or 'none'}\n"
        f"Subtotal {invoice.subtotal}, total {invoice.total}\n"
        f"Lines ({len(invoice.line_items)}):\n{lines}"
    )


def run_tool(store: ProcurementStore, name: str, args: dict) -> object:
    if name == "search_vendors":
        return [
            {"vendor_id": c.vendor.vendor_id, "name": c.vendor.name, "tax_id": c.vendor.tax_id, "score": c.score}
            for c in store.search_vendors(args["name"], args.get("tax_id"))
        ]
    if name == "list_purchase_orders":
        return [_po_summary(po) for po in store.purchase_orders_for_vendor(args["vendor_id"], args["include_closed"])]
    if name == "get_purchase_order":
        po = store.get_purchase_order(args["po_number"])
        if po is None:
            return {"found": False, "similar_po_numbers": store.similar_po_numbers(args["po_number"])}
        return {"found": True, **_po_summary(po)}
    return {"error": f"Unknown tool {name!r}"}


class AgentResolver:
    """Callable resolver backed by an OpenAI tool-calling loop (Responses API)."""

    def __init__(
        self,
        store: ProcurementStore,
        *,
        client: openai.OpenAI | None = None,
        model: str = DEFAULT_MODEL,
        effort: str = DEFAULT_AGENT_EFFORT,
        max_turns: int = MAX_TURNS,
    ):
        self.store = store
        self.client = client or openai.OpenAI()
        self.model = model
        self.effort = effort
        self.max_turns = max_turns

    def __call__(self, invoice: InvoiceData) -> Resolution:
        from tallyhawk.tracing import span

        with span("po_investigation_agent", metadata={"model": self.model}):
            return self._run(invoice)

    def _run(self, invoice: InvoiceData) -> Resolution:
        items: list = [{"role": "user", "content": f"Find the PO for this invoice.\n\n{invoice_brief(invoice)}"}]
        calls: list[ToolCall] = []
        usage: list[Usage] = []
        for _ in range(self.max_turns):
            response = self.client.responses.create(
                model=self.model,
                instructions=AGENT_PROMPT,
                input=items,
                tools=TOOLS,
                tool_choice="required",
                reasoning={"effort": self.effort},
                include=["reasoning.encrypted_content"],
                max_output_tokens=8000,
                store=False,
            )
            usage.append(
                Usage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cost_usd=estimate_cost(response.usage.input_tokens, response.usage.output_tokens),
                )
            )
            # Stateless (store=False): send the model's own output back with each tool result.
            items += [item.to_dict() for item in response.output]
            function_calls = [item for item in response.output if item.type == "function_call"]
            if not function_calls:
                break
            for fc in function_calls:
                try:
                    args = json.loads(fc.arguments)
                except json.JSONDecodeError:
                    args = {}
                calls.append(ToolCall(name=fc.name, arguments=args))
                if fc.name == "submit_resolution":
                    return Resolution(
                        vendor_id=args.get("vendor_id"),
                        po_number=args.get("po_number"),
                        confidence=float(args.get("confidence", 0.0)),
                        reasoning=str(args.get("reasoning", "")),
                        tool_calls=calls,
                        usage=usage,
                    )
                try:
                    output = run_tool(self.store, fc.name, args)
                except (KeyError, TypeError) as exc:
                    output = {"error": f"Bad arguments: {exc}"}
                items.append({"type": "function_call_output", "call_id": fc.call_id, "output": json.dumps(output)})
        return Resolution(
            vendor_id=None,
            po_number=None,
            confidence=0.0,
            reasoning=f"Agent stopped after {len(usage)} turns without submitting a resolution.",
            tool_calls=calls,
            usage=usage,
        )
