from datetime import date

from evals.scoring import score_invoice, values_match


def test_identical_invoices_score_perfectly(invoice):
    score = score_invoice(invoice, invoice)
    assert score["all_correct"]
    assert score["line_fields_correct"] == score["line_fields_total"] == 8


def test_text_normalisation():
    assert values_match("vendor_name", "OLD MILL SUPPLIES INC.", "Old Mill Supplies Inc.")
    assert not values_match("vendor_name", "Old Mill Supply Inc.", "Old Mill Supplies Inc.")


def test_ids_ignore_case_and_spaces_only():
    assert values_match("vendor_tax_id", "gb123 4567 89", "GB12345678 9")
    assert not values_match("po_number", "PO-1234", "PO1234")


def test_amounts_match_to_the_cent():
    assert values_match("total", 100.004, 100.0)
    assert not values_match("total", 100.01, 100.0)


def test_nulls():
    assert values_match("po_number", None, None)
    assert not values_match("po_number", "PO-1", None)
    assert not values_match("due_date", None, date(2026, 1, 1))


def test_missing_line_item_counts_against_score(invoice):
    pred = invoice.model_copy(update={"line_items": invoice.line_items[:1]})
    score = score_invoice(pred, invoice)
    assert not score["fields"]["line_item_count"]
    assert not score["fields"]["line_items"]
    assert score["line_fields_correct"] == 4 and score["line_fields_total"] == 8
    assert score["fields"]["total"]
