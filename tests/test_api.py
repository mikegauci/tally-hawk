"""The HTTP API end to end on a real database, with extraction faked (no OpenAI calls).

Skipped without TALLYHAWK_TEST_DATABASE_URL.
"""

import json
from pathlib import Path

import pytest
from conftest import make_extracted
from fastapi.testclient import TestClient

from tallyhawk.api import create_app
from tallyhawk.db import PostgresStore
from tallyhawk.extract import ExtractionResult, Usage
from tallyhawk.limits import DemoLimits
from tallyhawk.schema import InvoiceData
from tallyhawk.service import InvoiceService
from tallyhawk.storage import LocalFileStore
from tallyhawk.validation import low_confidence_fields, needs_review, validate_invoice
from tallyhawk.workflow import MatchingWorkflow

DATA = Path(__file__).parent.parent / "evals" / "data"
TOKEN = "test-token"


def gold(case_id: str) -> InvoiceData:
    return InvoiceData.model_validate(json.loads((DATA / "labels" / f"{case_id}.json").read_text())["invoice"])


class FakeExtractor:
    """Reads the case id from the uploaded bytes and returns that invoice's ground truth,
    optionally with edits, as if the model had extracted it."""

    def __init__(self):
        self.overrides: dict[str, dict] = {}
        self.fail: Exception | None = None

    def __call__(self, data: bytes, media_type: str) -> ExtractionResult:
        if self.fail:
            raise self.fail
        case_id = data.decode().split(":", 1)[1]
        invoice = gold(case_id).model_copy(update=self.overrides.get(case_id, {}))
        extracted = make_extracted(invoice)
        issues = validate_invoice(invoice)
        low = low_confidence_fields(extracted)
        return ExtractionResult(
            extracted=extracted,
            issues=issues,
            low_confidence_fields=low,
            needs_review=needs_review(issues, low),
            model="fake",
            usage=Usage(input_tokens=1200, output_tokens=300, cost_usd=None),
            latency_s=0.1,
        )


@pytest.fixture
def extractor():
    return FakeExtractor()


def make_client(pg_pool, tmp_path, extractor, limits: DemoLimits):
    with pg_pool.connection() as conn:
        conn.execute("truncate invoices cascade")
        conn.execute("truncate demo_usage")
        conn.execute("delete from posted_invoices where invoice_id is not null")
    service = InvoiceService(pg_pool, LocalFileStore(tmp_path), MatchingWorkflow(PostgresStore(pg_pool)), extractor)
    return TestClient(create_app(service, api_key=TOKEN, limits=limits), headers={"Authorization": f"Bearer {TOKEN}"})


@pytest.fixture
def client(pg_pool, tmp_path, extractor):
    with make_client(pg_pool, tmp_path, extractor, DemoLimits()) as c:
        yield c


@pytest.fixture
def capped(pg_pool, tmp_path, extractor):
    """2 uploads per visit, 3 per day across everyone."""
    with make_client(pg_pool, tmp_path, extractor, DemoLimits(per_session=2, per_day=3)) as c:
        yield c


def post_upload(client, case_id: str, process: bool = True, session: str | None = None):
    files = {"file": (f"{case_id}.pdf", f"case:{case_id}".encode(), "application/pdf")}
    headers = {"X-TallyHawk-Session": session} if session else {}
    return client.post("/invoices", files=files, params={"process": process}, headers=headers)


def upload(client, case_id: str, process: bool = True, session: str | None = None) -> dict:
    response = post_upload(client, case_id, process, session)
    assert response.status_code == 202, response.text
    return response.json()


def test_clean_invoice_is_approved_and_a_resubmission_is_caught(client):
    first = upload(client, "inv_001")
    detail = client.get(f"/invoices/{first['id']}").json()  # background processing ran after the response
    assert detail["invoice"]["status"] == "approved"
    assert detail["match"]["outcome"]["decision"] == "approve"
    assert detail["extraction"]["result"]["usage"]["input_tokens"] == 1200

    again = upload(client, "inv_001")
    detail = client.get(f"/invoices/{again['id']}").json()
    assert detail["invoice"]["status"] == "awaiting_review"
    assert "duplicate" in json.dumps(detail["match"]["outcome"]["issues"])


def test_review_queue_and_approval(client):
    uploaded = upload(client, "inv_011")  # goods not received yet: a person must check
    queue = client.get("/review-queue").json()
    assert [item["invoice_id"] for item in queue] == [uploaded["id"]]
    assert queue[0]["decision"] == "review" and queue[0]["issue_count"] >= 1

    response = client.post(f"/invoices/{uploaded['id']}/review", json={"action": "approve", "reviewer": "mike"})
    assert response.status_code == 200, response.text
    assert response.json()["invoice"]["status"] == "approved"
    assert response.json()["reviews"][0]["action"] == "approve"
    assert client.get("/review-queue").json() == []
    assert client.post(f"/invoices/{uploaded['id']}/review", json={"action": "approve"}).status_code == 409


