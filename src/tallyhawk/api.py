"""HTTP API for the web app: upload invoices, see results, work the review queue.

    uv run uvicorn tallyhawk.api:app --reload

Configuration comes from the environment (see `.env.example`): `DATABASE_URL` (required),
`OPENAI_API_KEY`, file storage (`SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`, or a local
`TALLYHAWK_STORAGE_DIR`), and `TALLYHAWK_API_KEY`, the bearer token clients must send.
Interactive docs are served at /docs.
"""

import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tallyhawk.agent import AgentResolver
from tallyhawk.db import PostgresStore, connect
from tallyhawk.drafting import LLMDrafter, template_drafter
from tallyhawk.extract import DEFAULT_EFFORT, DEFAULT_MODEL, MEDIA_TYPES, extract_invoice
from tallyhawk.limits import QUOTA_MESSAGE, DemoLimits, LimitReached, claim_upload, is_quota_error, session_id
from tallyhawk.service import (
    Conflict,
    InvoiceDetail,
    InvoiceRecord,
    InvoiceService,
    InvoiceStatus,
    NotFound,
    QueueItem,
    ReviewRequest,
)
from tallyhawk.storage import file_store_from_env
from tallyhawk.workflow import MatchingWorkflow

log = logging.getLogger("tallyhawk.api")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def service_from_env() -> InvoiceService:
    pool = connect(os.environ["DATABASE_URL"])
    store = PostgresStore(pool)
    use_llm = os.environ.get("TALLYHAWK_RESOLVER", "agent") == "agent"
    workflow = MatchingWorkflow(
        store,
        resolver=AgentResolver(store) if use_llm else None,
        drafter=LLMDrafter() if os.environ.get("TALLYHAWK_DRAFTER", "llm") == "llm" else template_drafter,
    )
    return InvoiceService(
        pool,
        file_store_from_env(),
        workflow,
        extractor=lambda data, media_type: extract_invoice(
            data, media_type, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT
        ),
    )


def create_app(
    service: InvoiceService | None = None, api_key: str | None = None, limits: DemoLimits | None = None
) -> FastAPI:
    """`service`, `api_key` and `limits` default to the environment (tests pass their own)."""
    limits = limits if limits is not None else DemoLimits.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or service_from_env()
        yield
        if service is None:
            app.state.service.pool.close()

    app = FastAPI(
        title="TallyHawk",
        summary="Invoice extraction, three-way matching and a review queue for accounts payable.",
        lifespan=lifespan,
    )
    origins = [o.strip() for o in os.environ.get("TALLYHAWK_CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    token = api_key if api_key is not None else os.environ.get("TALLYHAWK_API_KEY", "")
    if not token:
        log.warning("TALLYHAWK_API_KEY is not set: the API accepts requests without a token (local use only).")
    bearer = HTTPBearer(auto_error=False)

    def authorize(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> None:
        if token and (credentials is None or not secrets.compare_digest(credentials.credentials, token)):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or wrong bearer token.")

    def svc(request: Request) -> InvoiceService:
        return request.app.state.service

    Service = Annotated[InvoiceService, Depends(svc)]
    auth = [Depends(authorize)]

    def found(fn, *args):
        try:
            return fn(*args)
        except NotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except Conflict as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    # Sent by the web app's proxy from its signed session cookie; see tallyhawk.limits.
    SessionHeader = Annotated[str | None, Header(alias="X-TallyHawk-Session", include_in_schema=False)]

    def claim(service: InvoiceService, session: str | None) -> None:
        try:
            claim_upload(service.pool, limits, session_id(session))
        except LimitReached as exc:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc

    def process_quietly(service: InvoiceService, invoice_id: uuid.UUID) -> None:
        try:
            service.process(invoice_id)
        except Exception:  # the failure is saved on the invoice (status `failed`)
            log.exception("Processing invoice %s failed", invoice_id)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/invoices", status_code=status.HTTP_202_ACCEPTED, dependencies=auth, tags=["invoices"])
    async def upload_invoice(
        service: Service,
        background: BackgroundTasks,
        file: Annotated[UploadFile, File(description="Invoice PDF or image (PNG, JPEG, WebP).")],
        process: Annotated[bool, Query(description="Extract and match in the background right away.")] = True,
        session: SessionHeader = None,
    ) -> InvoiceRecord:
        """Upload a supplier invoice. With `process=true` (the default) extraction and matching
        start in the background; poll `GET /invoices/{id}` until the status leaves `processing`."""
        filename = file.filename or "invoice"
        suffix = os.path.splitext(filename)[1].lower()
        media_type = MEDIA_TYPES.get(suffix) or (
            file.content_type if file.content_type in MEDIA_TYPES.values() else None
        )
        if media_type is None:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Upload a PDF or image ({', '.join(sorted(MEDIA_TYPES))})."
            )
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Invoices are limited to 20 MB.")
        if not data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty.")
        claim(service, session)
        record = service.upload(filename, media_type, data)
        if process:
            background.add_task(process_quietly, service, record.id)
        return record

    @app.post("/invoices/{invoice_id}/process", dependencies=auth, tags=["invoices"])
    def process_invoice(service: Service, invoice_id: uuid.UUID, session: SessionHeader = None) -> InvoiceDetail:
        """Run (or re-run) extraction and matching now, and wait for the result. A re-run counts
        against the demo caps like an upload, since it calls the model again."""
        claim(service, session)
        try:
            return found(service.process, invoice_id)
        except HTTPException:
            raise
        except Exception as exc:
            if is_quota_error(exc):
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, QUOTA_MESSAGE) from exc
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Processing failed: {exc}") from exc

    @app.get("/invoices", dependencies=auth, tags=["invoices"])
    def list_invoices(
        service: Service,
        status_: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[InvoiceRecord]:
        return service.list(status_, limit, offset)

    @app.get("/invoices/{invoice_id}", dependencies=auth, tags=["invoices"])
    def get_invoice(service: Service, invoice_id: uuid.UUID) -> InvoiceDetail:
        """The invoice with its latest extraction, latest match outcome and review history."""
        return found(service.get, invoice_id)

    @app.get("/invoices/{invoice_id}/file", dependencies=auth, tags=["invoices"])
    def get_invoice_file(service: Service, invoice_id: uuid.UUID) -> Response:
        """The original upload, for showing the PDF beside the extracted fields."""
        data, media_type, filename = found(service.file, invoice_id)
        return Response(data, media_type=media_type, headers={"Content-Disposition": f'inline; filename="{filename}"'})

    @app.get("/review-queue", dependencies=auth, tags=["review"])
    def review_queue(
        service: Service,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[QueueItem]:
        """Invoices waiting for a person, oldest first. `decision` says why: `review` means the
        finance team must check something; `vendor_query` means the supplier must fix something."""
        return service.review_queue(limit, offset)

    @app.post("/invoices/{invoice_id}/review", dependencies=auth, tags=["review"])
    def review_invoice(service: Service, invoice_id: uuid.UUID, body: ReviewRequest) -> InvoiceDetail:
        """Approve, reject or query an invoice in the review queue, or correct its fields and
        match again."""
        return found(service.review, invoice_id, body)

    return app


app = create_app()
