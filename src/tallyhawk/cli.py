"""Command line entry points.

tallyhawk extract invoice.pdf                 # extracted fields as JSON
tallyhawk match invoice.pdf                   # extract, then match against the PO and decide
tallyhawk match evals/data/labels/inv_003.json --resolver rules --drafter template   # no API calls
tallyhawk db migrate                          # create or update the schema at $DATABASE_URL
tallyhawk db seed                             # load the synthetic vendors, POs and receipts into it
tallyhawk match invoice.pdf --db              # match against the database instead of the seed JSON
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from tallyhawk.agent import DEFAULT_AGENT_EFFORT, AgentResolver
from tallyhawk.drafting import LLMDrafter, template_drafter
from tallyhawk.extract import DEFAULT_EFFORT, DEFAULT_MODEL, EFFORT_LEVELS, extract_file
from tallyhawk.procurement import InMemoryStore
from tallyhawk.schema import InvoiceData
from tallyhawk.workflow import MatchingWorkflow

DEFAULT_SEED_DIR = "evals/data/procurement"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tallyhawk")
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="Extract structured fields from an invoice PDF or image.")
    ex.add_argument("path")
    ex.add_argument("--model", default=DEFAULT_MODEL)
    ex.add_argument("--effort", default=DEFAULT_EFFORT, choices=EFFORT_LEVELS)

    mt = sub.add_parser("match", help="Match an invoice against its PO and goods receipts, and decide.")
    mt.add_argument("path", help="Invoice PDF/image, or a JSON file holding extracted invoice data.")
    mt.add_argument("--seed", default=DEFAULT_SEED_DIR, help="Directory with the procurement seed JSON.")
    mt.add_argument("--db", action="store_true", help="Read procurement data from $DATABASE_URL instead.")
    mt.add_argument("--model", default=DEFAULT_MODEL)
    mt.add_argument("--effort", default=DEFAULT_EFFORT, choices=EFFORT_LEVELS, help="Extraction effort.")
    mt.add_argument("--agent-effort", default=DEFAULT_AGENT_EFFORT, choices=EFFORT_LEVELS)
    mt.add_argument("--resolver", default="agent", choices=["agent", "rules"])
    mt.add_argument("--drafter", default="llm", choices=["llm", "template"])

    db = sub.add_parser("db", help="Manage the Postgres / Supabase database at $DATABASE_URL.")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("migrate", help="Apply pending migrations from supabase/migrations.")
    seed = db_sub.add_parser("seed", help="Load procurement seed JSON (vendors, POs, receipts, posted invoices).")
    seed.add_argument("--seed", default=DEFAULT_SEED_DIR)
    args = parser.parse_args(argv)

    if args.command == "db":
        from tallyhawk.db import connect, migrate, seed_from_dir

        with connect(_database_url()) as pool, pool.connection() as conn:
            if args.db_command == "migrate":
                applied = migrate(conn)
                sys.stdout.write("".join(f"applied {name}\n" for name in applied) or "schema is up to date\n")
            else:
                counts = seed_from_dir(conn, args.seed)
                sys.stdout.write(", ".join(f"{n} {table}" for table, n in counts.items()) + " loaded\n")
        return 0

    if args.command == "extract":
        result = extract_file(args.path, model=args.model, effort=args.effort)
        sys.stdout.write(result.model_dump_json(indent=2) + "\n")
        return 0

    path = Path(args.path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text())  # an eval label, `tallyhawk extract` output, or bare invoice data
        low_confidence: list[str] = data.get("low_confidence_fields", [])
        invoice = InvoiceData.model_validate(data.get("extracted", data).get("invoice", data))
    else:
        extraction = extract_file(path, model=args.model, effort=args.effort)
        invoice, low_confidence = extraction.extracted.invoice, extraction.low_confidence_fields

    if args.db:
        from tallyhawk.db import PostgresStore, connect

        store = PostgresStore(connect(_database_url()))
    else:
        store = InMemoryStore.from_dir(args.seed)
    workflow = MatchingWorkflow(
        store,
        resolver=AgentResolver(store, model=args.model, effort=args.agent_effort) if args.resolver == "agent" else None,
        drafter=LLMDrafter(model=args.model) if args.drafter == "llm" else template_drafter,
    )
    outcome = workflow.run(invoice, low_confidence=low_confidence)
    sys.stdout.write(outcome.model_dump_json(indent=2) + "\n")
    return 0


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set DATABASE_URL (a Postgres connection string) first.")
    return url


if __name__ == "__main__":
    raise SystemExit(main())
