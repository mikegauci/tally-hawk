"""Deterministic checks on an extracted invoice.

These run after extraction and catch both extraction mistakes and genuine supplier
errors (an invoice whose printed totals don't add up). Either way the invoice
should go to a human.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from tallyhawk.schema import ExtractedInvoice, InvoiceData

# Allowed rounding difference, in currency units, when comparing printed amounts.
TOLERANCE = 0.02
DEFAULT_CONFIDENCE_THRESHOLD = 0.9


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ValidationIssue(BaseModel):
    code: str
    severity: Severity
    message: str


def _close(a: float, b: float, tolerance: float = TOLERANCE) -> bool:
    return abs(a - b) <= tolerance


def validate_invoice(inv: InvoiceData) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def add(code: str, severity: Severity, message: str) -> None:
        issues.append(ValidationIssue(code=code, severity=severity, message=message))

    if not inv.line_items:
        add("no_line_items", Severity.ERROR, "No line items were extracted.")

    for i, item in enumerate(inv.line_items, start=1):
        expected = round(item.quantity * item.unit_price, 2)
        if not _close(expected, item.amount):
            add(
                "line_amount_mismatch",
                Severity.ERROR,
                f"Line {i} ({item.description!r}): {item.quantity} x {item.unit_price} = {expected}, "
                f"but amount is {item.amount}.",
            )

    if inv.line_items:
        lines_sum = round(sum(item.amount for item in inv.line_items), 2)
        if not _close(lines_sum, inv.subtotal):
            add(
                "subtotal_mismatch",
                Severity.ERROR,
                f"Line items sum to {lines_sum}, but subtotal is {inv.subtotal}.",
            )

    if not _close(inv.subtotal + inv.tax_amount, inv.total):
        add(
            "total_mismatch",
            Severity.ERROR,
            f"Subtotal {inv.subtotal} + tax {inv.tax_amount} = {round(inv.subtotal + inv.tax_amount, 2)}, "
            f"but total is {inv.total}.",
        )

    if inv.tax_rate is not None:
        expected_tax = round(inv.subtotal * inv.tax_rate / 100, 2)
        if not _close(expected_tax, inv.tax_amount):
            add(
                "tax_mismatch",
                Severity.ERROR,
                f"{inv.tax_rate}% of {inv.subtotal} is {expected_tax}, but tax is {inv.tax_amount}.",
            )

    if inv.due_date is not None and inv.due_date < inv.invoice_date:
        add("due_before_issue", Severity.WARNING, "Due date is before the invoice date.")

    if inv.po_number is None:
        add("missing_po", Severity.WARNING, "No PO number found; the invoice can't be auto-matched.")

    if inv.total <= 0:
        add("non_positive_total", Severity.WARNING, f"Total is {inv.total}; possibly a credit note.")

    return issues


def low_confidence_fields(extracted: ExtractedInvoice, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> list[str]:
    scores = extracted.confidence.model_dump()
    return sorted(name for name, score in scores.items() if score < threshold)


def needs_review(issues: list[ValidationIssue], low_confidence: list[str]) -> bool:
    return bool(low_confidence) or any(i.severity is Severity.ERROR for i in issues)
