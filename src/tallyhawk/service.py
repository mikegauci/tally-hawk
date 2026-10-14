"""The invoice pipeline behind the API: store the file, extract, match, queue for review.

An invoice moves through these statuses (column `invoices.status`):

    uploaded ─► processing ─┬─► approved          (three-way match passed, nothing to check)
                            ├─► awaiting_review   (a person must look, or the supplier must fix something)
                            └─► failed            (extraction error; `error` says why)

    awaiting_review ─► approved | rejected | vendor_queried   (a reviewer decides)

A reviewer can also *correct* fields the model misread; matching then runs again on the
corrected invoice. Corrections are kept next to the model's reading as future eval data.
Every approved invoice is added to `posted_invoices`, so a second copy of it is caught as a
duplicate.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from psycopg import Connection
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field, model_validator

from tallyhawk.extract import ExtractionResult
from tallyhawk.matching import Decision
from tallyhawk.schema import InvoiceData
from tallyhawk.storage import FileStore
from tallyhawk.workflow import MatchingWorkflow, MatchOutcome

Extractor = Callable[[bytes, str], ExtractionResult]
InvoiceStatus = Literal["uploaded", "processing", "approved", "awaiting_review", "vendor_queried", "rejected", "failed"]
ReviewAction = Literal["approve", "reject", "send_query", "correct"]

REVIEW_STATUS: dict[str, InvoiceStatus] = {"approve": "approved", "reject": "rejected", "send_query": "vendor_queried"}


class NotFound(LookupError):
    pass


class Conflict(RuntimeError):
    """The request doesn't fit the invoice's current status."""


class InvoiceRecord(BaseModel):
    id: uuid.UUID
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    status: InvoiceStatus
    error: str | None
    uploaded_at: datetime
    updated_at: datetime


class ExtractionRecord(BaseModel):
    id: int
    model: str
    result: ExtractionResult
    created_at: datetime


class MatchRecord(BaseModel):
    id: int
    source: Literal["extraction", "correction"]
    invoice: InvoiceData
    outcome: MatchOutcome
    created_at: datetime


class ReviewRecord(BaseModel):
    id: int
    match_result_id: int | None
    action: ReviewAction
    corrected_invoice: InvoiceData | None
    note: str | None
    reviewer: str | None
    created_at: datetime


class InvoiceDetail(BaseModel):
    invoice: InvoiceRecord
    extraction: ExtractionRecord | None
    match: MatchRecord | None
    reviews: list[ReviewRecord]


class QueueItem(BaseModel):
    invoice_id: uuid.UUID
    filename: str
    uploaded_at: datetime
    match_result_id: int
    decision: Decision
    vendor_id: str | None
    po_number: str | None
    invoice_number: str
    vendor_name: str
    total: float
    currency: str
    issue_count: int


class ReviewRequest(BaseModel):
    action: ReviewAction = Field(
        description=(
            "approve: pay it. reject: don't pay it. send_query: the supplier must fix something "
            "(the drafted email is in the match outcome). correct: fix misread fields and match again."
        )
    )
    corrected_invoice: InvoiceData | None = Field(
        default=None, description="The full invoice with the reviewer's fixes. Required for `correct`."
    )
    note: str | None = None
    reviewer: str | None = None

    @model_validator(mode="after")
    def _correction_needs_fields(self) -> ReviewRequest:
        if self.action == "correct" and self.corrected_invoice is None:
            raise ValueError("`correct` needs `corrected_invoice`.")
        return self


def safe_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name.rsplit("/", 1)[-1]).strip("._")
    return stem[:120] or "invoice"


class InvoiceService:
    def __init__(self, pool: ConnectionPool, files: FileStore, workflow: MatchingWorkflow, extractor: Extractor):
        self.pool = pool
        self.files = files
        self.workflow = workflow
        self.extractor = extractor

    # --- upload and processing --------------------------------------------------------

    def upload(self, filename: str, media_type: str, data: bytes) -> InvoiceRecord:
        invoice_id = uuid.uuid4()
        path = f"{invoice_id}/{safe_filename(filename)}"
        self.files.put(path, data, media_type)
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                insert into invoices (id, filename, media_type, storage_path, size_bytes, sha256)
                values (%s, %s, %s, %s, %s, %s) returning *
                """,
                (invoice_id, filename, media_type, path, len(data), hashlib.sha256(data).hexdigest()),
            ).fetchone()
        return InvoiceRecord.model_validate(row)

    def process(self, invoice_id: uuid.UUID) -> InvoiceDetail:
        """Extract and match one invoice. Calling it again re-runs it from scratch."""
        from tallyhawk.tracing import set_invoice_id, span

        set_invoice_id(str(invoice_id))
        try:
            with span("process_invoice"):
                return self._process(invoice_id)
        finally:
            set_invoice_id(None)

    def _process(self, invoice_id: uuid.UUID) -> InvoiceDetail:
        with self.pool.connection() as conn, conn.transaction():
            row = conn.execute(
                """
                update invoices set status = 'processing', error = null, updated_at = now()
                where id = %s and status <> 'processing' returning storage_path, media_type
                """,
                (invoice_id,),
            ).fetchone()
            if row is None:
                self._require(conn, invoice_id)
                raise Conflict("This invoice is already being processed.")
            # A re-run must not find this invoice's own earlier approval and call it a duplicate.
            conn.execute("delete from posted_invoices where invoice_id = %s", (invoice_id,))
        try:
            data = self.files.get(row["storage_path"])
            extraction = self.extractor(data, row["media_type"])
        except Exception as exc:  # recorded on the invoice; the reviewer sees why
            self._set_status(invoice_id, "failed", f"{type(exc).__name__}: {exc}")
            raise
        with self.pool.connection() as conn, conn.transaction():
            extraction_id = conn.execute(
                """
                insert into extractions (invoice_id, model, extracted, issues, low_confidence_fields, needs_review,
                                         input_tokens, output_tokens, cost_usd, latency_s)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id
                """,
                (
                    invoice_id,
                    extraction.model,
                    Jsonb(extraction.extracted.model_dump(mode="json")),
                    Jsonb([i.model_dump(mode="json") for i in extraction.issues]),
                    extraction.low_confidence_fields,
                    extraction.needs_review,
                    extraction.usage.input_tokens,
                    extraction.usage.output_tokens,
                    extraction.usage.cost_usd,
                    extraction.latency_s,
                ),
            ).fetchone()["id"]
        try:
            outcome = self.workflow.run(extraction.extracted.invoice, low_confidence=extraction.low_confidence_fields)
        except Exception as exc:
            self._set_status(invoice_id, "failed", f"{type(exc).__name__}: {exc}")
            raise
        with self.pool.connection() as conn, conn.transaction():
            self._save_match(conn, invoice_id, extraction_id, "extraction", extraction.extracted.invoice, outcome)
        return self.get(invoice_id)

    # --- reads ------------------------------------------------------------------------

    def list(self, status: InvoiceStatus | None = None, limit: int = 50, offset: int = 0) -> list[InvoiceRecord]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """
                select * from invoices where %(status)s::text is null or status = %(status)s
                order by uploaded_at desc, id limit %(limit)s offset %(offset)s
                """,
                {"status": status, "limit": limit, "offset": offset},
            ).fetchall()
        return [InvoiceRecord.model_validate(r) for r in rows]

    def review_queue(self, limit: int = 50, offset: int = 0) -> list[QueueItem]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "select * from review_queue order by uploaded_at, invoice_id limit %s offset %s", (limit, offset)
            ).fetchall()
        return [QueueItem.model_validate(r) for r in rows]

    def get(self, invoice_id: uuid.UUID) -> InvoiceDetail:
        with self.pool.connection() as conn:
            invoice = self._require(conn, invoice_id)
            ext = conn.execute(
                "select * from extractions where invoice_id = %s order by created_at desc, id desc limit 1",
                (invoice_id,),
            ).fetchone()
            match = conn.execute(
                "select * from match_results where invoice_id = %s order by created_at desc, id desc limit 1",
                (invoice_id,),
            ).fetchone()
            reviews = conn.execute(
                "select * from reviews where invoice_id = %s order by created_at, id", (invoice_id,)
            ).fetchall()
        return InvoiceDetail(
            invoice=InvoiceRecord.model_validate(invoice),
            extraction=_extraction_record(ext) if ext else None,
            match=_match_record(match) if match else None,
            reviews=[ReviewRecord.model_validate(r) for r in reviews],
        )

    def file(self, invoice_id: uuid.UUID) -> tuple[bytes, str, str]:
        with self.pool.connection() as conn:
            invoice = self._require(conn, invoice_id)
        return self.files.get(invoice["storage_path"]), invoice["media_type"], invoice["filename"]

    # --- review -----------------------------------------------------------------------

    def review(self, invoice_id: uuid.UUID, request: ReviewRequest) -> InvoiceDetail:
        outcome = None
        if request.action == "correct":
            with self.pool.connection() as conn:
                if self._require(conn, invoice_id)["status"] != "awaiting_review":
                    raise Conflict("Only invoices awaiting review can be corrected.")
            # Matching may call the LLM (agent, drafts), so run it before taking the row lock.
            outcome = self.workflow.run(request.corrected_invoice)
        with self.pool.connection() as conn, conn.transaction():
            invoice = conn.execute("select * from invoices where id = %s for update", (invoice_id,)).fetchone()
            if invoice is None:
                raise NotFound(f"No invoice {invoice_id}")
            if invoice["status"] != "awaiting_review":
                raise Conflict(f"Only invoices awaiting review can be reviewed; this one is {invoice['status']}.")
            current = conn.execute(
                "select * from match_results where invoice_id = %s order by created_at desc, id desc limit 1",
                (invoice_id,),
            ).fetchone()
            conn.execute(
                """
                insert into reviews (invoice_id, match_result_id, action, corrected_invoice, note, reviewer)
                values (%s, %s, %s, %s, %s, %s)
                """,
                (
                    invoice_id,
                    current["id"] if current else None,
                    request.action,
                    Jsonb(request.corrected_invoice.model_dump(mode="json")) if request.corrected_invoice else None,
                    request.note,
                    request.reviewer,
                ),
            )
            if outcome is not None:
                self._save_match(conn, invoice_id, None, "correction", request.corrected_invoice, outcome)
            else:
                status = REVIEW_STATUS[request.action]
                self._update_status(conn, invoice_id, status)
                if status == "approved" and current is not None:
                    self._post(conn, invoice_id, InvoiceData.model_validate(current["invoice_data"]), current)
        return self.get(invoice_id)

    # --- helpers ----------------------------------------------------------------------

    def _save_match(
        self,
        conn: Connection,
        invoice_id: uuid.UUID,
        extraction_id: int | None,
        source: str,
        invoice: InvoiceData,
        outcome: MatchOutcome,
    ) -> None:
        row = conn.execute(
            """
            insert into match_results (invoice_id, extraction_id, source, invoice_data, decision, vendor_id,
                                       po_number, outcome, cost_usd)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning *
            """,
            (
                invoice_id,
                extraction_id,
                source,
                Jsonb(invoice.model_dump(mode="json")),
                outcome.decision.value,
                outcome.vendor_id,
                outcome.po_number,
                Jsonb(outcome.model_dump(mode="json")),
                outcome.cost_usd,
            ),
        ).fetchone()
        if outcome.decision is Decision.APPROVE:
            self._update_status(conn, invoice_id, "approved")
            self._post(conn, invoice_id, invoice, row)
        else:
            self._update_status(conn, invoice_id, "awaiting_review")

    @staticmethod
    def _post(conn: Connection, invoice_id: uuid.UUID, invoice: InvoiceData, match: dict) -> None:
        """Record an approved invoice so a resubmitted copy is flagged as a duplicate."""
        if match["vendor_id"] is None:
            return
        conn.execute(
            """
            insert into posted_invoices (vendor_id, invoice_number, invoice_date, total, status, invoice_id)
            values (%s, %s, %s, %s, 'posted', %s)
            """,
            (match["vendor_id"], invoice.invoice_number, invoice.invoice_date, invoice.total, invoice_id),
        )

    @staticmethod
    def _update_status(conn: Connection, invoice_id: uuid.UUID, status: InvoiceStatus, error: str | None = None):
        conn.execute(
            "update invoices set status = %s, error = %s, updated_at = now() where id = %s", (status, error, invoice_id)
        )

    def _set_status(self, invoice_id: uuid.UUID, status: InvoiceStatus, error: str | None = None) -> None:
        with self.pool.connection() as conn:
            self._update_status(conn, invoice_id, status, error)

    @staticmethod
    def _require(conn: Connection, invoice_id: uuid.UUID) -> dict:
        row = conn.execute("select * from invoices where id = %s", (invoice_id,)).fetchone()
        if row is None:
            raise NotFound(f"No invoice {invoice_id}")
        return row


def _extraction_record(row: dict) -> ExtractionRecord:
    result = ExtractionResult(
        extracted=row["extracted"],
        issues=row["issues"],
        low_confidence_fields=row["low_confidence_fields"],
        needs_review=row["needs_review"],
        model=row["model"],
        usage={"input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"], "cost_usd": row["cost_usd"]},
        latency_s=float(row["latency_s"] or 0),
    )
    return ExtractionRecord(id=row["id"], model=row["model"], result=result, created_at=row["created_at"])


def _match_record(row: dict) -> MatchRecord:
    return MatchRecord(
        id=row["id"],
        source=row["source"],
        invoice=row["invoice_data"],
        outcome=row["outcome"],
        created_at=row["created_at"],
    )
