"""Generate the synthetic invoice eval set: PDFs plus ground-truth JSON.

Deterministic (fixed seed), so re-running reproduces the committed dataset exactly:

    uv run python -m evals.generate

Each case is `evals/data/invoices/<id>.pdf` with `evals/data/labels/<id>.json`. A label
holds the values printed on the invoice (`invoice`, in `InvoiceData` shape), the layout
used, tags describing what makes the case hard, and `expected_issues`: the validation
codes a correct extraction should trigger (non-empty only for invoices where the
supplier's own arithmetic is wrong, or where no PO is printed).
"""

from __future__ import annotations

import json
import random
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4, LETTER
from reportlab.pdfgen.canvas import Canvas

from tallyhawk.schema import InvoiceData, LineItem

SEED = 1042
N_INVOICES = 50
DATA_DIR = Path(__file__).parent / "data"

VENDOR_FIRST = [
    "Northwind",
    "Blue Harbor",
    "Kestrel",
    "Ironbridge",
    "Maple & Finch",
    "Solano",
    "Brightwater",
    "Granite Peak",
    "Lumen",
    "Harbourside",
    "Copperleaf",
    "Vantage",
    "Old Mill",
    "Redfern",
    "Atlas",
]
VENDOR_SECOND = [
    "Supplies",
    "Trading",
    "Logistics",
    "Foods",
    "Systems",
    "Building Materials",
    "Office Solutions",
    "Packaging",
    "Engineering",
    "Catering Supplies",
    "IT Services",
    "Print Works",
]
VENDOR_SUFFIX = {
    "EUR": ["Ltd", "GmbH", "B.V.", "S.r.l.", "Ltd"],
    "GBP": ["Ltd", "plc", "LLP"],
    "USD": ["Inc.", "LLC", "Corp."],
}
BUYERS = [
    "Harbour View Hotels Ltd",
    "Castello Construction Co.",
    "Greenline Restaurants Group",
    "Meridian Property Management",
    "Tidewater Manufacturing",
    "Saltpan Bakery Ltd",
]
STREETS = ["Triq il-Kbira", "High Street", "Market Lane", "Industrial Estate Road", "Harbour Road", "Elm Avenue"]
CITIES = {
    "EUR": ["Valletta", "Rotterdam", "Munich", "Milan", "Dublin"],
    "GBP": ["Leeds", "Bristol", "Glasgow"],
    "USD": ["Austin, TX", "Columbus, OH", "Portland, OR"],
}

CATALOG = [
    ("A4 copy paper, 80gsm (box of 5 reams)", 18, 32),
    ("Toner cartridge, black", 45, 120),
    ("Ballpoint pens (pack of 50)", 6, 14),
    ("Ready-mix concrete, per m3", 85, 140),
    ("Rebar 12mm, 6m length", 7, 15),
    ("Plasterboard sheet 2400x1200", 9, 16),
    ("Olive oil, extra virgin, 5L", 28, 55),
    ("Flour type 00, 25kg sack", 14, 26),
    ("Disposable gloves (box of 100)", 4, 11),
    ("On-site IT support, per hour", 55, 120),
    ("Laptop docking station", 140, 260),
    ("Cat6 patch cable 3m", 2.5, 7),
    ("Pallet delivery, zone 2", 35, 90),
    ("Shrink wrap roll 500mm", 11, 24),
    ("Cleaning chemicals, 10L", 19, 42),
    ("Safety boots, size assorted", 38, 75),
    ("Monthly software licence, per seat", 12, 49),
    ("Printed brochures A5 (per 100)", 22, 60),
    ("Coffee beans 1kg", 14, 29),
    ("Freight surcharge", 15, 60),
]

PO_STYLES = [
    lambda r: f"PO-{r.randint(10000, 99999)}",
    lambda r: f"45000{r.randint(10000, 99999)}",
    lambda r: f"PO/{r.choice([2025, 2026])}/{r.randint(100, 9999):04d}",
    lambda r: f"{r.choice(['HVH', 'CCC', 'GRG', 'MPM'])}-{r.randint(1000, 9999)}",
]
PO_LABELS = ["PO Number", "Purchase Order", "Your Ref (PO)", "Customer PO", "Order No."]
TAX_RATES = {"EUR": [18, 21, 19, 9, 0], "GBP": [20, 20, 5, 0], "USD": [7.5, 8.25, 6, 0]}
TAX_LABEL = {"EUR": "VAT", "GBP": "VAT", "USD": "Sales tax"}
LAYOUTS = ["classic", "modern", "european", "compact", "multipage"]