def test_vendor_query_is_drafted_and_can_be_sent(client):
    uploaded = upload(client, "inv_003")  # supplier charged more than the PO price
    detail = client.get(f"/invoices/{uploaded['id']}").json()
    assert detail["match"]["outcome"]["decision"] == "vendor_query"
    assert detail["match"]["outcome"]["draft"]["subject"]
    response = client.post(f"/invoices/{uploaded['id']}/review", json={"action": "send_query"})
    assert response.json()["invoice"]["status"] == "vendor_queried"


def test_correcting_a_misread_field_rematches(client, extractor):
    truth = gold("inv_001")
    extractor.overrides["inv_001"] = {"total": truth.total + 100}  # the "model" misread the total
    uploaded = upload(client, "inv_001")
    detail = client.get(f"/invoices/{uploaded['id']}").json()
    assert detail["invoice"]["status"] == "awaiting_review"

    body = {"action": "correct", "corrected_invoice": truth.model_dump(mode="json"), "note": "total misread"}
    response = client.post(f"/invoices/{uploaded['id']}/review", json=body)
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["invoice"]["status"] == "approved"
    assert detail["match"]["source"] == "correction"
    assert detail["reviews"][0]["corrected_invoice"]["total"] == truth.total
    assert detail["extraction"]["result"]["extracted"]["invoice"]["total"] == truth.total + 100  # kept as eval data


def test_failed_extraction_is_recorded_and_can_be_retried(client, extractor):
    uploaded = upload(client, "inv_001", process=False)
    assert uploaded["status"] == "uploaded"
    extractor.fail = RuntimeError("model unavailable")
    response = client.post(f"/invoices/{uploaded['id']}/process")
    assert response.status_code == 502
    detail = client.get(f"/invoices/{uploaded['id']}").json()
    assert detail["invoice"]["status"] == "failed" and "model unavailable" in detail["invoice"]["error"]

    extractor.fail = False
    assert client.post(f"/invoices/{uploaded['id']}/process").json()["invoice"]["status"] == "approved"
    assert client.post(f"/invoices/{uploaded['id']}/process").json()["invoice"]["status"] == "approved"  # rerun


def test_file_listing_and_errors(client):
    uploaded = upload(client, "inv_001", process=False)
    file = client.get(f"/invoices/{uploaded['id']}/file")
    assert file.content == b"case:inv_001" and file.headers["content-type"] == "application/pdf"
    assert [i["id"] for i in client.get("/invoices", params={"status": "uploaded"}).json()] == [uploaded["id"]]
    assert client.get("/invoices", params={"status": "approved"}).json() == []

    assert client.get("/invoices/00000000-0000-0000-0000-000000000000").status_code == 404
    bad = client.post("/invoices", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert bad.status_code == 415
    assert client.post(f"/invoices/{uploaded['id']}/review", json={"action": "correct"}).status_code == 422
    assert client.get("/invoices", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/health", headers={"Authorization": ""}).json() == {"status": "ok"}


VISIT_A = "aaaaaaaa-1111-4111-8111-111111111111"
VISIT_B = "bbbbbbbb-2222-4222-8222-222222222222"


def test_demo_caps_per_visit_and_per_day(capped):
    client = capped
    upload(client, "inv_001", process=False, session=VISIT_A)
    upload(client, "inv_002", process=False, session=VISIT_A)
    capped = post_upload(client, "inv_003", process=False, session=VISIT_A)
    assert capped.status_code == 429 and "per visit" in capped.json()["detail"]

    upload(client, "inv_003", process=False, session=VISIT_B)  # a new visit has its own allowance
    daily = post_upload(client, "inv_004", process=False, session=VISIT_B)
    assert daily.status_code == 429 and "for today" in daily.json()["detail"]
    # Requests without a session id (direct API use) still count toward the daily cap.
    assert post_upload(client, "inv_004", process=False).status_code == 429
    assert len(client.get("/invoices").json()) == 3  # rejected uploads store nothing


def test_reprocessing_counts_against_the_caps(capped):
    client = capped
    uploaded = upload(client, "inv_001", process=False, session=VISIT_A)  # 1 of 2 for this visit
    assert client.post(f"/invoices/{uploaded['id']}/process", headers={"X-TallyHawk-Session": VISIT_A}).is_success
    again = client.post(f"/invoices/{uploaded['id']}/process", headers={"X-TallyHawk-Session": VISIT_A})
    assert again.status_code == 429


def test_used_up_openai_budget_is_explained(client, extractor):
    from test_limits import rate_limit_error

    uploaded = upload(client, "inv_001", process=False)
    extractor.fail = rate_limit_error("insufficient_quota")
    response = client.post(f"/invoices/{uploaded['id']}/process")
    assert response.status_code == 429 and "budget" in response.json()["detail"]
    detail = client.get(f"/invoices/{uploaded['id']}").json()
    assert detail["invoice"]["status"] == "failed" and "budget" in detail["invoice"]["error"]
