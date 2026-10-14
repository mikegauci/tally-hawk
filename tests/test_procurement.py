"""Vendor name matching and the in-memory store."""

from datetime import date

import pytest

from tallyhawk.procurement import (
    InMemoryStore,
    POLine,
    PurchaseOrder,
    Vendor,
    normalize_vendor_name,
    vendor_name_similarity,
)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Maple & Finch Supplies Ltd", "MAPLE AND FINCH SUPPLIES LIMITED"),
        ("Ironbridge Engineering B.V.", "Ironbridge Engineering BV"),
        ("Old Mill Supplies S.r.l.", "Old Mill Supplies SRL"),
        ("Solano Supplies LLC", "Solano Supplies L.L.C."),
    ],
)
def test_name_variants_normalize_the_same(a, b):
    assert normalize_vendor_name(a) == normalize_vendor_name(b)
    assert vendor_name_similarity(a, b) == 1.0


def test_different_businesses_score_low():
    assert vendor_name_similarity("Kestrel Building Materials Ltd", "Kestrel Logistics Ltd") < 0.7


def _vendor(vendor_id, name, tax_id):
    return Vendor(vendor_id=vendor_id, name=name, tax_id=tax_id, email="a@b.example", address="x")


def _store():
    vendors = [
        _vendor("V1", "Ironbridge Engineering B.V.", "NL11111111"),
        _vendor("V2", "Ironbridge Engineering B.V.", "NL22222222"),
        _vendor("V3", "Kestrel Logistics Ltd", "MT33333333"),
    ]
    po = PurchaseOrder(
        po_number="PO-31244",
        vendor_id="V1",
        order_date=date(2026, 1, 1),
        currency="EUR",
        status="open",
        lines=[POLine(line_no=1, description="Rebar", quantity=2, unit_price=10)],
    )
    return InMemoryStore(vendors, [po], [], [])


def test_tax_id_beats_name_tie():
    best = _store().search_vendors("Ironbridge Engineering BV", "NL 2222 2222")[0]
    assert best.vendor.vendor_id == "V2" and best.reason == "tax ID matches"


def test_po_lookup_ignores_case_and_spaces_and_suggests_near_numbers():
    store = _store()
    assert store.get_purchase_order(" po-31244 ").po_number == "PO-31244"
    assert store.get_purchase_order("PO-31245") is None
    assert store.similar_po_numbers("PO-31245") == ["PO-31244"]
    assert store.similar_po_numbers("ZZZ-1") == []


def test_open_pos_for_vendor():
    store = _store()
    assert [po.po_number for po in store.purchase_orders_for_vendor("V1")] == ["PO-31244"]
    assert store.purchase_orders_for_vendor("V3") == []
