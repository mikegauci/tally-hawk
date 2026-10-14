"""Postgres (Supabase) persistence: migrations, seeding, and the procurement store.

`PostgresStore` implements the same `ProcurementStore` interface as `InMemoryStore`, so the
matching workflow and the PO-finding agent run unchanged on top of it:

    pool = connect(os.environ["DATABASE_URL"])
    workflow = MatchingWorkflow(PostgresStore(pool))

The schema lives in `supabase/migrations/` (plain SQL, so the Supabase CLI can apply it
too). `migrate` applies any file not yet recorded in `tallyhawk_schema_migrations`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from tallyhawk.procurement import (
    GoodsReceipt,
    InMemoryStore,
    POLine,
    PostedInvoice,
    PurchaseOrder,
    ReceiptLine,
    Vendor,
    VendorCandidate,
    rank_similar_refs,
    rank_vendors,
)

MIGRATIONS_DIR = Path(os.environ.get("TALLYHAWK_MIGRATIONS_DIR", Path(__file__).parents[2] / "supabase" / "migrations"))


def connect(database_url: str, *, min_size: int = 1, max_size: int = 5) -> ConnectionPool:
    """A connection pool. Prepared statements are off so Supabase's transaction pooler
    (port 6543) works as well as a direct connection."""
    return ConnectionPool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        kwargs={"prepare_threshold": None, "row_factory": dict_row},
        open=True,
    )


# --- migrations -----------------------------------------------------------------------


def migrate(conn: Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in filename order; returns the names applied."""
    conn.execute(
        "create table if not exists public.tallyhawk_schema_migrations "
        "(name text primary key, applied_at timestamptz not null default now())"
    )
    conn.execute("alter table public.tallyhawk_schema_migrations enable row level security")
    done = {row["name"] for row in conn.execute("select name from public.tallyhawk_schema_migrations")}
    applied = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute("insert into public.tallyhawk_schema_migrations (name) values (%s)", (path.name,))
        applied.append(path.name)
    return applied


# --- seeding --------------------------------------------------------------------------


