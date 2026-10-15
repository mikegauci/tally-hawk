"""Load curated eval invoices through the real upload + process pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from tallyhawk.agent import AgentResolver
from tallyhawk.db import PostgresStore, connect, migrate, seed_from_dir
from tallyhawk.drafting import LLMDrafter, template_drafter
from tallyhawk.extract import DEFAULT_EFFORT, DEFAULT_MODEL, extract_invoice
from tallyhawk.service import InvoiceService
from tallyhawk.storage import FileStore, file_store_from_env
from tallyhawk.workflow import MatchingWorkflow

DEFAULT_DEMO_CASES = ("inv_001", "inv_002", "inv_003", "inv_007", "inv_011")
DEFAULT_INVOICES_DIR = Path("evals/data/invoices")
DEFAULT_SEED_DIR = Path("evals/data/procurement")


@dataclass
class DemoLoadResult:
    case_id: str
    invoice_id: str
    status: str
    decision: str | None
    cost_usd: float | None


def service_from_env(pool: ConnectionPool | None = None) -> InvoiceService:
    pool = pool or connect(os.environ["DATABASE_URL"])
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


def prepare_database(
    conn,
    *,
    skip_seed: bool,
    seed_dir: Path,
) -> None:
    migrate(conn)
    if not skip_seed:
        seed_from_dir(conn, seed_dir)


def load_cases(
    service: InvoiceService,
    cases: list[str],
    *,
    invoices_dir: Path = DEFAULT_INVOICES_DIR,
) -> list[DemoLoadResult]:
    results: list[DemoLoadResult] = []
    for index, case_id in enumerate(cases, start=1):
        path = invoices_dir / f"{case_id}.pdf"
        if not path.is_file():
            raise FileNotFoundError(f"Missing demo invoice {path}")
        data = path.read_bytes()
        sys.stdout.write(f"[{index}/{len(cases)}] {case_id} … ")
        sys.stdout.flush()
        record = service.upload(path.name, "application/pdf", data)
        try:
            detail = service.process(record.id)
        except Exception:
            detail = service.get(record.id)
            sys.stdout.write(f"failed ({detail.invoice.status})\n")
            results.append(
                DemoLoadResult(
                    case_id=case_id,
                    invoice_id=str(record.id),
                    status=detail.invoice.status,
                    decision=detail.match.outcome.decision if detail.match else None,
                    cost_usd=_extraction_cost(detail),
                )
            )
            continue
        decision = detail.match.outcome.decision if detail.match else None
        cost = _extraction_cost(detail)
        cost_note = f", ${cost:.3f}" if cost is not None else ""
        sys.stdout.write(f"{detail.invoice.status} (decision={decision}{cost_note})\n")
        results.append(
            DemoLoadResult(
                case_id=case_id,
                invoice_id=str(record.id),
                status=detail.invoice.status,
                decision=decision,
                cost_usd=cost,
            )
        )
    return results


def _extraction_cost(detail) -> float | None:
    if detail.extraction is None:
        return None
    usage = detail.extraction.result.usage
    return usage.cost_usd if usage else None


def run_load(
    cases: list[str],
    *,
    skip_seed: bool = False,
    seed_dir: Path = DEFAULT_SEED_DIR,
    invoices_dir: Path = DEFAULT_INVOICES_DIR,
    service: InvoiceService | None = None,
) -> int:
    """Migrate, optionally seed procurement data, then upload and process each case."""
    if service is None:
        pool = connect(os.environ["DATABASE_URL"])
        with pool.connection() as conn:
            prepare_database(conn, skip_seed=skip_seed, seed_dir=seed_dir)
        service = service_from_env(pool)
    else:
        with service.pool.connection() as conn:
            prepare_database(conn, skip_seed=skip_seed, seed_dir=seed_dir)

    results = load_cases(service, cases, invoices_dir=invoices_dir)
    failed = [r for r in results if r.status == "failed"]
    if failed:
        sys.stderr.write(f"{len(failed)} invoice(s) failed processing.\n")
        return 1
    return 0


# --- nightly reset ----------------------------------------------------------------------
#
# `demo snapshot` exports the invoice side of the database (after a paid `demo load`) to
# DEFAULT_SNAPSHOT. `demo reset` puts it back without calling OpenAI: it deletes every
# invoice visitors uploaded or reviewed, restores the snapshot rows with their timestamps
# moved up to now, re-uploads the snapshot's PDFs from the eval set, and clears the
# demo upload counters. Procurement seed data (vendors, POs, receipts) is left alone.

DEFAULT_SNAPSHOT = Path("demo/snapshot.json")

# Restored in this order (foreign keys). Generated columns are never written.
SNAPSHOT_TABLES: dict[str, list[str]] = {
    "invoices": [
        "id",
        "filename",
        "media_type",
        "storage_path",
        "size_bytes",
        "sha256",
        "status",
        "error",
        "uploaded_at",
        "updated_at",
    ],
    "extractions": [
        "id",
        "invoice_id",
        "model",
        "extracted",
        "issues",
        "low_confidence_fields",
        "needs_review",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "latency_s",
        "created_at",
    ],
    "match_results": [
        "id",
        "invoice_id",
        "extraction_id",
        "source",
        "invoice_data",
        "decision",
        "vendor_id",
        "po_number",
        "outcome",
        "cost_usd",
        "created_at",
    ],
    "reviews": ["id", "invoice_id", "match_result_id", "action", "corrected_invoice", "note", "reviewer", "created_at"],
    "posted_invoices": [
        "id",
        "vendor_id",
        "invoice_number",
        "invoice_date",
        "total",
        "status",
        "invoice_id",
        "created_at",
    ],
}
TIMESTAMPS = {
    "invoices": ["uploaded_at", "updated_at"],
    "extractions": ["created_at"],
    "match_results": ["created_at"],
    "reviews": ["created_at"],
    "posted_invoices": ["created_at"],
}


def export_snapshot(conn) -> dict:
    """The invoice-side rows, as JSON-ready data (posted invoices only where TallyHawk approved)."""
    snapshot: dict = {"version": 1}
    for table, columns in SNAPSHOT_TABLES.items():
        where = "where invoice_id is not null" if table == "posted_invoices" else ""
        cols = ", ".join(columns)
        snapshot[table] = conn.execute(
            f"select coalesce(jsonb_agg(to_jsonb(t) order by t.{columns[0]}), '[]') as rows "
            f"from (select {cols} from {table} {where}) t"
        ).fetchone()["rows"]
    return snapshot


def write_snapshot(conn, path: Path = DEFAULT_SNAPSHOT) -> dict:
    snapshot = export_snapshot(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n")
    return {table: len(snapshot[table]) for table in SNAPSHOT_TABLES}


def restore_snapshot(pool: ConnectionPool, files: FileStore, snapshot: dict, invoices_dir: Path) -> dict[str, int]:
    """Replace the invoice side of the database with `snapshot`; see the section comment."""
    pdfs = {}
    for row in snapshot["invoices"]:
        data = (invoices_dir / row["filename"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError(f"{row['filename']} no longer matches the snapshot; re-run demo load and demo snapshot.")
        pdfs[row["storage_path"]] = (data, row["media_type"])

    with pool.connection() as conn, conn.transaction():
        stale = [r["storage_path"] for r in conn.execute("select storage_path from invoices")]
        conn.execute("delete from posted_invoices where invoice_id is not null")
        conn.execute("delete from invoices")  # extractions, match results and reviews cascade
        conn.execute("truncate demo_usage")
        for table, columns in SNAPSHOT_TABLES.items():
            cols = ", ".join(columns)
            conn.execute(
                f"insert into {table} ({cols}) overriding system value "
                f"select {cols} from jsonb_populate_recordset(null::{table}, %s)",
                (Jsonb(snapshot[table]),),
            )
            if table != "invoices":  # uuid keys; the others use identity columns
                conn.execute(
                    f"select setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"coalesce((select max(id) from {table}), 0) + 1, false)"
                )
        # Make the demo look freshly loaded: move every timestamp up by the same amount.
        latest = conn.execute("select max(uploaded_at) as at from invoices").fetchone()["at"]
        if latest is not None:
            shift = datetime.now(UTC) - latest
            for table, columns in TIMESTAMPS.items():
                sets = ", ".join(f"{c} = {c} + %(shift)s" for c in columns)
                conn.execute(f"update {table} set {sets}", {"shift": shift})

    for path, (data, media_type) in pdfs.items():
        files.put(path, data, media_type)
    stale = [path for path in stale if path not in pdfs]
    if stale:
        files.delete(stale)
    return {"invoices": len(snapshot["invoices"]), "files_removed": len(stale)}


def run_reset(snapshot_path: Path = DEFAULT_SNAPSHOT, invoices_dir: Path = DEFAULT_INVOICES_DIR) -> int:
    snapshot = json.loads(snapshot_path.read_text())
    with connect(os.environ["DATABASE_URL"]) as pool:
        with pool.connection() as conn:
            migrate(conn)
        counts = restore_snapshot(pool, file_store_from_env(), snapshot, invoices_dir)
    sys.stdout.write(
        f"restored {counts['invoices']} demo invoices, removed {counts['files_removed']} uploaded files, "
        "cleared upload counters\n"
    )
    return 0
