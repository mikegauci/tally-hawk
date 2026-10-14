"""Three-way match rules, extraction issues and the decision policy."""

from datetime import date

import pytest

from tallyhawk.matching import Decision, Tolerances, decide, extraction_issues, three_way_match
from tallyhawk.procurement import GoodsReceipt, POLine, PostedInvoice, PurchaseOrder, ReceiptLine, Vendor
from tallyhawk.schema import LineItem
from tallyhawk.validation import validate_invoice

VENDOR = Vendor(
    vendor_id="V1", name="Kestrel Building Materials Ltd", tax_id="MT12345678", email="a@k.example", address="x"
)
OTHER = Vendor(vendor_id="V2", name="Atlas Foods Ltd", tax_id="MT87654321", email="a@a.example", address="y")


def _po(invoice, **changes):
    lines = [
        POLine(line_no=n, description=i.description, quantity=i.quantity, unit_price=i.unit_price)
        for n, i in enumerate(invoice.line_items, start=1)
    ]
    fields = {
        "po_number": "PO-55120",
        "vendor_id": "V1",
        "order_date": date(2026, 2, 1),
        "currency": "EUR",
        "status": "open",
        "lines": lines,
    }
    return PurchaseOrder(**(fields | changes))


def _receipt(quantities):
    return GoodsReceipt(
        receipt_number="GRN-1",
        po_number="PO-55120",
        received_date=date(2026, 2, 20),
        lines=[ReceiptLine(po_line=no, quantity=q) for no, q in quantities.items()],
    )


def _match(invoice, po=None, receipts=None, vendor=VENDOR, po_vendor=VENDOR, posted=(), **kw):
    po = po or _po(invoice)
    receipts = [_receipt({1: 10, 2: 1})] if receipts is None else receipts
    return three_way_match(
        invoice, vendor=vendor, po=po, po_vendor=po_vendor, receipts=receipts, posted=list(posted), **kw
    )


def codes(result):
    return sorted(i.code for i in result.issues)


def test_clean_match_approves(invoice):
    result = _match(invoice)
    assert codes(result) == [] and decide(result.issues) is Decision.APPROVE
    assert [line.po_line for line in result.lines] == [1, 2]


def test_price_above_tolerance_goes_to_vendor(invoice):
    po = _po(invoice)
    po.lines[0].unit_price = 8.0  # invoice charges 8.5
    result = _match(invoice, po=po)
    assert codes(result) == ["price_variance"]
    assert decide(result.issues) is Decision.VENDOR_QUERY


def test_small_price_difference_and_cheaper_prices_pass(invoice):
    po = _po(invoice)
    po.lines[0].unit_price = 8.45  # 0.6% under the invoice price: within 1%
    po.lines[1].unit_price = 20.0  # invoice is cheaper than the PO: fine
    assert codes(_match(invoice, po=po)) == []
    assert codes(_match(invoice, po=po, tolerances=Tolerances(price_pct=0.1))) == ["price_variance"]


def test_short_delivery_and_split_receipts(invoice):
    assert codes(_match(invoice, receipts=[_receipt({1: 8, 2: 1})])) == ["qty_exceeds_received"]
    split = [_receipt({1: 6}), _receipt({1: 4, 2: 1})]
    assert codes(_match(invoice, receipts=split)) == []


def test_no_receipt_is_one_review_issue_not_one_per_line(invoice):
    result = _match(invoice, receipts=[])
    assert codes(result) == ["no_goods_receipt"] and decide(result.issues) is Decision.REVIEW


def test_line_not_on_po_and_over_ordered(invoice):
    po = _po(invoice)
    po.lines.pop()
    po.lines[0].quantity = 5
    assert codes(_match(invoice, po=po, receipts=[_receipt({1: 10})])) == ["line_not_on_po", "qty_exceeds_ordered"]


def test_repeated_items_pair_with_the_right_po_lines(invoice):
    # Two invoice lines with the same description at different prices; the PO lists them in
    # the other order, and one is overcharged. Only that one should be flagged.
    inv = invoice.model_copy(
        update={
            "line_items": [
                LineItem(description="Rebar 12mm", quantity=10, unit_price=9.0, amount=90.0),
                LineItem(description="Rebar 12mm", quantity=2, unit_price=8.5, amount=17.0),
            ]
        }
    )
    po = _po(inv)
    po.lines = [
        POLine(line_no=1, description="Rebar 12mm", quantity=2, unit_price=8.5),
        POLine(line_no=2, description="Rebar 12mm", quantity=10, unit_price=8.0),
    ]
    result = _match(inv, po=po, receipts=[_receipt({1: 2, 2: 10})])
    assert codes(result) == ["price_variance"]
    assert [(line.po_line, line.issues) for line in result.lines] == [(2, ["price_variance"]), (1, [])]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"po_vendor": OTHER}, ["vendor_mismatch"]),
        ({"vendor": None}, ["unknown_vendor"]),
        ({"po_inferred": True}, ["po_inferred"]),
        ({"vendor_inferred": True}, ["vendor_inferred"]),
    ],
)
def test_review_issues(invoice, kwargs, expected):
    result = _match(invoice, **kwargs)
    assert codes(result) == expected and decide(result.issues) is Decision.REVIEW


def test_po_level_checks(invoice):
    assert codes(_match(invoice, po=_po(invoice, currency="GBP"))) == ["currency_mismatch"]
    assert codes(_match(invoice, po=_po(invoice, status="closed"))) == ["po_closed"]
    paid = PostedInvoice(
        vendor_id="V1", invoice_number="INV-1001", invoice_date=date(2026, 3, 1), total=118.0, status="paid"
    )
    assert codes(_match(invoice, posted=[paid])) == ["duplicate_invoice"]


def test_no_po_goes_back_to_vendor(invoice):
    result = three_way_match(invoice, vendor=VENDOR, po=None, po_vendor=None, receipts=[], posted=[])
    assert codes(result) == ["no_po_found"] and decide(result.issues) is Decision.VENDOR_QUERY
    assert result.lines == []


def test_extraction_issues(invoice):
    bad = invoice.model_copy(update={"total": 128.0})
    assert [i.code for i in extraction_issues(validate_invoice(bad), [])] == ["invoice_arithmetic_error"]
    issues = extraction_issues(validate_invoice(bad), ["total"])
    assert [i.code for i in issues] == ["low_confidence", "invoice_arithmetic_error"]
    # Unsure extraction outranks the supplier query: a person checks before anyone emails the supplier.
    assert decide(issues) is Decision.REVIEW
    empty = invoice.model_copy(update={"line_items": []})
    assert [i.code for i in extraction_issues(validate_invoice(empty), [])] == ["extraction_error"]
