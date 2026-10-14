"""The real eval: calls the OpenAI API on every invoice. Costs money, so it only runs with `-m live`.

OPENAI_API_KEY=... uv run pytest -m live -s
"""

import os

import pytest

from evals.run_eval import main

pytestmark = pytest.mark.live

# Bars a change must clear, on the 50 standard invoices. The hard set is reported, not gated:
# it exists to show where extraction breaks and whether low confidence catches it.
# Raise these as the extractor improves.
MIN_HEADER_FIELD_ACCURACY = 0.95
MIN_LINE_ITEM_FIELD_ACCURACY = 0.95
MAX_SILENT_ERROR_RATE = 0.05


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
def test_extraction_accuracy():
    summary = main([])
    assert not summary["failures"], summary["failures"]
    standard = summary["sets"]["standard"]
    low = {k: v for k, v in standard["field_accuracy"].items() if v < MIN_HEADER_FIELD_ACCURACY}
    assert not low, f"Fields below {MIN_HEADER_FIELD_ACCURACY:.0%}: {low}"
    assert standard["line_item_field_accuracy"] >= MIN_LINE_ITEM_FIELD_ACCURACY
    assert standard["silent_error_rate"] <= MAX_SILENT_ERROR_RATE
