"""Demo load uses the invoice pipeline without OpenAI (fake extractor)."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_api import FakeExtractor

from tallyhawk.db import PostgresStore, seed_from_dir
from tallyhawk.demo import load_cases, restore_snapshot
from tallyhawk.service import InvoiceService
from tallyhawk.storage import LocalFileStore
from tallyhawk.workflow import MatchingWorkflow

DATA = Path(__file__).parent.parent / "evals" / "data"


@pytest.fixture
def demo_service(pg_pool, tmp_path):
    with pg_pool.connection() as conn:
        conn.execute("truncate invoices cascade")
    extractor = FakeExtractor()
    service = InvoiceService(
        pg_pool,
        LocalFileStore(tmp_path),
        MatchingWorkflow(PostgresStore(pg_pool)),
        extractor,
    )
    return service


def test_demo_load_curated_cases(demo_service, monkeypatch):
    original = Path.read_bytes

    def fake_read_bytes(self: Path) -> bytes:
        if self.suffix == ".pdf" and self.stem.startswith("inv_"):
            return f"case:{self.stem}".encode()
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)

    results = load_cases(demo_service, ["inv_001", "inv_003"], invoices_dir=DATA / "invoices")
    assert len(results) == 2
    by_case = {r.case_id: r for r in results}

    assert by_case["inv_001"].status == "approved"
    assert by_case["inv_001"].decision == "approve"

    assert by_case["inv_003"].status == "awaiting_review"
    assert by_case["inv_003"].decision == "vendor_query"

    detail = demo_service.get(uuid.UUID(by_case["inv_001"].invoice_id))
    assert detail.extraction is not None
    assert detail.extraction.result.model == "fake"


SNAPSHOT = Path(__file__).parent.parent / "demo" / "snapshot.json"


def test_committed_snapshot_matches_the_eval_pdfs():
    """`demo reset` re-uploads these files, so they must be the ones the snapshot was made from."""
    snapshot = json.loads(SNAPSHOT.read_text())
    assert snapshot["invoices"], "demo/snapshot.json has no invoices"
    for row in snapshot["invoices"]:
        data = (DATA / "invoices" / row["filename"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["sha256"], row["filename"]


def test_reset_removes_visitor_work_and_restores_the_demo(pg_pool, tmp_path):
    with pg_pool.connection() as conn:
        # Other tests truncate invoices with cascade, which also empties posted_invoices.
        conn.execute("delete from invoices")
        seed_from_dir(conn, DATA / "procurement")
    files = LocalFileStore(tmp_path / "storage")
    snapshot = json.loads(SNAPSHOT.read_text())
    restore_snapshot(pg_pool, files, snapshot, DATA / "invoices")

    # A visitor uploads an invoice, approves a demo one and uses up some of the cap.
    service = InvoiceService(pg_pool, files, MatchingWorkflow(PostgresStore(pg_pool)), FakeExtractor())
    visitor = service.upload("mine.pdf", "application/pdf", b"case:inv_004")
    queued = next(r for r in snapshot["invoices"] if r["status"] == "awaiting_review")
    with pg_pool.connection() as conn:
        conn.execute("update invoices set status = 'approved' where id = %s", (queued["id"],))
        conn.execute("insert into demo_usage values ('visit', current_date, 7)")

    counts = restore_snapshot(pg_pool, files, snapshot, DATA / "invoices")
    assert counts == {"invoices": len(snapshot["invoices"]), "files_removed": 1}
    with pg_pool.connection() as conn:
        rows = {str(r["id"]): r for r in conn.execute("select id, status, uploaded_at from invoices")}
        assert set(rows) == {r["id"] for r in snapshot["invoices"]}
        assert rows[queued["id"]]["status"] == "awaiting_review"
        assert conn.execute("select count(*) as n from demo_usage").fetchone()["n"] == 0
        assert conn.execute("select count(*) as n from posted_invoices where invoice_id is null").fetchone()["n"] > 0
        newest = max(r["uploaded_at"] for r in rows.values())
        assert abs((datetime.now(UTC) - newest).total_seconds()) < 60  # looks freshly loaded
    assert not (tmp_path / "storage" / str(visitor.id) / "mine.pdf").exists()
    assert service.get(uuid.UUID(queued["id"])).match is not None  # full detail restored
    # Identity sequences continue after the restored ids.
    again = service.upload("next.pdf", "application/pdf", b"case:inv_001")
    service.process(again.id)
