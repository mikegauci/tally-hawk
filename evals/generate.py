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

import io
import json
import random
import shutil
import textwrap
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import reportlab
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from tallyhawk.schema import InvoiceData, LineItem

SEED = 1042
N_STANDARD = 50
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

# The hard set: (kind, layout) for each extra invoice, appended after the 50 standard ones.
# Each kind is a tag in the label, so the report breaks accuracy down by it.
HARD_KINDS: list[tuple[str, str]] = [
    ("scanned_rotated", "classic"),  # page scanned sideways
    ("scanned_rotated", "compact"),
    ("scanned_skewed", "classic"),  # crooked, noisy scan
    ("scanned_skewed", "european"),
    ("scanned_skewed", "modern"),
    ("low_res", "european"),  # fax-quality image: decimal commas are barely readable
    ("low_res", "compact"),
    ("low_res", "classic"),
    ("handwritten_po", "classic"),  # PO number only written by hand, not printed
    ("handwritten_po", "compact"),
    ("handwritten_note", "european"),  # buyer's scribbled part-payment note: not invoice data
    ("two_column", "two_column"),  # details and totals in a sidebar, wrapped descriptions, SKUs
    ("two_column", "two_column"),
    ("two_column", "two_column"),
    ("deposit_paid", "classic"),  # invoice total vs smaller balance due after a deposit
    ("mixed_tax_rates", "european"),  # two VAT rates, so no single tax rate
    ("dual_currency", "modern"),  # USD invoice with a bold EUR equivalent
    ("paid_stamp", "compact"),  # red PAID stamp over the totals
]
N_INVOICES = N_STANDARD + len(HARD_KINDS)


@dataclass(frozen=True)
class Scan:
    dpi: int = 150  # resolution of the final image
    skew: float = 0.0  # degrees, small scanner misalignment
    rotate: int = 0  # 90 or 270: the page was fed sideways
    noise: float = 0.06  # 0..1 blend of random speckle
    blur: float = 0.4  # Gaussian blur radius in output pixels
    jpeg_quality: int = 70
    color: bool = False  # keep colour (handwriting in blue ink, red stamps)
    fax: bool = False  # threshold to pure black and white, like a fax machine


@dataclass(frozen=True)
class Handwriting:
    text: str
    x: float  # points from the left edge
    y: float  # points from the top edge (baseline)
    size: float = 14
    angle: float = -4.0


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
    # Hard-set extras (see HARD_KINDS). `scan` renders the page as a degraded image with no
    # text layer; `totals_rows` replaces the standard subtotal/tax/total block (a str value
    # is printed verbatim); `handwriting` and `stamp` are drawn on top of a scanned page.
    scan: Scan | None = None
    totals_rows: list[tuple[str, float | str, bool]] | None = None
    handwriting: list[Handwriting] = field(default_factory=list)
    stamp: str | None = None
    account_ref: str | None = None
    print_po: bool = True


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


def make_case(i: int, rng: random.Random, layout: str | None = None) -> Case:
    layout = layout or LAYOUTS[i % len(LAYOUTS)]
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


def _tax_name(inv: InvoiceData, print_rate: bool, decimal_comma: bool) -> str:
    name = TAX_LABEL[inv.currency]
    if print_rate and inv.tax_rate is not None:
        name = f"{name} {_qty(inv.tax_rate, decimal_comma)}%"
    if inv.tax_amount == 0 and inv.currency != "USD":
        name += " (exempt / reverse charge)"
    return name


def _with_totals(case: Case, items: list[LineItem], tax_amount: float, **update) -> None:
    subtotal = round(sum(it.amount for it in items), 2)
    case.invoice = case.invoice.model_copy(
        update={
            "line_items": items,
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "total": round(subtotal + tax_amount, 2),
            **update,
        }
    )


