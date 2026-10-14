import json
from pathlib import Path

import pytest

from tallyhawk.schema import HEADER_FIELDS, ExtractedInvoice, FieldConfidence, InvoiceData

LABELS_DIR = Path(__file__).parent.parent / "evals" / "data" / "labels"


@pytest.fixture
def gold_labels() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(LABELS_DIR.glob("*.json"))]


@pytest.fixture
def invoice() -> InvoiceData:
    return InvoiceData.model_validate(
        {
            "vendor_name": "Kestrel Building Materials Ltd",
            "vendor_tax_id": "MT12345678",
            "invoice_number": "INV-1001",
            "invoice_date": "2026-03-01",
            "due_date": "2026-03-31",
            "po_number": "PO-55120",
            "currency": "EUR",
            "line_items": [
                {"description": "Rebar 12mm", "quantity": 10, "unit_price": 8.5, "amount": 85.0},
                {"description": "Freight surcharge", "quantity": 1, "unit_price": 15.0, "amount": 15.0},
            ],
            "subtotal": 100.0,
            "tax_rate": 18.0,
            "tax_amount": 18.0,
            "total": 118.0,
        }
    )


def make_extracted(invoice: InvoiceData, confidence: float = 0.98) -> ExtractedInvoice:
    scores = {name: confidence for name in (*HEADER_FIELDS, "line_items")}
    return ExtractedInvoice(invoice=invoice, confidence=FieldConfidence(**scores), notes=None)
