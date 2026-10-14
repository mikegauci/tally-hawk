"""Three-way match and the approval decision.

A *three-way match* checks that the invoice (what the supplier bills), the purchase order
(what was agreed) and the goods receipts (what actually arrived) agree. Everything here is
deterministic so a finance team can audit why an invoice was approved; the LLM only helps
find the right PO when the invoice doesn't point to one, and drafts emails.

Each problem found is a `MatchIssue` with a route:

- `review`: a person in the finance team has to look (possible duplicate, wrong supplier,
  goods not yet received, PO found by the agent rather than printed).
- `vendor`: the supplier has to fix something (charged more than agreed, billed for goods
  that didn't arrive, items not on the PO, arithmetic errors).

The decision is `review` if any issue needs a person, else `vendor_query` if any issue goes
back to the supplier, else `approve`.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from enum import StrEnum

from pydantic import BaseModel

from tallyhawk.procurement import (
    GoodsReceipt,
    PostedInvoice,
    PurchaseOrder,
    Vendor,
    normalize_ref,
    vendor_name_similarity,
)
from tallyhawk.schema import InvoiceData
from tallyhawk.validation import Severity, ValidationIssue

VENDOR_NAME_THRESHOLD = 0.85
ARITHMETIC_ISSUES = frozenset({"line_amount_mismatch", "subtotal_mismatch", "total_mismatch", "tax_mismatch"})


class Decision(StrEnum):
    APPROVE = "approve"
    REVIEW = "review"
    VENDOR_QUERY = "vendor_query"


class Route(StrEnum):
    REVIEW = "review"
    VENDOR = "vendor"


class MatchIssue(BaseModel):
    code: str
    route: Route
    message: str


class Tolerances(BaseModel):
    """How far the invoice may drift from the PO before it's flagged.

    Small price differences (rounding, a few cents) are normal and not worth a query;
    quantities must match exactly by default.
    """

    price_pct: float = 1.0  # percent above the PO unit price
    price_abs: float = 0.01  # or this many currency units, whichever is larger
    quantity: float = 0.0


class LineMatch(BaseModel):
    invoice_line: int
    description: str
    po_line: int | None
    billed_qty: float
    ordered_qty: float | None
    received_qty: float | None
    invoice_price: float
    po_price: float | None
    issues: list[str]


class MatchResult(BaseModel):
    issues: list[MatchIssue]
    lines: list[LineMatch]


def _norm_desc(text: str) -> str:
    return " ".join(text.casefold().split())


def _price_ok(invoice_price: float, po_price: float, tol: Tolerances) -> bool:
    return invoice_price - po_price <= max(tol.price_abs, po_price * tol.price_pct / 100) + 1e-9


def _pair_lines(invoice: InvoiceData, po: PurchaseOrder, tol: Tolerances) -> dict[int, int]:
    """Pair each invoice line with a PO line (invoice index -> PO line_no).

    Pass 1 takes exact matches (same description, price within tolerance, same quantity) so
    a repeated item can't steal another line's partner. Pass 2 pairs what's left by
    description, closest price first, falling back to near-identical descriptions.
    """
    remaining = {line.line_no: line for line in po.lines}
    pairs: dict[int, int] = {}
    for i, item in enumerate(invoice.line_items):
        for no, line in remaining.items():
            if (
                _norm_desc(line.description) == _norm_desc(item.description)
                and _price_ok(item.unit_price, line.unit_price, tol)
                and abs(item.quantity - line.quantity) <= tol.quantity
            ):
                pairs[i] = no
                del remaining[no]
                break
    for i, item in enumerate(invoice.line_items):
        if i in pairs or not remaining:
            continue
        same = [line for line in remaining.values() if _norm_desc(line.description) == _norm_desc(item.description)]
        if same:
            best = min(same, key=lambda line: abs(line.unit_price - item.unit_price))
        else:
            scored = [
                (SequenceMatcher(None, _norm_desc(line.description), _norm_desc(item.description)).ratio(), line)
                for line in remaining.values()
            ]
            score, best = max(scored, key=lambda pair: pair[0])
            if score < 0.85:
                continue
        pairs[i] = best.line_no
        del remaining[best.line_no]
    return pairs


def vendor_matches(invoice: InvoiceData, vendor: Vendor) -> bool:
    """Is this invoice from this vendor? Tax IDs decide when both are known; otherwise the name."""
    if invoice.vendor_tax_id and vendor.tax_id:
        return normalize_ref(invoice.vendor_tax_id) == normalize_ref(vendor.tax_id)
    return vendor_name_similarity(invoice.vendor_name, vendor.name) >= VENDOR_NAME_THRESHOLD


def three_way_match(
    invoice: InvoiceData,
    *,
    vendor: Vendor | None,
    po: PurchaseOrder | None,
    po_vendor: Vendor | None,
    receipts: list[GoodsReceipt],
    posted: list[PostedInvoice],
    po_inferred: bool = False,
    vendor_inferred: bool = False,
    tolerances: Tolerances | None = None,
) -> MatchResult:
    """Compare the invoice with its PO and goods receipts.

    `vendor` is who sent the invoice (as identified from its name/tax ID), `po_vendor` who
    the PO was raised with. `po_inferred` means the PO was found by searching rather than
    read off the invoice, so a person should confirm the link.
    """
    tol = tolerances or Tolerances()
    issues: list[MatchIssue] = []

    def add(code: str, route: Route, message: str) -> None:
        issues.append(MatchIssue(code=code, route=route, message=message))

    if vendor is None:
        add(
            "unknown_vendor",
            Route.REVIEW,
            f"{invoice.vendor_name!r} isn't a known supplier; it may need setting up before payment.",
        )
    elif vendor_inferred:
        add(
            "vendor_inferred",
            Route.REVIEW,
            f"{invoice.vendor_name!r} was matched to supplier {vendor.name} by the agent, not by name or tax ID.",
        )
    if vendor is not None and posted:
        prior = posted[0]
        add(
            "duplicate_invoice",
            Route.REVIEW,
            f"Invoice {invoice.invoice_number} from {vendor.name} was already {prior.status} "
            f"(dated {prior.invoice_date}, total {prior.total}).",
        )

    if po is None:
        printed = f"PO {invoice.po_number} isn't on file" if invoice.po_number else "The invoice quotes no PO"
        add("no_po_found", Route.VENDOR, f"{printed}, and no matching open PO was found.")
        return MatchResult(issues=issues, lines=[])

    if po_inferred:
        printed = f"quotes {invoice.po_number}" if invoice.po_number else "quotes no PO"
        add("po_inferred", Route.REVIEW, f"The invoice {printed}; the best matching PO on file is {po.po_number}.")
    if po_vendor is not None and vendor is not None and po_vendor.vendor_id != vendor.vendor_id:
        add(
            "vendor_mismatch",
            Route.REVIEW,
            f"{po.po_number} was raised with {po_vendor.name}, but this invoice is from {vendor.name}.",
        )
    if po.status == "closed":
        add("po_closed", Route.REVIEW, f"{po.po_number} is closed.")
    if invoice.currency.upper() != po.currency.upper():
        add(
            "currency_mismatch",
            Route.REVIEW,
            f"The invoice is in {invoice.currency} but {po.po_number} is in {po.currency}.",
        )

    received: dict[int, float] = {}
    for receipt in receipts:
        for rl in receipt.lines:
            received[rl.po_line] = received.get(rl.po_line, 0.0) + rl.quantity
    if not receipts:
        add(
            "no_goods_receipt",
            Route.REVIEW,
            f"Nothing has been recorded as received against {po.po_number} yet.",
        )

    pairs = _pair_lines(invoice, po, tol)
    po_lines = {line.line_no: line for line in po.lines}
    lines: list[LineMatch] = []
    for i, item in enumerate(invoice.line_items):
        line = po_lines.get(pairs[i]) if i in pairs else None
        line_issues: list[str] = []
        if line is None:
            line_issues.append("line_not_on_po")
            add(
                "line_not_on_po",
                Route.VENDOR,
                f"Line {i + 1} ({item.description!r}, {item.amount}) isn't on {po.po_number}.",
            )
        else:
            if not _price_ok(item.unit_price, line.unit_price, tol):
                line_issues.append("price_variance")
                add(
                    "price_variance",
                    Route.VENDOR,
                    f"Line {i + 1} ({item.description!r}) is billed at {item.unit_price} per unit; "
                    f"{po.po_number} agreed {line.unit_price}.",
                )
            if item.quantity - line.quantity > tol.quantity + 1e-9:
                line_issues.append("qty_exceeds_ordered")
                add(
                    "qty_exceeds_ordered",
                    Route.VENDOR,
                    f"Line {i + 1} ({item.description!r}) bills {item.quantity:g}; "
                    f"only {line.quantity:g} were ordered.",
                )
            got = received.get(line.line_no, 0.0)
            if receipts and item.quantity - got > tol.quantity + 1e-9:
                line_issues.append("qty_exceeds_received")
                add(
                    "qty_exceeds_received",
                    Route.VENDOR,
                    f"Line {i + 1} ({item.description!r}) bills {item.quantity:g}; {got:g} were received.",
                )
        lines.append(
            LineMatch(
                invoice_line=i + 1,
                description=item.description,
                po_line=line.line_no if line else None,
                billed_qty=item.quantity,
                ordered_qty=line.quantity if line else None,
                received_qty=received.get(line.line_no, 0.0) if line and receipts else None,
                invoice_price=item.unit_price,
                po_price=line.unit_price if line else None,
                issues=line_issues,
            )
        )
    return MatchResult(issues=issues, lines=lines)


def extraction_issues(validation: list[ValidationIssue], low_confidence: list[str]) -> list[MatchIssue]:
    """Turn step 1's validation results into match issues.

    Arithmetic errors on a confidently-read invoice are the supplier's mistake, so they go
    back to the supplier. Anything the extraction was unsure about goes to a person first,
    so we never send a supplier a query based on a misread.
    """
    issues: list[MatchIssue] = []
    if low_confidence:
        issues.append(
            MatchIssue(
                code="low_confidence",
                route=Route.REVIEW,
                message=f"Extraction was unsure about: {', '.join(low_confidence)}.",
            )
        )
    errors = [i for i in validation if i.severity is Severity.ERROR]
    arithmetic = [i for i in errors if i.code in ARITHMETIC_ISSUES]
    if arithmetic:
        issues.append(
            MatchIssue(
                code="invoice_arithmetic_error",
                route=Route.VENDOR,
                message=" ".join(i.message for i in arithmetic),
            )
        )
    other = [i for i in errors if i.code not in ARITHMETIC_ISSUES]
    if other:
        issues.append(
            MatchIssue(code="extraction_error", route=Route.REVIEW, message=" ".join(i.message for i in other))
        )
    return issues


def decide(issues: list[MatchIssue]) -> Decision:
    if any(i.route is Route.REVIEW for i in issues):
        return Decision.REVIEW
    if any(i.route is Route.VENDOR for i in issues):
        return Decision.VENDOR_QUERY
    return Decision.APPROVE
