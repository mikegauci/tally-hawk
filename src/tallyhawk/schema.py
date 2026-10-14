"""Pydantic models for invoice extraction.

`ExtractedInvoice` is the schema the model fills in (via structured outputs), so every
field description here is part of the prompt. Keep descriptions precise.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

# Header fields scored by the eval harness and covered by a confidence score.
HEADER_FIELDS: tuple[str, ...] = (
    "vendor_name",
    "vendor_tax_id",
    "invoice_number",
    "invoice_date",
    "due_date",
    "po_number",
    "currency",
    "subtotal",
    "tax_rate",
    "tax_amount",
    "total",
)

MONEY_FIELDS: frozenset[str] = frozenset({"subtotal", "tax_amount", "total"})


class LineItem(BaseModel):
    description: str = Field(description="Item or service description as printed.")
    quantity: float = Field(description="Quantity billed. Use 1 if the line has no quantity.")
    unit_price: float = Field(description="Price per unit, excluding tax.")
    amount: float = Field(description="Line total as printed (normally quantity x unit price), excluding tax.")


class InvoiceData(BaseModel):
    vendor_name: str = Field(description="Legal or trading name of the supplier issuing the invoice.")
    vendor_tax_id: str | None = Field(
        description="Supplier VAT / GST / tax registration number, exactly as printed. Null if absent."
    )
    invoice_number: str = Field(description="The supplier's invoice number, exactly as printed.")
    invoice_date: date = Field(description="Issue date of the invoice.")
    due_date: date | None = Field(description="Payment due date. Null if not stated.")
    po_number: str | None = Field(
        description="Buyer's purchase order (PO) reference, exactly as printed. Null if the invoice has none."
    )
    currency: str = Field(description="ISO 4217 currency code, e.g. EUR, GBP, USD.")
    line_items: list[LineItem] = Field(description="Every billed line, in the order printed.")
    subtotal: float = Field(description="Total before tax, as printed.")
    tax_rate: float | None = Field(
        description="Tax rate as a percentage (e.g. 18 for 18%). Null if no single rate is printed."
    )
    tax_amount: float = Field(description="Total tax charged, as printed. 0 if no tax is charged.")
    total: float = Field(description="Amount due including tax, as printed.")


class FieldConfidence(BaseModel):
    """The model's self-reported confidence (0.0 to 1.0) for each header field."""

    vendor_name: float
    vendor_tax_id: float
    invoice_number: float
    invoice_date: float
    due_date: float
    po_number: float
    currency: float
    subtotal: float
    tax_rate: float
    tax_amount: float
    total: float
    line_items: float


class ExtractedInvoice(BaseModel):
    """The full structured output requested from the model."""

    invoice: InvoiceData
    confidence: FieldConfidence = Field(
        description=(
            "Confidence from 0.0 to 1.0 that each extracted value is correct. Use 0.95+ only when the "
            "value is printed clearly and unambiguously; lower it for inferred, ambiguous, partly "
            "illegible or computed values. A correctly-null field you are sure is absent scores high."
        )
    )
    notes: str | None = Field(
        description="Anything a reviewer should know (ambiguities, inferred values). Null if nothing."
    )
