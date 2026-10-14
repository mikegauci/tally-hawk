"""Demo load uses the invoice pipeline without OpenAI (fake extractor)."""

import uuid
from pathlib import Path

import pytest
from test_api import FakeExtractor

from tallyhawk.db import PostgresStore
from tallyhawk.demo import load_cases
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
