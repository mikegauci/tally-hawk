"""Integrity checks on the committed eval set: labels are valid, match their PDFs, and
trigger exactly the validation issues they claim to."""

from pathlib import Path

from pypdf import PdfReader

from evals.generate import N_INVOICES, build_cases, label_for
from evals.run_eval import SCORED_ISSUES
from tallyhawk.schema import InvoiceData
from tallyhawk.validation import validate_invoice

INVOICES_DIR = Path(__file__).parent.parent / "evals" / "data" / "invoices"


def test_dataset_size(gold_labels):
    assert len(gold_labels) == N_INVOICES
    assert len(list(INVOICES_DIR.glob("*.pdf"))) == N_INVOICES


def test_committed_labels_match_generator(gold_labels):
    assert [label_for(c) for c in build_cases()] == gold_labels


def test_labels_trigger_exactly_their_expected_issues(gold_labels):
    for label in gold_labels:
        inv = InvoiceData.model_validate(label["invoice"])
        found = sorted(i.code for i in validate_invoice(inv) if i.code in SCORED_ISSUES)
        assert found == label["expected_issues"], label["case_id"]


def test_key_values_are_printed_in_pdf(gold_labels):
    for label in gold_labels:
        text = "".join(page.extract_text() for page in PdfReader(INVOICES_DIR / f"{label['case_id']}.pdf").pages)
        inv = label["invoice"]
        assert inv["invoice_number"] in text, label["case_id"]
        if inv["po_number"]:
            assert inv["po_number"] in text, label["case_id"]
        if inv["vendor_tax_id"]:
            assert inv["vendor_tax_id"] in text, label["case_id"]


def test_dataset_covers_hard_cases(gold_labels):
    tags = {t for label in gold_labels for t in label["tags"]}
    assert {"supplier_error", "no_po", "many_line_items", "zero_tax", "tax_rate_not_printed", "european"} <= tags
