"""Load curated eval invoices through the real upload + process pipeline."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from psycopg_pool import ConnectionPool

from tallyhawk.agent import AgentResolver
from tallyhawk.db import PostgresStore, connect, migrate, seed_from_dir
from tallyhawk.drafting import LLMDrafter, template_drafter
from tallyhawk.extract import DEFAULT_EFFORT, DEFAULT_MODEL, extract_invoice
from tallyhawk.service import InvoiceService
from tallyhawk.storage import file_store_from_env
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
