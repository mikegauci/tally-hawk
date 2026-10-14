"""Generate the procurement seed data and matching labels for the 50 eval invoices.

    uv run python -m evals.generate_matching

The invoices from step 1 stay exactly as they are. Each one is given a *scenario* that is
built on the buyer's side instead: the PO, goods receipts and vendor record are seeded so
that matching that invoice should end in a known decision. For example, `price_increase`
seeds a PO with a lower agreed price than the invoice charges, and `short_delivery` seeds
a goods receipt with fewer units than were billed.

Writes `evals/data/procurement/*.json` (the seed a store loads) and
`evals/data/match_labels.json` (expected decision, supplier, PO and issue codes per invoice).
Deterministic, so `tests/test_matching_dataset.py` can check the committed files.
"""

from __future__ import annotations

import json
import random
import re
from datetime import timedelta
from pathlib import Path

from evals.generate import (
    CATALOG,
    N_STANDARD,
    PO_STYLES,
    VENDOR_FIRST,
    VENDOR_SECOND,
    VENDOR_SUFFIX,
    Case,
    build_cases,
)
from tallyhawk.procurement import (
    GoodsReceipt,
    POLine,
    PostedInvoice,
    PurchaseOrder,
    ReceiptLine,
    Vendor,
    vendor_name_similarity,
)

SEED = 2042
DATA_DIR = Path(__file__).parent / "data"
SEED_DIR = DATA_DIR / "procurement"
LABELS_PATH = DATA_DIR / "match_labels.json"

# Scenario -> (expected decision, expected issue codes, plain-English description)
SCENARIOS: dict[str, tuple[str, list[str], str]] = {
    "clean": ("approve", [], "PO, receipt and invoice agree"),
    "supplier_error": (
        "vendor_query",
        ["invoice_arithmetic_error"],
        "Matches the PO, but the supplier's own arithmetic is wrong",
    ),
    "price_within_tolerance": ("approve", [], "One price is a fraction of a percent above the PO"),
    "price_increase": ("vendor_query", ["price_variance"], "One line is billed 5 to 12% above the PO price"),
    "short_delivery": ("vendor_query", ["qty_exceeds_received"], "Fewer units arrived than were billed"),
    "split_receipts": ("approve", [], "Goods arrived in two deliveries that together cover the invoice"),
    "not_received": ("review", ["no_goods_receipt"], "No goods receipt has been recorded yet"),
    "extra_line": ("vendor_query", ["line_not_on_po"], "The invoice bills a line that isn't on the PO"),
    "duplicate": ("review", ["duplicate_invoice"], "The same invoice was already paid"),
    "vendor_mismatch": ("review", ["vendor_mismatch"], "The quoted PO was raised with a different supplier"),
    "unknown_vendor": ("review", ["no_po_found", "unknown_vendor"], "Supplier and PO aren't on file"),
    "currency_mismatch": ("review", ["currency_mismatch"], "The PO is in a different currency"),
    "po_typo": ("review", ["po_inferred"], "The quoted PO number has a typo; the real PO is on file"),
    "po_not_printed": ("review", ["po_inferred"], "No PO quoted, but the supplier has a matching open PO"),
    "no_po_exists": ("vendor_query", ["no_po_found"], "No PO quoted and none of the supplier's POs match"),
}