@dataclass
class Case:
    case_id: str
    layout: str
    invoice: InvoiceData
    buyer: str
    buyer_tax_id: str
    vendor_address: list[str]
    print_tax_rate: bool
    payment_terms_days: int | None
    tags: list[str] = field(default_factory=list)
    expected_issues: list[str] = field(default_factory=list)


def _money(value: float, currency: str, decimal_comma: bool = False, symbol: bool = True) -> str:
    text = f"{value:,.2f}"
    if decimal_comma:
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    if not symbol:
        return text
    sym = {"EUR": "€", "GBP": "£", "USD": "$"}[currency]
    return f"{text} {sym}" if decimal_comma else f"{sym}{text}"


def _qty(value: float, decimal_comma: bool = False) -> str:
    text = f"{value:g}"
    return text.replace(".", ",") if decimal_comma else text


def _date(d: date, style: str) -> str:
    return {
        "iso": d.isoformat(),
        "long": d.strftime("%d %B %Y").lstrip("0"),
        "us": d.strftime("%b %d, %Y").replace(" 0", " "),
        "dotted": d.strftime("%d.%m.%Y"),
    }[style]


def _tax_id(rng: random.Random, currency: str) -> str:
    if currency == "EUR":
        return f"{rng.choice(['MT', 'NL', 'DE', 'IT', 'IE'])}{rng.randint(10_000_000, 99_999_999)}"
    if currency == "GBP":
        return f"GB{rng.randint(100, 999)} {rng.randint(1000, 9999)} {rng.randint(10, 99)}"
    return f"{rng.randint(10, 99)}-{rng.randint(1_000_000, 9_999_999)}"


def make_case(i: int, rng: random.Random) -> Case:
    layout = LAYOUTS[i % len(LAYOUTS)]
    currency = {"european": "EUR", "modern": "USD"}.get(layout) or rng.choice(["EUR", "EUR", "GBP", "USD"])
    tags: list[str] = [layout, currency.lower()]

    vendor = f"{rng.choice(VENDOR_FIRST)} {rng.choice(VENDOR_SECOND)} {rng.choice(VENDOR_SUFFIX[currency])}"
    vendor_address = [f"{rng.randint(1, 240)} {rng.choice(STREETS)}", rng.choice(CITIES[currency])]

    n_items = rng.randint(40, 55) if layout == "multipage" else rng.randint(1, 7)
    items = []
    for desc, lo, hi in rng.sample(CATALOG, min(n_items, len(CATALOG))) + [
        rng.choice(CATALOG) for _ in range(max(0, n_items - len(CATALOG)))
    ]:
        qty = (
            rng.choice([1, 1, 2, 3, 4, 5, 6, 10, 12, 20, 24, 50])
            if "hour" not in desc
            else rng.choice([1.5, 2, 3.5, 8])
        )
        unit = round(rng.uniform(lo, hi), 2)
        items.append(LineItem(description=desc, quantity=qty, unit_price=unit, amount=round(qty * unit, 2)))
    if layout == "multipage":
        tags.append("many_line_items")

    subtotal = round(sum(it.amount for it in items), 2)
    rate = rng.choice(TAX_RATES[currency])
    tax = round(subtotal * rate / 100, 2)
    total = round(subtotal + tax, 2)
    if rate == 0:
        tags.append("zero_tax")

    issued = date(2026, 1, 1) + timedelta(days=rng.randint(0, 270))
    terms = rng.choice([14, 30, 30, 45, 60])
    due: date | None = issued + timedelta(days=terms)
    payment_terms_days: int | None = None
    if rng.random() < 0.12:
        due, payment_terms_days = None, None
        tags.append("no_due_date")

    po = rng.choice(PO_STYLES)(rng) if rng.random() < 0.82 else None
    expected_issues: list[str] = []
    if po is None:
        tags.append("no_po")
        expected_issues.append("missing_po")

    vendor_tax_id = _tax_id(rng, currency) if rng.random() < 0.9 else None
    if vendor_tax_id is None:
        tags.append("no_vendor_tax_id")

    print_tax_rate = rng.random() < 0.85
    if not print_tax_rate:
        tags.append("tax_rate_not_printed")

    # A few suppliers make arithmetic mistakes. Labels keep the *printed* (wrong) values;
    # a correct extraction copies them and validation should flag the mismatch.
    error_kind = None
    if i in (7, 19, 33, 46):
        error_kind = ["total", "line", "total", "line"][[7, 19, 33, 46].index(i)]
    if error_kind == "total":
        total = round(total + rng.choice([10, 1, 0.9, 100]), 2)
        expected_issues.append("total_mismatch")
        tags.append("supplier_error")
    elif error_kind == "line":
        bad = items[0]
        items[0] = LineItem(
            description=bad.description,
            quantity=bad.quantity,
            unit_price=bad.unit_price,
            amount=round(bad.amount + 10, 2),
        )
        subtotal = round(sum(it.amount for it in items), 2)
        tax = round(subtotal * rate / 100, 2)
        total = round(subtotal + tax, 2)
        expected_issues.append("line_amount_mismatch")
        tags.append("supplier_error")

    prefix = rng.choice(["INV-", "", "SI", "F", "2026-"])
    invoice = InvoiceData(
        vendor_name=vendor,
        vendor_tax_id=vendor_tax_id,
        invoice_number=f"{prefix}{rng.randint(1000, 999999)}",
        invoice_date=issued,
        due_date=due,
        po_number=po,
        currency=currency,
        line_items=items,
        subtotal=subtotal,
        tax_rate=float(rate) if print_tax_rate else None,
        tax_amount=tax,
        total=total,
    )
    return Case(
        case_id=f"inv_{i + 1:03d}",
        layout=layout,
        invoice=invoice,
        buyer=rng.choice(BUYERS),
        buyer_tax_id=_tax_id(rng, currency),
        vendor_address=vendor_address,
        print_tax_rate=print_tax_rate,
        payment_terms_days=payment_terms_days,
        tags=tags,
        expected_issues=expected_issues,
    )


