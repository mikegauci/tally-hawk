"""The PO-finding agent and the workflow around it, against a scripted OpenAI API."""

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from openai_mock import function_call, message, scripted_client

from tallyhawk.agent import AgentResolver, Resolution, run_tool
from tallyhawk.drafting import LLMDrafter
from tallyhawk.extract import Usage
from tallyhawk.procurement import InMemoryStore
from tallyhawk.schema import InvoiceData
from tallyhawk.workflow import MatchingWorkflow, MatchOutcome, checkpoint_serializer

DATA = Path(__file__).parent.parent / "evals" / "data"


@pytest.fixture(scope="module")
def store():
    return InMemoryStore.from_dir(DATA / "procurement")


@pytest.fixture(scope="module")
def labels():
    return {label["case_id"]: label for label in json.loads((DATA / "match_labels.json").read_text())}


def gold(case_id: str) -> InvoiceData:
    return InvoiceData.model_validate(json.loads((DATA / "labels" / f"{case_id}.json").read_text())["invoice"])


def test_tools_read_the_store(store, labels):
    label = labels["inv_002"]
    found = run_tool(store, "get_purchase_order", {"po_number": label["expected_po_number"]})
    assert found["found"] and found["vendor_id"] == label["expected_vendor_id"]
    pos = run_tool(store, "list_purchase_orders", {"vendor_id": label["expected_vendor_id"], "include_closed": False})
    assert label["expected_po_number"] in [po["po_number"] for po in pos] and len(pos) >= 2  # distractors too
    assert run_tool(store, "nope", {}) == {"error": "Unknown tool 'nope'"}


def test_agent_loop_runs_tools_and_returns_submission(store, labels):
    label = labels["inv_002"]
    invoice = gold("inv_002")
    requests: list[dict] = []
    client = scripted_client(
        [
            [function_call("search_vendors", {"name": invoice.vendor_name, "tax_id": invoice.vendor_tax_id})],
            [
                function_call(
                    "list_purchase_orders", {"vendor_id": label["expected_vendor_id"], "include_closed": False}
                )
            ],
            [
                function_call(
                    "submit_resolution",
                    {
                        "vendor_id": label["expected_vendor_id"],
                        "po_number": label["expected_po_number"],
                        "confidence": 0.9,
                        "reasoning": "Lines and quantities match.",
                    },
                )
            ],
        ],
        requests,
    )
    resolution = AgentResolver(store, client=client)(invoice)

    assert resolution.po_number == label["expected_po_number"]
    assert [c.name for c in resolution.tool_calls] == ["search_vendors", "list_purchase_orders", "submit_resolution"]
    assert len(resolution.usage) == 3
    assert requests[0]["tool_choice"] == "required" and requests[0]["store"] is False
    assert all(tool["strict"] for tool in requests[0]["tools"])
    # The second request carries the first call and its result back to the model.
    outputs = [item for item in requests[1]["input"] if item.get("type") == "function_call_output"]
    assert outputs[0]["call_id"] == "call_search_vendors_1"
    assert json.loads(outputs[0]["output"])[0]["vendor_id"] == label["expected_vendor_id"]


def test_agent_gives_up_after_max_turns(store):
    client = scripted_client([[function_call("search_vendors", {"name": "x", "tax_id": None})]] * 2)
    resolution = AgentResolver(store, client=client, max_turns=2)(gold("inv_002"))
    assert resolution.po_number is None and "2 turns" in resolution.reasoning


def fixed(vendor_id, po_number):
    return lambda invoice: Resolution(vendor_id=vendor_id, po_number=po_number, confidence=0.9, reasoning="test")


def test_agent_found_po_goes_to_review(store, labels):
    label = labels["inv_002"]
    workflow = MatchingWorkflow(store, resolver=fixed(label["expected_vendor_id"], label["expected_po_number"]))
    outcome = workflow.run(gold("inv_002"))
    assert outcome.decision == "review" and outcome.po_source == "agent"
    assert [i.code for i in outcome.issues] == ["po_inferred"]


def test_made_up_po_from_agent_is_ignored(store):
    workflow = MatchingWorkflow(store, resolver=fixed(None, "PO-00000"))
    outcome = workflow.run(gold("inv_002"))
    assert outcome.po_number is None and outcome.decision == "vendor_query"
    assert any("isn't on file" in step for step in outcome.trace)


def test_agent_only_runs_when_lookup_fails(store):
    def boom(invoice):
        raise AssertionError("agent should not run")

    outcome = MatchingWorkflow(store, resolver=boom).run(gold("inv_001"))
    assert outcome.decision == "approve" and outcome.resolution is None and outcome.llm_calls == 0


def test_llm_drafter(store):
    client = scripted_client([[message(json.dumps({"subject": "Query on INV", "body": "Hello"}))]])
    outcome = MatchingWorkflow(store, drafter=LLMDrafter(client=client)).run(gold("inv_003"))
    assert outcome.decision == "vendor_query"
    assert outcome.draft.subject == "Query on INV" and outcome.draft.to.endswith(".example")
    assert outcome.llm_calls == 1 and outcome.input_tokens == 1000


def test_pause_for_reviewer_and_resume(store):
    workflow = MatchingWorkflow(store, checkpointer=InMemorySaver(serde=checkpoint_serializer()))
    paused = workflow.run(gold("inv_003"), await_human=True)
    assert paused.status == "awaiting_review" and paused.decision == "vendor_query" and paused.review is None
    done = workflow.resume(paused.thread_id, {"action": "send_query"})
    assert done.status == "done" and done.review == {"action": "send_query"}
    # Approved invoices never wait for a person.
    assert workflow.run(gold("inv_001"), await_human=True).status == "done"


def test_await_human_needs_a_checkpointer(store):
    with pytest.raises(ValueError):
        MatchingWorkflow(store).run(gold("inv_001"), await_human=True)


def test_each_step_records_its_time_and_model_usage(store, labels):
    label = labels["inv_002"]
    spend = Usage(input_tokens=900, output_tokens=120, cost_usd=0.004)

    def resolver(invoice):
        return Resolution(
            vendor_id=label["expected_vendor_id"],
            po_number=label["expected_po_number"],
            confidence=0.9,
            reasoning="test",
            usage=[spend],
        )

    outcome = MatchingWorkflow(store, resolver=resolver).run(gold("inv_002"))
    steps = {step.name: step for step in outcome.steps}
    assert [s.name for s in outcome.steps] == ["check", "lookup", "investigate", "match", "decide", "handoff"]
    assert all(s.duration_ms >= 0 for s in outcome.steps)
    assert (steps["investigate"].llm_calls, steps["investigate"].input_tokens) == (1, 900)
    assert steps["investigate"].cost_usd == 0.004
    assert steps["match"].llm_calls == 0 and steps["match"].cost_usd is None  # rules, no model
    assert steps["decide"].summary == ["review"]


def test_outcomes_stored_before_step_timing_still_load(store):
    stored = MatchingWorkflow(store).run(gold("inv_001")).model_dump(mode="json")
    del stored["steps"]
    assert MatchOutcome.model_validate(stored).steps == []