def make_hard_case(i: int, kind: str, layout: str, rng: random.Random) -> Case:
    """A standard case made harder in one specific way. Labels still hold what is printed
    (or, for `handwritten_po`, written) on the document."""
    case = make_case(i, rng, layout=layout)
    case.tags = list(dict.fromkeys([*case.tags, "hard", kind]))
    inv = case.invoice
    note_date = inv.invoice_date + timedelta(days=rng.randint(5, 20))

    if kind == "scanned_rotated":
        case.scan = Scan(rotate=90 if i % 2 else 270, skew=round(rng.uniform(-1, 1), 2), noise=0.05)
    elif kind == "scanned_skewed":
        case.scan = Scan(skew=round(rng.choice([-1, 1]) * rng.uniform(1.5, 3.5), 2), noise=0.1, blur=0.6)
    elif kind == "low_res":
        case.scan = Scan(dpi=rng.choice([62, 70, 78]), jpeg_quality=35, noise=0.06, blur=0.4, fax=i % 3 == 0)
    elif kind == "handwritten_po":
        po = f"45000{rng.randint(10000, 99999)}" if i % 2 else f"PO-{rng.randint(10000, 99999)}"
        case.invoice = inv.model_copy(update={"po_number": po})
        case.print_po = False
        case.tags = [t for t in case.tags if t != "no_po"]
        case.expected_issues = [c for c in case.expected_issues if c != "missing_po"]
        note = f"PO {po}" if i % 2 else f"re {po} - ok to pay JB"
        case.handwriting = [Handwriting(note, x=250 if i % 2 else 60, y=38 if i % 2 else 770, size=16)]
        case.scan = Scan(skew=round(rng.uniform(-1.2, 1.2), 2), color=True)
    elif kind == "handwritten_note":
        half = _money(inv.total / 2, inv.currency, decimal_comma=True)
        case.handwriting = [
            Handwriting(f"Part paid 50% {note_date:%d/%m} - {half}", x=60, y=760, size=15, angle=3),
            Handwriting("Approved JB", x=330, y=36, size=17, angle=-6),
        ]
        case.scan = Scan(skew=round(rng.uniform(-1, 1), 2), color=True)
    elif kind == "two_column":
        case.account_ref = f"CUST-{rng.randint(10000, 99999)}"
    elif kind == "deposit_paid":
        deposit = round(inv.total * rng.choice([0.25, 0.3, 0.5]), 2)
        case.totals_rows = [
            ("Subtotal", inv.subtotal, False),
            (_tax_name(inv, case.print_tax_rate, False), inv.tax_amount, False),
            ("Invoice total", inv.total, False),
            ("Less deposit received", -deposit, False),
            ("BALANCE DUE", round(inv.total - deposit, 2), True),
        ]
    elif kind == "mixed_tax_rates":
        items = list(inv.line_items)
        while len(items) < 3:
            desc, lo, hi = rng.choice(CATALOG)
            unit = round(rng.uniform(lo, hi), 2)
            items.append(LineItem(description=desc, quantity=2, unit_price=unit, amount=round(2 * unit, 2)))
        k = len(items) // 2
        (rate_a, rate_b), parts = rng.choice([(21, 9), (19, 7), (18, 5)]), []
        for rate, group in ((rate_a, items[:k]), (rate_b, items[k:])):
            base = round(sum(it.amount for it in group), 2)
            parts.append((rate, base, round(base * rate / 100, 2)))
        _with_totals(case, items, round(sum(p[2] for p in parts), 2), tax_rate=None)
        case.print_tax_rate = False
        case.tags = [t for t in case.tags if t not in ("zero_tax", "tax_rate_not_printed")]
        inv = case.invoice
        case.totals_rows = [
            ("Net amount", inv.subtotal, False),
            *(
                (f"VAT {rate}% on {_money(base, 'EUR', decimal_comma=True, symbol=False)}", tax, False)
                for rate, base, tax in parts
            ),
            ("Total amount", inv.total, True),
        ]
    elif kind == "dual_currency":
        fx = round(rng.uniform(0.84, 0.94), 4)
        case.totals_rows = [
            ("Subtotal", inv.subtotal, False),
            (_tax_name(inv, case.print_tax_rate, False), inv.tax_amount, False),
            ("TOTAL DUE", inv.total, True),
            (f"EUR equivalent @ {fx}", _money(inv.total * fx, "EUR", decimal_comma=True), True),
        ]
    elif kind == "paid_stamp":
        case.stamp = f"PAID {note_date:%d %b %Y}".upper()
        case.scan = Scan(skew=round(rng.uniform(-1, 1), 2), color=True)
    else:
        raise ValueError(kind)
    return case


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


