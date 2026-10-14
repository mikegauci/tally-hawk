from conftest import make_extracted

from tallyhawk.validation import low_confidence_fields, needs_review, validate_invoice


def codes(inv):
    return {i.code for i in validate_invoice(inv)}


def test_consistent_invoice_has_no_issues(invoice):
    assert codes(invoice) == set()


def test_total_mismatch(invoice):
    assert "total_mismatch" in codes(invoice.model_copy(update={"total": 128.0}))


def test_subtotal_mismatch(invoice):
    assert "subtotal_mismatch" in codes(
        invoice.model_copy(update={"subtotal": 90.0, "tax_amount": 16.2, "total": 106.2})
    )


def test_line_amount_mismatch(invoice):
    lines = [invoice.line_items[0].model_copy(update={"amount": 95.0}), invoice.line_items[1]]
    found = codes(invoice.model_copy(update={"line_items": lines}))
    assert {"line_amount_mismatch", "subtotal_mismatch"} <= found


def test_tax_rate_mismatch(invoice):
    assert "tax_mismatch" in codes(invoice.model_copy(update={"tax_rate": 20.0}))


def test_rounding_within_tolerance_is_fine(invoice):
    assert codes(invoice.model_copy(update={"total": 118.01})) == set()


def test_missing_po_is_a_warning_not_review(invoice):
    issues = validate_invoice(invoice.model_copy(update={"po_number": None}))
    assert [i.code for i in issues] == ["missing_po"]
    assert not needs_review(issues, [])


def test_low_confidence_routes_to_review(invoice):
    extracted = make_extracted(invoice)
    extracted.confidence.po_number = 0.6
    low = low_confidence_fields(extracted)
    assert low == ["po_number"]
    assert needs_review([], low)