# Chosen by hand so each scenario's preconditions hold (e.g. extra_line needs 2+ lines,
# the no-PO scenarios need invoices that print no PO). Unlisted invoices are `clean`.
CASE_SCENARIOS: dict[str, str] = {
    "inv_002": "po_not_printed",
    "inv_012": "po_not_printed",
    "inv_028": "po_not_printed",
    "inv_035": "po_not_printed",
    "inv_043": "po_not_printed",
    "inv_050": "po_not_printed",
    "inv_024": "no_po_exists",
    "inv_037": "no_po_exists",
    "inv_038": "no_po_exists",
    "inv_045": "no_po_exists",
    "inv_003": "price_increase",
    "inv_018": "price_increase",
    "inv_030": "price_increase",
    "inv_041": "price_increase",
    "inv_006": "price_within_tolerance",
    "inv_027": "price_within_tolerance",
    "inv_044": "price_within_tolerance",
    "inv_007": "short_delivery",
    "inv_015": "short_delivery",
    "inv_031": "short_delivery",
    "inv_048": "short_delivery",
    "inv_004": "split_receipts",
    "inv_013": "split_receipts",
    "inv_040": "split_receipts",
    "inv_011": "not_received",
    "inv_026": "not_received",
    "inv_017": "extra_line",
    "inv_029": "extra_line",
    "inv_049": "extra_line",
    "inv_019": "duplicate",
    "inv_039": "duplicate",
    "inv_022": "vendor_mismatch",
    "inv_032": "vendor_mismatch",
    "inv_042": "unknown_vendor",
    "inv_010": "po_typo",
    "inv_021": "po_typo",
    "inv_036": "po_typo",
    "inv_046": "currency_mismatch",
}

SUFFIX_VARIANTS = {
    "Ltd": "Limited",
    "Inc.": "Incorporated",
    "Corp.": "Corporation",
    "LLC": "L.L.C.",
    "B.V.": "BV",
    "GmbH": "GMBH",
    "S.r.l.": "SRL",
    "plc": "PLC",
    "LLP": "L.L.P.",
}
ABBREVIATIONS = {
    "Building": "Bldg",
    "Engineering": "Eng.",
    "Services": "Svcs",
    "Solutions": "Solns",
    "Supplies": "Supply",
    "Materials": "Mat.",
}


def name_variant(name: str, rng: random.Random) -> str:
    """How the buyer's system might spell the supplier's name differently from the invoice."""
    kind = rng.choice(["upper", "suffix", "abbrev", "and"])
    if kind == "and" and "&" in name:
        return name.replace("&", "and")
    if kind == "abbrev":
        for word, short in ABBREVIATIONS.items():
            if word in name.split():
                return name.replace(word, short)
    if kind in ("suffix", "abbrev", "and"):
        for suffix, longer in SUFFIX_VARIANTS.items():
            if name.endswith(" " + suffix):
                return name[: -len(suffix)] + longer
    return name.upper()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def typo(po_number: str) -> str:
    """Change the last digit, like a supplier mistyping the PO."""
    i = max(i for i, ch in enumerate(po_number) if ch.isdigit())
    return po_number[:i] + str((int(po_number[i]) + 1) % 10) + po_number[i + 1 :]


