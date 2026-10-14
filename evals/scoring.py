"""Compare an extracted invoice with its ground-truth label, field by field."""

from __future__ import annotations

import re
from datetime import date

from tallyhawk.schema import HEADER_FIELDS, InvoiceData

AMOUNT_TOLERANCE = 0.005  # amounts must match to the cent
LINE_FIELDS = ("description", "quantity", "unit_price", "amount")
ID_FIELDS = frozenset({"vendor_tax_id", "invoice_number", "po_number"})


def _norm_text(value: str) -> str:
    """Case-, punctuation- and whitespace-insensitive form of free text (names, descriptions)."""
    return " ".join(re.sub(r"[^\w\s]", " ", value.casefold()).split())


def _norm_id(value: str) -> str:
    """IDs must match character for character, ignoring case and whitespace."""
    return re.sub(r"\s+", "", value.casefold())


def values_match(field: str, predicted: object, expected: object) -> bool:
    if expected is None or predicted is None:
        return predicted is None and expected is None
    if isinstance(expected, float | int) and not isinstance(expected, bool):
        return isinstance(predicted, float | int) and abs(float(predicted) - float(expected)) <= AMOUNT_TOLERANCE
    if isinstance(expected, date):
        return predicted == expected
    if field in ID_FIELDS:
        return _norm_id(str(predicted)) == _norm_id(str(expected))
    if field == "currency":
        return str(predicted).strip().upper() == str(expected).strip().upper()
    return _norm_text(str(predicted)) == _norm_text(str(expected))


def score_invoice(predicted: InvoiceData, expected: InvoiceData) -> dict:
    """Return per-field correctness plus line-item stats for one invoice.

    Line items are aligned by position (invoices list them in a fixed order); a missing
    or extra line counts every field of that line as wrong.
    """
    fields = {name: values_match(name, getattr(predicted, name), getattr(expected, name)) for name in HEADER_FIELDS}

    pred_lines, gold_lines = predicted.line_items, expected.line_items
    line_correct = 0
    line_total = len(LINE_FIELDS) * max(len(pred_lines), len(gold_lines))
    for p, g in zip(pred_lines, gold_lines, strict=False):
        line_correct += sum(values_match(f, getattr(p, f), getattr(g, f)) for f in LINE_FIELDS)

    fields["line_item_count"] = len(pred_lines) == len(gold_lines)
    fields["line_items"] = fields["line_item_count"] and line_correct == line_total
    return {
        "fields": fields,
        "line_fields_correct": line_correct,
        "line_fields_total": line_total,
        "all_correct": all(fields.values()),
    }
