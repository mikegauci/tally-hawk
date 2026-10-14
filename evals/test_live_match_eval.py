"""The real matching eval: the agent and drafter call the OpenAI API. Only runs with `-m live`.

OPENAI_API_KEY=... uv run pytest -m live -s evals/test_live_match_eval.py
"""

import os

import pytest

from evals.run_match_eval import main

pytestmark = pytest.mark.live

MIN_DECISION_ACCURACY = 0.95
MIN_PO_ACCURACY = 0.95


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
def test_matching_accuracy():
    summary = main([])
    assert not summary["failures"], summary["failures"]
    assert summary["false_approvals"] == [], "Approved invoices that should have been stopped"
    assert summary["decision_accuracy"] >= MIN_DECISION_ACCURACY
    assert summary["po_accuracy"] >= MIN_PO_ACCURACY
