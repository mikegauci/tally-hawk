"""Integrity checks on the committed eval set: labels are valid, match their PDFs, and
trigger exactly the validation issues they claim to."""

from pathlib import Path

from pypdf import PdfReader

from evals.generate import HARD_KINDS, N_INVOICES, N_STANDARD, build_cases, label_for
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


def _pdf_text(case_id: str) -> str:
    return "".join(page.extract_text() for page in PdfReader(INVOICES_DIR / f"{case_id}.pdf").pages)


def _is_scanned(label: dict) -> bool:
    return bool(SCANNED_KINDS & set(label["tags"]))


SCANNED_KINDS = {
    "scanned_rotated",
    "scanned_skewed",
    "low_res",
    "handwritten_po",
    "handwritten_note",
    "paid_stamp",
}


def test_key_values_are_printed_in_pdf(gold_labels):
    for label in gold_labels:
        if _is_scanned(label):
            continue
        text = _pdf_text(label["case_id"])
        inv = label["invoice"]
        assert inv["invoice_number"] in text, label["case_id"]
        if inv["po_number"]:
            assert inv["po_number"] in text, label["case_id"]
        if inv["vendor_tax_id"]:
            assert inv["vendor_tax_id"] in text, label["case_id"]


def test_dataset_covers_hard_cases(gold_labels):
    tags = {t for label in gold_labels for t in label["tags"]}
    assert {"supplier_error", "no_po", "many_line_items", "zero_tax", "tax_rate_not_printed", "european"} <= tags


def test_scanned_invoices_have_no_text_layer(gold_labels):
    scanned = [label for label in gold_labels if _is_scanned(label)]
    assert len(scanned) == sum(kind in SCANNED_KINDS for kind, _ in HARD_KINDS)
    for label in scanned:
        assert _pdf_text(label["case_id"]).strip() == "", label["case_id"]


def test_hard_set(gold_labels):
    standard, hard = gold_labels[:N_STANDARD], gold_labels[N_STANDARD:]
    assert not any("hard" in label["tags"] for label in standard)
    assert [next(t for t in label["tags"] if t in dict(HARD_KINDS)) for label in hard] == [k for k, _ in HARD_KINDS]
    assert 15 <= len(hard) <= 20
    for label in hard:
        inv = label["invoice"]
        if "handwritten_po" in label["tags"]:
            # The PO is only handwritten; the label holds it, so no missing-PO issue is expected.
            assert inv["po_number"] and "missing_po" not in label["expected_issues"]
        if "mixed_tax_rates" in label["tags"]:
            assert inv["tax_rate"] is None and inv["tax_amount"] > 0
        if "deposit_paid" in label["tags"] or "dual_currency" in label["tags"]:
            # The label keeps the invoice's own total, not the balance or the converted amount.
            assert abs(inv["subtotal"] + inv["tax_amount"] - inv["total"]) < 0.01