class Builder:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.vendors: list[Vendor] = []
        self.pos: list[PurchaseOrder] = []
        self.receipts: list[GoodsReceipt] = []
        self.posted: list[PostedInvoice] = []
        self.po_numbers: set[str] = set()

    def vendor(self, name: str, tax_id: str | None, currency: str, address: str) -> Vendor:
        vendor = Vendor(
            vendor_id=f"V{len(self.vendors) + 1:03d}",
            name=name,
            tax_id=tax_id or self.tax_id(currency),
            email=f"accounts@{slug(name)}.example",
            address=address,
        )
        self.vendors.append(vendor)
        return vendor

    def tax_id(self, currency: str) -> str:
        r = self.rng
        if currency == "GBP":
            return f"GB{r.randint(100, 999)} {r.randint(1000, 9999)} {r.randint(10, 99)}"
        if currency == "USD":
            return f"{r.randint(10, 99)}-{r.randint(1_000_000, 9_999_999)}"
        return f"MT{r.randint(10_000_000, 99_999_999)}"

    def new_po_number(self) -> str:
        while True:
            number = self.rng.choice(PO_STYLES)(self.rng)
            if number not in self.po_numbers:
                self.po_numbers.add(number)
                return number

    def po(self, number: str, vendor: Vendor, case: Case, lines: list[POLine], status: str = "open") -> PurchaseOrder:
        po = PurchaseOrder(
            po_number=number,
            vendor_id=vendor.vendor_id,
            order_date=case.invoice.invoice_date - timedelta(days=self.rng.randint(10, 40)),
            currency=case.invoice.currency,
            status=status,
            lines=lines,
        )
        self.po_numbers.add(number)
        self.pos.append(po)
        return po

    def receipt(self, po: PurchaseOrder, case: Case, quantities: dict[int, float]) -> None:
        self.receipts.append(
            GoodsReceipt(
                receipt_number=f"GRN-{len(self.receipts) + 1:05d}",
                po_number=po.po_number,
                received_date=case.invoice.invoice_date - timedelta(days=self.rng.randint(0, 9)),
                lines=[ReceiptLine(po_line=no, quantity=q) for no, q in quantities.items() if q > 0],
            )
        )

    def distractor_po(self, vendor: Vendor, case: Case, status: str = "open") -> None:
        """Another PO for the same supplier, for different goods."""
        items = self.rng.sample(CATALOG, self.rng.randint(1, 5))
        lines = [
            POLine(
                line_no=n,
                description=desc,
                quantity=self.rng.choice([1, 2, 5, 10, 20]),
                unit_price=round(self.rng.uniform(lo, hi), 2),
            )
            for n, (desc, lo, hi) in enumerate(items, start=1)
        ]
        self.po(self.new_po_number(), vendor, case, lines, status)


