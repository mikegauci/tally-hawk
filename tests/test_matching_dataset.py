"""Integrity of the matching seed data and labels, and the free rules-only baseline."""

import json
from pathlib import Path

from evals.generate_matching import SCENARIOS, SEED_DIR, build
from evals.run_match_eval import load_inputs, load_match_labels, run_outcomes, summarize
from tallyhawk.agent import Resolution
from tallyhawk.procurement import InMemoryStore
from tallyhawk.workflow import MatchingWorkflow


def test_committed_seed_and_labels_match_generator():
    seed_data, labels = build()
    for name, rows in seed_data.items():
        assert json.loads((SEED_DIR / f"{name}.json").read_text()) == rows, name
    assert load_match_labels() == labels


def test_labels_cover_every_scenario_and_decision():
    labels = load_match_labels()
    assert len(labels) == 50
    assert {label["scenario"] for label in labels} == set(SCENARIOS)
    assert {label["expected_decision"] for label in labels} == {"approve", "review", "vendor_query"}


def _summary(tmp_path: Path, resolver) -> dict:
    labels = load_match_labels()
    store = InMemoryStore.from_dir(SEED_DIR)
    run_outcomes(labels, load_inputs(labels, None), MatchingWorkflow(store, resolver=resolver), tmp_path, workers=1)
    return summarize(labels, tmp_path / "outcomes")


def test_labels_are_reachable_with_the_right_resolution(tmp_path):
    """With an agent that always finds the labelled PO, every case matches its label exactly.
    This checks the seed data and the matcher agree; the live eval measures the real agent."""
    by_invoice_number = {
        json.loads((SEED_DIR.parent / "labels" / f"{lb['case_id']}.json").read_text())["invoice"]["invoice_number"]: lb
        for lb in load_match_labels()
    }

    def oracle(invoice):
        label = by_invoice_number[invoice.invoice_number]
        return Resolution(
            vendor_id=label["expected_vendor_id"],
            po_number=label["expected_po_number"],
            confidence=1.0,
            reasoning="oracle",
        )

    summary = _summary(tmp_path, oracle)
    assert summary["decision_accuracy"] == 1.0
    assert summary["issue_set_accuracy"] == 1.0
    assert summary["vendor_accuracy"] == 1.0 and summary["po_accuracy"] == 1.0


def test_rules_only_baseline(tmp_path):
    """Without the agent, only invoices whose PO can't be looked up directly are wrong, and
    they go back to the supplier rather than being approved."""
    summary = _summary(tmp_path, None)
    assert summary["false_approvals"] == []
    assert summary["decision_accuracy"] == 0.82
    wrong = {c["scenario"] for c in summary["cases"] if c["decision"] != c["expected"]}
    assert wrong == {"po_not_printed", "po_typo"}