FONT_DIR = Path(reportlab.__file__).parent / "fonts"  # Bitstream Vera, shipped with reportlab
RENDER_DPI = 200  # pages are drawn at this resolution, then degraded to Scan.dpi
INK = (25, 25, 25)
BLUE_INK = (30, 50, 150)
STAMP_RED = (200, 30, 30)


class RasterDoc:
    """Same drawing interface as `Doc`, but paints a bitmap and saves it as a scanned PDF:
    one JPEG per page and no text layer, so the model has to read pixels."""

    def __init__(self, path: Path, pagesize, scan: Scan):
        self.path, self.scan = path, scan
        self.w, self.h = pagesize
        self.margin = 50
        self.k = RENDER_DPI / 72
        self.img = Image.new("RGB", (round(self.w * self.k), round(self.h * self.k)), "white")
        self.draw = ImageDraw.Draw(self.img)
        self.rng = random.Random(path.stem)
        self._fonts: dict[tuple[str, float], ImageFont.FreeTypeFont] = {}

    def font(self, name: str, size: float) -> ImageFont.FreeTypeFont:
        key = (name, size)
        if key not in self._fonts:
            self._fonts[key] = ImageFont.truetype(str(FONT_DIR / name), round(size * self.k))
        return self._fonts[key]

    def text(self, x: float, y: float, s: str, size: int = 10, bold: bool = False, right: bool = False):
        font = self.font("VeraBd.ttf" if bold else "Vera.ttf", size * 0.92)  # Vera runs wider than Helvetica
        self.draw.text((x * self.k, y * self.k), s, font=font, fill=INK, anchor="rs" if right else "ls")

    def line(self, y: float):
        self.draw.line(
            [(self.margin * self.k, y * self.k), ((self.w - self.margin) * self.k, y * self.k)],
            fill=INK,
            width=max(1, round(self.k * 0.6)),
        )

    def _overlay(self, layer: Image.Image, angle: float, cx: float, cy: float) -> None:
        layer = layer.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        pos = (round(cx * self.k - layer.width / 2), round(cy * self.k - layer.height / 2))
        base = self.img.convert("RGBA")
        base.alpha_composite(layer, dest=(max(0, pos[0]), max(0, pos[1])))
        self.img = base.convert("RGB")
        self.draw = ImageDraw.Draw(self.img)

    def handwrite(self, note: Handwriting) -> None:
        """Pen-on-paper imitation: slanted italic glyphs with jittered size, baseline and spacing."""
        rng = random.Random(note.text)
        px = note.size * self.k
        layer = Image.new("RGBA", (round(px * 0.75 * len(note.text) + px), round(px * 2.2)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        x = px * 0.3
        for ch in note.text:
            font = self.font("VeraBI.ttf" if rng.random() < 0.3 else "VeraIt.ttf", note.size * rng.uniform(0.9, 1.12))
            y = px * 1.4 + rng.uniform(-0.12, 0.12) * px
            draw.text((x, y), ch, font=font, fill=(*BLUE_INK, 235), anchor="ls")
            x += font.getlength(ch) * rng.uniform(0.92, 1.08)
        layer = layer.crop((0, 0, min(layer.width, round(x + px * 0.3)), layer.height))
        width_pt = layer.width / self.k
        self._overlay(layer, note.angle, note.x + width_pt / 2, note.y - note.size * 0.4)

    def stamp(self, text: str, cx: float, cy: float) -> None:
        font = self.font("VeraBd.ttf", 20)
        tw = font.getlength(text)
        pad = 10 * self.k
        layer = Image.new("RGBA", (round(tw + 2 * pad), round(30 * self.k + 2 * pad)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        draw.rectangle(
            [pad / 3, pad / 3, layer.width - pad / 3, layer.height - pad / 3],
            outline=(*STAMP_RED, 170),
            width=round(2.5 * self.k),
        )
        draw.text((layer.width / 2, layer.height / 2), text, font=font, fill=(*STAMP_RED, 170), anchor="mm")
        self._overlay(layer, 14, cx, cy)

    def save(self):
        scan, img = self.scan, self.img
        if not scan.color:
            img = img.convert("L")
        white = 255 if img.mode == "L" else (255, 255, 255)
        if scan.skew:
            img = img.rotate(scan.skew, resample=Image.Resampling.BICUBIC, fillcolor=white)
        img = img.resize((round(self.w * scan.dpi / 72), round(self.h * scan.dpi / 72)), Image.Resampling.LANCZOS)
        if scan.noise:
            noise = Image.frombytes("L", img.size, self.rng.randbytes(img.width * img.height))
            img = Image.blend(img, noise.convert(img.mode), scan.noise)
        if scan.blur:
            img = img.filter(ImageFilter.GaussianBlur(scan.blur))
        if scan.fax:
            img = img.convert("L").point(lambda v: 255 if v > 165 else 0)
        if scan.rotate:
            img = img.rotate(scan.rotate, expand=True)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=scan.jpeg_quality)
        buf.seek(0)
        page = (self.h, self.w) if scan.rotate in (90, 270) else (self.w, self.h)
        c = Canvas(str(self.path), pagesize=page, invariant=1)
        c.drawImage(ImageReader(buf), 0, 0, width=page[0], height=page[1])
        c.showPage()
        c.save()


def render(case: Case, path: Path) -> None:
    inv = case.invoice
    dc = case.layout == "european"
    date_style = {
        "classic": "long",
        "modern": "us",
        "european": "dotted",
        "compact": "iso",
        "multipage": "long",
        "two_column": "long",
    }[case.layout]
    pagesize = LETTER if case.layout == "modern" else A4
    doc = RasterDoc(path, pagesize, case.scan) if case.scan else Doc(path, pagesize)
    m, right = doc.margin, doc.w - doc.margin
    rng = random.Random(case.case_id)
    po_label = rng.choice(PO_LABELS)

    def money(v: float, symbol: bool = True) -> str:
        return _money(v, inv.currency, dc, symbol)

    if case.layout == "two_column":
        return render_two_column(case, doc, money, date_style, po_label)

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
    if inv.po_number and case.print_po:
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
    totals_y = y
    rows = case.totals_rows or [
        ("Subtotal" if case.layout != "european" else "Net amount", inv.subtotal, False),
        (_tax_name(inv, case.print_tax_rate, dc), inv.tax_amount, False),
        ("TOTAL DUE" if case.layout != "european" else "Total amount", inv.total, True),
    ]
    for label, value, bold in rows:
        doc.text(right - 120, y, label, 10, bold=bold, right=True)
        doc.text(right, y, _fmt_total(value, money), 10, bold=bold, right=True)
        y += 15

    # Footer
    y += 25
    doc.text(m, y, f"All amounts in {inv.currency}.", 8)
    if inv.due_date is None:
        doc.text(m, y + 12, "Payment terms: as per agreement.", 8)
    doc.text(m, doc.h - 70 - (doc.h - 842 if doc.h != 842 else 0), "Thank you for your business.", 8)
    if page > 1:
        doc.text(right, doc.h - 40, f"Page {page} of {page}", 8, right=True)
    if case.handwriting or case.stamp:
        assert isinstance(doc, RasterDoc), f"{case.case_id}: annotations need a scanned page"
        for note in case.handwriting:
            doc.handwrite(note)
        if case.stamp:
            doc.stamp(case.stamp, right - 90, totals_y + 8)
    doc.save()


def _fmt_total(value: float | str, money) -> str:
    if isinstance(value, str):
        return value
    return f"-{money(-value)}" if value < 0 else money(value)


def render_two_column(case: Case, doc: Doc | RasterDoc, money, date_style: str, po_label: str) -> None:
    """Main column holds the line items (with SKUs and wrapped descriptions); a right-hand
    sidebar holds invoice details, a customer account number (a distractor for the invoice
    and PO numbers), bill-to, remittance details and the totals. Reading order in the text
    layer interleaves the two columns."""
    inv = case.invoice
    m, right = doc.margin, doc.w - doc.margin
    side = right - 150
    rng = random.Random(case.case_id + "two_column")

    doc.text(m, 60, inv.vendor_name, 15, bold=True)
    y = 78
    for addr in case.vendor_address:
        doc.text(m, y, addr, 9)
        y += 12
    if inv.vendor_tax_id:
        doc.text(m, y, f"{'EIN' if inv.currency == 'USD' else 'VAT Reg No'}: {inv.vendor_tax_id}", 9)

    doc.text(side, 60, "INVOICE", 16, bold=True)
    details = [("Invoice number", inv.invoice_number), ("Invoice date", _date(inv.invoice_date, date_style))]
    if inv.due_date:
        details.append(("Payment due", _date(inv.due_date, date_style)))
    if inv.po_number and case.print_po:
        details.append((po_label, inv.po_number))
    details.append(("Customer account", case.account_ref or ""))
    sy = 85
    for label, value in details:
        doc.text(side, sy, label.upper(), 7, bold=True)
        doc.text(side, sy + 12, value, 10)
        sy += 28
    sy += 8
    doc.text(side, sy, "BILL TO", 7, bold=True)
    doc.text(side, sy + 12, case.buyer, 8)
    doc.text(side, sy + 23, f"Tax ID {case.buyer_tax_id}", 8)
    sy += 50

    # Items table in the main column; long descriptions wrap onto a second line.
    cols = [m, m + 48, side - 120, side - 70, side - 20]
    y = 150
    doc.text(cols[0], y, "SKU", 8, bold=True)
    doc.text(cols[1], y, "Description", 8, bold=True)
    for x, hdr in zip(cols[2:], ["Qty", "Price", "Amount"], strict=True):
        doc.text(x, y, hdr, 8, bold=True, right=True)
    y += 16
    for item in inv.line_items:
        sku = f"{rng.choice('ABCDKMRT')}{rng.choice('ABCDKMRT')}-{rng.randint(100, 9999)}"
        unit = "hrs" if "hour" in item.description else "ea"
        doc.text(cols[0], y, sku, 8)
        doc.text(cols[2], y, f"{_qty(item.quantity)} {unit}", 8, right=True)
        doc.text(cols[3], y, money(item.unit_price, symbol=False), 8, right=True)
        doc.text(cols[4], y, money(item.amount, symbol=False), 8, right=True)
        for n, part in enumerate(textwrap.wrap(item.description, 22)):
            doc.text(cols[1], y + n * 10, part, 8)
        y += 10 * max(1, len(textwrap.wrap(item.description, 22))) + 8

    # Totals and remittance in the sidebar.
    sy = max(sy, 300)
    rows = case.totals_rows or [
        ("Subtotal", inv.subtotal, False),
        (_tax_name(inv, case.print_tax_rate, False), inv.tax_amount, False),
        ("Total due", inv.total, True),
    ]
    for label, value, bold in rows:
        doc.text(side, sy, label, 8, bold=bold)
        doc.text(right, sy, _fmt_total(value, money), 9, bold=bold, right=True)
        sy += 14
    sy += 20
    doc.text(side, sy, "REMIT TO", 7, bold=True)
    doc.text(side, sy + 12, f"IBAN XX{rng.randint(10, 99)} {rng.randint(1000, 9999)} {rng.randint(1000, 9999)}", 8)
    doc.text(side, sy + 23, f"Quote ref {inv.invoice_number}", 8)

    doc.text(m, max(y, sy) + 50, f"All amounts in {inv.currency}.", 8)
    doc.save()


def label_for(case: Case) -> dict:
    return {
        "case_id": case.case_id,
        "layout": case.layout,
        "tags": case.tags,
        "expected_issues": sorted(case.expected_issues),
        "invoice": json.loads(case.invoice.model_dump_json()),
    }


def build_cases(seed: int = SEED) -> list[Case]:
    rng = random.Random(seed)
    cases = [make_case(i, rng) for i in range(N_STANDARD)]
    hard_rng = random.Random(seed + 1)  # separate stream: the standard 50 stay unchanged
    cases += [make_hard_case(N_STANDARD + j, kind, layout, hard_rng) for j, (kind, layout) in enumerate(HARD_KINDS)]
    return cases


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
