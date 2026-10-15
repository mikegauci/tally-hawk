"""The web app's "Try a sample invoice" files are copies of eval invoices; keep them honest.

Each sample must be byte-identical to its eval PDF, and the outcome its card promises must
be what the deterministic matcher decides from the ground truth (the agent sample, which
needs the LLM to find its PO, is covered by the agent matching eval instead).
"""

import json
from pathlib import Path

import pytest

from tallyhawk.drafting import template_drafter
from tallyhawk.procurement import InMemoryStore
from tallyhawk.schema import InvoiceData
from tallyhawk.workflow import MatchingWorkflow

ROOT = Path(__file__).parent.parent
DATA = ROOT / "evals" / "data"
SAMPLES = json.loads((ROOT / "web" / "src" / "lib" / "samples.json").read_text())


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s["file"])
def test_sample_is_an_unchanged_eval_invoice(sample):
    copy = ROOT / "web" / "public" / "samples" / sample["file"]
    assert copy.read_bytes() == (DATA / "invoices" / sample["file"]).read_bytes()


@pytest.mark.parametrize("sample", [s for s in SAMPLES if not s.get("agent")], ids=lambda s: s["file"])
def test_sample_outcome_matches_the_matcher(sample):
    label = json.loads((DATA / "labels" / sample["file"].replace(".pdf", ".json")).read_text())
    workflow = MatchingWorkflow(InMemoryStore.from_dir(DATA / "procurement"), resolver=None, drafter=template_drafter)
    outcome = workflow.run(InvoiceData.model_validate(label["invoice"]), low_confidence=[])
    assert outcome.decision == sample["decision"]


def test_agent_sample_matches_the_matching_labels():
    labels = {item["case_id"]: item for item in json.loads((DATA / "match_labels.json").read_text())}
    for sample in SAMPLES:
        case = sample["file"].removesuffix(".pdf")
        if case in labels:
            assert labels[case]["expected_decision"] == sample["decision"], case