def build(cases: list[Case] | None = None, seed: int = SEED) -> tuple[dict[str, list], list[dict]]:
    rng = random.Random(seed)
    b = Builder(rng)
    cases = cases or build_cases()[:N_STANDARD]  # the extraction hard set has no matching scenarios
    invoice_names = {c.invoice.vendor_name for c in cases}

    # Supplier records. Two step-1 invoices share a name with different tax IDs, so a vendor
    # is keyed by (name, tax ID): two legal entities with the same trading name.
    by_case: dict[str, Vendor] = {}
    seen: dict[tuple[str, str | None], Vendor] = {}
    for case in cases:
        inv = case.invoice
        if CASE_SCENARIOS.get(case.case_id) == "unknown_vendor":
            continue
        key = (inv.vendor_name, inv.vendor_tax_id)
        if key not in seen:
            name = name_variant(inv.vendor_name, rng) if rng.random() < 0.4 else inv.vendor_name
            seen[key] = b.vendor(name, inv.vendor_tax_id, inv.currency, ", ".join(case.vendor_address))
        by_case[case.case_id] = seen[key]

    # Look-alike suppliers that should never be matched (same first word, different business).
    distractors: list[Vendor] = []
    for first in VENDOR_FIRST:
        for second in rng.sample(VENDOR_SECOND, 2):
            currency = rng.choice(list(VENDOR_SUFFIX))
            name = f"{first} {second} {rng.choice(VENDOR_SUFFIX[currency])}"
            if max(vendor_name_similarity(name, n) for n in invoice_names) < 0.8:
                distractors.append(b.vendor(name, None, currency, "Distractor Road 1"))
                break

    labels = []
    for case in cases:
        inv = case.invoice
        scenario = CASE_SCENARIOS.get(case.case_id, "clean")
        if scenario == "clean" and "supplier_error" in case.tags:
            scenario = "supplier_error"
        vendor = by_case.get(case.case_id)
        lines = [
            POLine(line_no=n, description=item.description, quantity=item.quantity, unit_price=item.unit_price)
            for n, item in enumerate(inv.line_items, start=1)
        ]
        full = {line.line_no: line.quantity for line in lines}
        po_number: str | None = inv.po_number

        if scenario == "unknown_vendor":
            labels.append(_label(case, scenario, None, None))
            continue
        if scenario in ("po_not_printed", "no_po_exists", "po_typo"):
            for _ in range(rng.randint(1, 2)):
                b.distractor_po(vendor, case)
        if scenario == "no_po_exists":
            labels.append(_label(case, scenario, vendor.vendor_id, None))
            continue
        if scenario == "po_not_printed":
            po_number = b.new_po_number()
        elif scenario == "po_typo":
            po_number = typo(inv.po_number)
            assert po_number not in b.po_numbers
        elif scenario == "price_increase":
            i = rng.randrange(len(lines))
            lines[i].unit_price = round(lines[i].unit_price / rng.uniform(1.05, 1.12), 2)
        elif scenario == "price_within_tolerance":
            i = max(range(len(lines)), key=lambda n: lines[n].unit_price)
            lines[i].unit_price = round(lines[i].unit_price / 1.004, 2)
        elif scenario == "extra_line":
            lines.pop()
            full.pop(len(inv.line_items))

        po_vendor = rng.choice(distractors) if scenario == "vendor_mismatch" else vendor
        po = b.po(po_number, po_vendor, case, lines)
        if scenario == "currency_mismatch":
            po.currency = "GBP" if inv.currency != "GBP" else "EUR"

        if scenario == "short_delivery":
            no = max(full, key=lambda n: full[n])
            q = full[no]
            full[no] = q - max(1, round(q * 0.2)) if q >= 2 else 0
            b.receipt(po, case, full)
        elif scenario == "split_receipts":
            first = {no: (round(q / 2) if q >= 2 else q) for no, q in full.items()}
            b.receipt(po, case, first)
            b.receipt(po, case, {no: q - first[no] for no, q in full.items()})
        elif scenario != "not_received":
            b.receipt(po, case, full)

        if scenario == "duplicate":
            b.posted.append(
                PostedInvoice(
                    vendor_id=vendor.vendor_id,
                    invoice_number=inv.invoice_number,
                    invoice_date=inv.invoice_date,
                    total=inv.total,
                    status="paid",
                )
            )
        labels.append(_label(case, scenario, vendor.vendor_id, po.po_number))

    # Background noise: older closed POs and earlier paid invoices for some suppliers.
    for case in rng.sample(cases, 15):
        vendor = by_case.get(case.case_id)
        if vendor is None:
            continue
        b.distractor_po(vendor, case, status="closed")
        b.posted.append(
            PostedInvoice(
                vendor_id=vendor.vendor_id,
                invoice_number=f"{case.invoice.invoice_number}-OLD",
                invoice_date=case.invoice.invoice_date - timedelta(days=rng.randint(30, 120)),
                total=round(rng.uniform(100, 5000), 2),
                status="paid",
            )
        )

    seed_data = {
        "vendors": [v.model_dump(mode="json") for v in b.vendors],
        "purchase_orders": [p.model_dump(mode="json") for p in b.pos],
        "goods_receipts": [r.model_dump(mode="json") for r in b.receipts],
        "posted_invoices": [p.model_dump(mode="json") for p in b.posted],
    }
    return seed_data, labels


def _label(case: Case, scenario: str, vendor_id: str | None, po_number: str | None) -> dict:
    decision, issues, _ = SCENARIOS[scenario]
    return {
        "case_id": case.case_id,
        "scenario": scenario,
        "expected_decision": decision,
        "expected_vendor_id": vendor_id,
        "expected_po_number": po_number,
        "expected_issues": sorted(issues),
    }


def main() -> None:
    seed_data, labels = build()
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in seed_data.items():
        (SEED_DIR / f"{name}.json").write_text(json.dumps(rows, indent=2) + "\n")
    LABELS_PATH.write_text(json.dumps(labels, indent=2) + "\n")
    counts = {name: len(rows) for name, rows in seed_data.items()}
    print(f"Wrote {counts} to {SEED_DIR} and {len(labels)} labels to {LABELS_PATH}")


if __name__ == "__main__":
    main()
