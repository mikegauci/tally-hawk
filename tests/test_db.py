"""The Postgres store against a real database (skipped without TALLYHAWK_TEST_DATABASE_URL)."""

import json
from pathlib import Path

import pytest

from tallyhawk.db import PostgresStore, migrate, seed_from_dir
from tallyhawk.procurement import InMemoryStore
from tallyhawk.schema import InvoiceData
from tallyhawk.workflow import MatchingWorkflow

DATA = Path(__file__).parent.parent / "evals" / "data"
LABELS = json.loads((DATA / "match_labels.json").read_text())


def gold(case_id: str) -> InvoiceData:
    return InvoiceData.model_validate(json.loads((DATA / "labels" / f"{case_id}.json").read_text())["invoice"])


@pytest.fixture(scope="module")
def stores(pg_pool):
    return PostgresStore(pg_pool), InMemoryStore.from_dir(DATA / "procurement")


def test_migrate_and_seed_are_rerunnable(pg_pool):
    with pg_pool.connection() as conn:
        assert migrate(conn) == []
        counts = seed_from_dir(conn, DATA / "procurement")
        assert conn.execute("select count(*) as n from vendors").fetchone()["n"] == counts["vendors"]
        assert conn.execute("select count(*) as n from posted_invoices").fetchone()["n"] == counts["posted_invoices"]


@pytest.mark.parametrize("case_id", [label["case_id"] for label in LABELS])
def test_postgres_store_matches_like_the_in_memory_store(stores, case_id):
    """Every matching eval case gets the same outcome (decision, issues, lines, trace) on both stores."""
    pg, mem = stores
    invoice = gold(case_id)
    on_pg, in_mem = MatchingWorkflow(pg).run(invoice), MatchingWorkflow(mem).run(invoice)
    assert on_pg.model_dump(exclude={"steps"}) == in_mem.model_dump(exclude={"steps"})
    # Step timings differ run to run; what each step did must not.
    assert [(s.name, s.summary) for s in on_pg.steps] == [(s.name, s.summary) for s in in_mem.steps]


def test_store_lookups_agree(stores):
    pg, mem = stores
    for label in LABELS:
        invoice = gold(label["case_id"])
        for name in (invoice.vendor_name, invoice.vendor_name.upper()):
            assert pg.search_vendors(name, invoice.vendor_tax_id) == mem.search_vendors(name, invoice.vendor_tax_id)
            assert pg.search_vendors(name) == mem.search_vendors(name)
        if invoice.po_number:
            typo = invoice.po_number[:-1] + "9"
            assert pg.similar_po_numbers(typo) == mem.similar_po_numbers(typo)
            assert pg.get_purchase_order(invoice.po_number.lower()) == mem.get_purchase_order(invoice.po_number)
    for vendor_id in sorted(mem.vendors)[:10]:
        for closed in (False, True):
            assert sorted(pg.purchase_orders_for_vendor(vendor_id, closed), key=lambda p: p.po_number) == sorted(
                mem.purchase_orders_for_vendor(vendor_id, closed), key=lambda p: p.po_number
            )
