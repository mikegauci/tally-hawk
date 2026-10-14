"""Procurement records the matcher checks invoices against, and the store that serves them.

Three documents take part in a three-way match:

- **Purchase order (PO):** what the buyer agreed to buy, from whom, how many, at what price.
- **Goods receipt (GRN):** what the warehouse actually received against that PO. One PO can
  have several receipts when goods arrive in batches.
- **Invoice:** what the supplier is billing.

`ProcurementStore` is the interface the matching workflow uses. `InMemoryStore` loads the
seed JSON files; `tallyhawk.db.PostgresStore` serves the same data from Postgres/Supabase.
Both rank candidates with `rank_vendors` and `rank_similar_refs`, so they answer alike.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

VENDOR_CANDIDATE_MIN_SCORE = 0.5

# Words that say what kind of company it is, not which company. Dropped before comparing names.
LEGAL_SUFFIXES = frozenset(
    {
        "ag",
        "bv",
        "co",
        "company",
        "corp",
        "corporation",
        "gmbh",
        "inc",
        "incorporated",
        "limited",
        "llc",
        "llp",
        "ltd",
        "plc",
        "sa",
        "srl",
    }
)


class Vendor(BaseModel):
    vendor_id: str
    name: str
    tax_id: str | None
    email: str
    address: str


class POLine(BaseModel):
    line_no: int
    description: str
    quantity: float
    unit_price: float

    @property
    def amount(self) -> float:
        return round(self.quantity * self.unit_price, 2)


class PurchaseOrder(BaseModel):
    po_number: str
    vendor_id: str
    order_date: date
    currency: str
    status: Literal["open", "closed"]
    lines: list[POLine]

    @property
    def total(self) -> float:
        return round(sum(line.amount for line in self.lines), 2)


class ReceiptLine(BaseModel):
    po_line: int
    quantity: float


class GoodsReceipt(BaseModel):
    receipt_number: str
    po_number: str
    received_date: date
    lines: list[ReceiptLine]


class PostedInvoice(BaseModel):
    """An invoice already entered in the accounting system (used to catch duplicates)."""

    vendor_id: str
    invoice_number: str
    invoice_date: date
    total: float
    status: Literal["posted", "paid"]


class VendorCandidate(BaseModel):
    vendor: Vendor
    score: float
    reason: str


def normalize_vendor_name(name: str) -> str:
    """'Maple & Finch Supplies Ltd.' and 'MAPLE AND FINCH SUPPLIES LIMITED' both become 'maple and finch supplies'."""
    text = name.casefold().replace("&", " and ").replace(".", "")
    tokens = re.sub(r"[^\w\s]", " ", text).split()
    return " ".join(t for t in tokens if t not in LEGAL_SUFFIXES)


def vendor_name_similarity(a: str, b: str) -> float:
    return round(SequenceMatcher(None, normalize_vendor_name(a), normalize_vendor_name(b)).ratio(), 3)


def normalize_ref(value: str) -> str:
    """Document numbers compare ignoring case and whitespace."""
    return re.sub(r"\s+", "", value).casefold()


def rank_vendors(vendors: Iterable[Vendor], name: str, tax_id: str | None, limit: int = 5) -> list[VendorCandidate]:
    """Rank vendors by tax ID (exact) and then name similarity.

    Lexical similarity is enough for suffix, case and abbreviation variants. Embeddings
    (pgvector) could replace it for trading names that share no words with the legal name.
    """
    candidates = []
    for vendor in vendors:
        if tax_id and vendor.tax_id and normalize_ref(tax_id) == normalize_ref(vendor.tax_id):
            candidates.append(VendorCandidate(vendor=vendor, score=1.0, reason="tax ID matches"))
            continue
        score = vendor_name_similarity(name, vendor.name)
        if score >= VENDOR_CANDIDATE_MIN_SCORE:
            candidates.append(VendorCandidate(vendor=vendor, score=score, reason="name similarity"))
    candidates.sort(key=lambda c: (c.reason != "tax ID matches", -c.score, c.vendor.vendor_id))
    return candidates[:limit]


def rank_similar_refs(target: str, numbers: Iterable[str], limit: int = 3) -> list[str]:
    """Document numbers that look like a typo of `target`, best first."""
    key = normalize_ref(target)
    scored = [(SequenceMatcher(None, key, normalize_ref(n)).ratio(), n) for n in numbers]
    return [number for score, number in sorted(scored, reverse=True)[:limit] if score >= 0.8]


class ProcurementStore(Protocol):
    def get_vendor(self, vendor_id: str) -> Vendor | None: ...

    def search_vendors(self, name: str, tax_id: str | None = None, limit: int = 5) -> list[VendorCandidate]: ...

    def get_purchase_order(self, po_number: str) -> PurchaseOrder | None: ...

    def similar_po_numbers(self, po_number: str, limit: int = 3) -> list[str]: ...

    def purchase_orders_for_vendor(self, vendor_id: str, include_closed: bool = False) -> list[PurchaseOrder]: ...

    def goods_receipts(self, po_number: str) -> list[GoodsReceipt]: ...

    def posted_invoices(self, vendor_id: str, invoice_number: str) -> list[PostedInvoice]: ...


class InMemoryStore:
    """Procurement data held in memory, loaded from the seed JSON files."""

    def __init__(
        self,
        vendors: list[Vendor],
        purchase_orders: list[PurchaseOrder],
        goods_receipts: list[GoodsReceipt],
        posted_invoices: list[PostedInvoice],
    ):
        self.vendors = {v.vendor_id: v for v in vendors}
        self.purchase_orders = {normalize_ref(po.po_number): po for po in purchase_orders}
        self.receipts = goods_receipts
        self.invoices = posted_invoices

    @classmethod
    def from_dir(cls, path: str | Path) -> InMemoryStore:
        path = Path(path)

        def load(name: str, model: type[BaseModel]) -> list:
            return [model.model_validate(row) for row in json.loads((path / f"{name}.json").read_text())]

        return cls(
            vendors=load("vendors", Vendor),
            purchase_orders=load("purchase_orders", PurchaseOrder),
            goods_receipts=load("goods_receipts", GoodsReceipt),
            posted_invoices=load("posted_invoices", PostedInvoice),
        )

    def get_vendor(self, vendor_id: str) -> Vendor | None:
        return self.vendors.get(vendor_id)

    def search_vendors(self, name: str, tax_id: str | None = None, limit: int = 5) -> list[VendorCandidate]:
        return rank_vendors(self.vendors.values(), name, tax_id, limit)

    def get_purchase_order(self, po_number: str) -> PurchaseOrder | None:
        return self.purchase_orders.get(normalize_ref(po_number))

    def similar_po_numbers(self, po_number: str, limit: int = 3) -> list[str]:
        return rank_similar_refs(po_number, [po.po_number for po in self.purchase_orders.values()], limit)

    def purchase_orders_for_vendor(self, vendor_id: str, include_closed: bool = False) -> list[PurchaseOrder]:
        return [
            po
            for po in self.purchase_orders.values()
            if po.vendor_id == vendor_id and (include_closed or po.status == "open")
        ]

    def goods_receipts(self, po_number: str) -> list[GoodsReceipt]:
        key = normalize_ref(po_number)
        return [r for r in self.receipts if normalize_ref(r.po_number) == key]

    def posted_invoices(self, vendor_id: str, invoice_number: str) -> list[PostedInvoice]:
        key = normalize_ref(invoice_number)
        return [i for i in self.invoices if i.vendor_id == vendor_id and normalize_ref(i.invoice_number) == key]