# --- rendering -------------------------------------------------------------------------


class Doc:
    """Thin wrapper over a reportlab canvas with a top-down cursor."""

    def __init__(self, path: Path, pagesize=A4):
        self.c = Canvas(str(path), pagesize=pagesize, invariant=1)  # invariant: byte-stable output
        self.w, self.h = pagesize
        self.margin = 50

    def text(self, x: float, y: float, s: str, size: int = 10, bold: bool = False, right: bool = False):
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        (self.c.drawRightString if right else self.c.drawString)(x, self.h - y, s)

    def line(self, y: float):
        self.c.line(self.margin, self.h - y, self.w - self.margin, self.h - y)

    def save(self):
        self.c.showPage()
        self.c.save()


def render(case: Case, path: Path) -> None:
    inv = case.invoice
    dc = case.layout == "european"
    date_style = {"classic": "long", "modern": "us", "european": "dotted", "compact": "iso", "multipage": "long"}[
        case.layout
    ]
    doc = Doc(path, LETTER if case.layout == "modern" else A4)
    m, right = doc.margin, doc.w - doc.margin
    rng = random.Random(case.case_id)
    po_label = rng.choice(PO_LABELS)
    tax_label = TAX_LABEL[inv.currency]

    def money(v: float, symbol: bool = True) -> str:
        return _money(v, inv.currency, dc, symbol)

    # Header
    if case.layout == "modern":
        doc.text(m, 60, inv.vendor_name.upper(), 18, bold=True)
        doc.text(right, 60, "INVOICE", 22, bold=True, right=True)
    elif case.layout == "european":
        doc.text(right, 60, inv.vendor_name, 16, bold=True, right=True)
        doc.text(m, 60, "Rechnung / Invoice", 18, bold=True)
    else:
        doc.text(m, 60, inv.vendor_name, 15, bold=True)
        doc.text(right, 60, "TAX INVOICE" if inv.currency != "USD" else "INVOICE", 14, bold=True, right=True)

    y = 80
    for addr in case.vendor_address:
        doc.text(m, y, addr, 9)
        y += 12
    if inv.vendor_tax_id:
        label = "EIN" if inv.currency == "USD" else "VAT Reg No"
        doc.text(m, y, f"{label}: {inv.vendor_tax_id}", 9)

    meta = [("Invoice No.", inv.invoice_number), ("Invoice Date", _date(inv.invoice_date, date_style))]
    if inv.due_date:
        meta.append(("Due Date" if case.layout != "compact" else "Pay by", _date(inv.due_date, date_style)))
    if inv.po_number:
        meta.append((po_label, inv.po_number))
    my = 85
    for label, value in meta:
        doc.text(right - 150, my, f"{label}:", 9, bold=True)
        doc.text(right, my, value, 9, right=True)
        my += 13

    # Bill-to block, with the *buyer's* tax ID as a distractor.
    y = max(y, my) + 25
    doc.text(m, y, "Bill to:", 9, bold=True)
    doc.text(m, y + 13, case.buyer, 9)
    doc.text(m, y + 26, f"Customer VAT/Tax ID: {case.buyer_tax_id}", 9)
    y += 55

    # Line items
    cols = [m, right - 210, right - 120, right]
    headers = ["Description", "Qty", "Unit price", "Amount"]

    def table_header(y: float) -> float:
        doc.line(y - 10)
        for idx, (x, hdr) in enumerate(zip(cols, headers, strict=True)):
            doc.text(x, y, hdr, 9, bold=True, right=idx > 0)
        doc.line(y + 5)
        return y + 20

    y = table_header(y)
    page = 1
    for item in inv.line_items:
        if y > doc.h - 90:
            doc.text(right, doc.h - 40, f"Page {page} - continued overleaf", 8, right=True)
            doc.c.showPage()
            page += 1
            doc.text(m, 50, f"{inv.vendor_name} - Invoice {inv.invoice_number} (continued)", 9, bold=True)
            y = table_header(80)
        doc.text(cols[0], y, item.description, 9)
        doc.text(cols[1], y, _qty(item.quantity, dc), 9, right=True)
        doc.text(cols[2], y, money(item.unit_price, symbol=False), 9, right=True)
        doc.text(cols[3], y, money(item.amount, symbol=False), 9, right=True)
        y += 15
    doc.line(y - 8)

    # Totals
    y += 10
    tax_name = (
        f"{tax_label} {_qty(inv.tax_rate, dc)}%" if case.print_tax_rate and inv.tax_rate is not None else tax_label
    )
    if inv.tax_amount == 0 and inv.currency != "USD":
        tax_name += " (exempt / reverse charge)"
    for label, value, bold in [
        ("Subtotal" if case.layout != "european" else "Net amount", inv.subtotal, False),
        (tax_name, inv.tax_amount, False),
        ("TOTAL DUE" if case.layout != "european" else "Total amount", inv.total, True),
    ]:
        doc.text(right - 120, y, label, 10, bold=bold, right=True)
        doc.text(right, y, money(value), 10, bold=bold, right=True)
        y += 15

    # Footer
    y += 25
    doc.text(m, y, f"All amounts in {inv.currency}.", 8)
    if inv.due_date is None:
        doc.text(m, y + 12, "Payment terms: as per agreement.", 8)
    doc.text(m, doc.h - 70 - (doc.h - 842 if doc.h != 842 else 0), "Thank you for your business.", 8)
    if page > 1:
        doc.text(right, doc.h - 40, f"Page {page} of {page}", 8, right=True)
    doc.save()


def label_for(case: Case) -> dict:
    return {
        "case_id": case.case_id,
        "layout": case.layout,
        "tags": case.tags,
        "expected_issues": sorted(case.expected_issues),
        "invoice": json.loads(case.invoice.model_dump_json()),
    }


def build_cases(n: int = N_INVOICES, seed: int = SEED) -> list[Case]:
    rng = random.Random(seed)
    return [make_case(i, rng) for i in range(n)]


def main() -> None:
    inv_dir, lbl_dir = DATA_DIR / "invoices", DATA_DIR / "labels"
    for d in (inv_dir, lbl_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    cases = build_cases()
    for case in cases:
        render(case, inv_dir / f"{case.case_id}.pdf")
        (lbl_dir / f"{case.case_id}.json").write_text(json.dumps(label_for(case), indent=2) + "\n")
    print(f"Wrote {len(cases)} invoices to {DATA_DIR}")


if __name__ == "__main__":
    main()