def upsert_vendors(conn: Connection, vendors: Iterable[Vendor]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into vendors (vendor_id, name, tax_id, email, address)
            values (%s, %s, %s, %s, %s)
            on conflict (vendor_id) do update set
                name = excluded.name, tax_id = excluded.tax_id, email = excluded.email, address = excluded.address
            """,
            [(v.vendor_id, v.name, v.tax_id, v.email, v.address) for v in vendors],
        )


def upsert_purchase_orders(conn: Connection, purchase_orders: Iterable[PurchaseOrder]) -> None:
    with conn.cursor() as cur:
        for po in purchase_orders:
            cur.execute(
                """
                insert into purchase_orders (po_number, vendor_id, order_date, currency, status)
                values (%s, %s, %s, %s, %s)
                on conflict (po_number) do update set
                    vendor_id = excluded.vendor_id, order_date = excluded.order_date,
                    currency = excluded.currency, status = excluded.status
                """,
                (po.po_number, po.vendor_id, po.order_date, po.currency, po.status),
            )
            cur.execute("delete from po_lines where po_number = %s", (po.po_number,))
            cur.executemany(
                "insert into po_lines (po_number, line_no, description, quantity, unit_price) "
                "values (%s, %s, %s, %s, %s)",
                [(po.po_number, li.line_no, li.description, li.quantity, li.unit_price) for li in po.lines],
            )


def upsert_goods_receipts(conn: Connection, receipts: Iterable[GoodsReceipt]) -> None:
    with conn.cursor() as cur:
        for r in receipts:
            cur.execute(
                """
                insert into goods_receipts (receipt_number, po_number, received_date) values (%s, %s, %s)
                on conflict (receipt_number) do update set
                    po_number = excluded.po_number, received_date = excluded.received_date
                """,
                (r.receipt_number, r.po_number, r.received_date),
            )
            cur.execute("delete from goods_receipt_lines where receipt_number = %s", (r.receipt_number,))
            cur.executemany(
                "insert into goods_receipt_lines (receipt_number, po_line, quantity) values (%s, %s, %s)",
                [(r.receipt_number, li.po_line, li.quantity) for li in r.lines],
            )


def seed_from_dir(conn: Connection, path: str | Path) -> dict[str, int]:
    """Load the seed JSON (vendors, POs, goods receipts, posted invoices) into the database.

    Re-running it is safe: procurement rows are upserted, and seeded posted invoices
    (those not created by TallyHawk itself) are replaced.
    """
    data = InMemoryStore.from_dir(path)
    with conn.transaction():
        upsert_vendors(conn, data.vendors.values())
        upsert_purchase_orders(conn, data.purchase_orders.values())
        upsert_goods_receipts(conn, data.receipts)
        conn.execute("delete from posted_invoices where invoice_id is null")
        with conn.cursor() as cur:
            cur.executemany(
                "insert into posted_invoices (vendor_id, invoice_number, invoice_date, total, status) "
                "values (%s, %s, %s, %s, %s)",
                [(i.vendor_id, i.invoice_number, i.invoice_date, i.total, i.status) for i in data.invoices],
            )
    return {
        "vendors": len(data.vendors),
        "purchase_orders": len(data.purchase_orders),
        "goods_receipts": len(data.receipts),
        "posted_invoices": len(data.invoices),
    }


# --- the store ------------------------------------------------------------------------


def _vendor(row: dict) -> Vendor:
    return Vendor(
        vendor_id=row["vendor_id"], name=row["name"], tax_id=row["tax_id"], email=row["email"], address=row["address"]
    )


class PostgresStore:
    """`ProcurementStore` backed by Postgres. Matching rules stay in Python; SQL only fetches."""

    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def _purchase_orders(self, where: str, params: tuple) -> list[PurchaseOrder]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                f"""
                select po.po_number, po.vendor_id, po.order_date, po.currency, po.status,
                       coalesce(json_agg(json_build_object(
                           'line_no', l.line_no, 'description', l.description,
                           'quantity', l.quantity, 'unit_price', l.unit_price
                       ) order by l.line_no) filter (where l.line_no is not null), '[]') as lines
                from purchase_orders po
                left join po_lines l on l.po_number = po.po_number
                where {where}
                group by po.po_number
                order by po.po_number
                """,
                params,
            ).fetchall()
        return [
            PurchaseOrder(
                po_number=r["po_number"],
                vendor_id=r["vendor_id"],
                order_date=r["order_date"],
                currency=r["currency"].strip(),
                status=r["status"],
                lines=[POLine.model_validate(line) for line in r["lines"]],
            )
            for r in rows
        ]

    def get_vendor(self, vendor_id: str) -> Vendor | None:
        with self.pool.connection() as conn:
            row = conn.execute("select * from vendors where vendor_id = %s", (vendor_id,)).fetchone()
        return _vendor(row) if row else None

    def search_vendors(self, name: str, tax_id: str | None = None, limit: int = 5) -> list[VendorCandidate]:
        """Ranked exactly as `InMemoryStore` ranks them, so evals give the same answer on both.

        Every vendor is scored: an SMB's supplier list is hundreds of rows, not millions. A
        SQL prefilter (pg_trgm) was tried and dropped candidates the Python scorer keeps.
        """
        with self.pool.connection() as conn:
            rows = conn.execute("select * from vendors order by vendor_id").fetchall()
        return rank_vendors([_vendor(r) for r in rows], name, tax_id, limit)

    def get_purchase_order(self, po_number: str) -> PurchaseOrder | None:
        found = self._purchase_orders("po.po_number_key = public.normalize_ref(%s)", (po_number,))
        return found[0] if found else None

    def similar_po_numbers(self, po_number: str, limit: int = 3) -> list[str]:
        # PO numbers are short codes where one wrong digit matters, so score them all in Python.
        with self.pool.connection() as conn:
            numbers = [r["po_number"] for r in conn.execute("select po_number from purchase_orders").fetchall()]
        return rank_similar_refs(po_number, numbers, limit)

    def purchase_orders_for_vendor(self, vendor_id: str, include_closed: bool = False) -> list[PurchaseOrder]:
        if include_closed:
            return self._purchase_orders("po.vendor_id = %s", (vendor_id,))
        return self._purchase_orders("po.vendor_id = %s and po.status = 'open'", (vendor_id,))

    def goods_receipts(self, po_number: str) -> list[GoodsReceipt]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """
                select r.receipt_number, r.po_number, r.received_date,
                       json_agg(json_build_object('po_line', l.po_line, 'quantity', l.quantity)
                                order by l.po_line) filter (where l.po_line is not null) as lines
                from goods_receipts r
                join purchase_orders po on po.po_number = r.po_number
                left join goods_receipt_lines l on l.receipt_number = r.receipt_number
                where po.po_number_key = public.normalize_ref(%s)
                group by r.receipt_number
                order by r.received_date, r.receipt_number
                """,
                (po_number,),
            ).fetchall()
        return [
            GoodsReceipt(
                receipt_number=r["receipt_number"],
                po_number=r["po_number"],
                received_date=r["received_date"],
                lines=[ReceiptLine.model_validate(line) for line in r["lines"] or []],
            )
            for r in rows
        ]

    def posted_invoices(self, vendor_id: str, invoice_number: str) -> list[PostedInvoice]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """
                select vendor_id, invoice_number, invoice_date, total, status from posted_invoices
                where vendor_id = %s and invoice_number_key = public.normalize_ref(%s)
                order by invoice_date, id
                """,
                (vendor_id, invoice_number),
            ).fetchall()
        return [PostedInvoice.model_validate(r) for r in rows]
