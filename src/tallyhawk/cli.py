"""Command line entry points.

tallyhawk extract invoice.pdf                 # extracted fields as JSON
tallyhawk match invoice.pdf                   # extract, then match against the PO and decide
tallyhawk match evals/data/labels/inv_003.json --resolver rules --drafter template   # no API calls
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tallyhawk.agent import DEFAULT_AGENT_EFFORT, AgentResolver
from tallyhawk.drafting import LLMDrafter, template_drafter
from tallyhawk.extract import EFFORT_LEVELS, default_effort, default_model, extract_file, load_dotenv
from tallyhawk.procurement import InMemoryStore
from tallyhawk.schema import InvoiceData
from tallyhawk.workflow import MatchingWorkflow

DEFAULT_SEED_DIR = "evals/data/procurement"


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="tallyhawk")
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="Extract structured fields from an invoice PDF or image.")
    ex.add_argument("path")
    ex.add_argument("--model", default=default_model())
    ex.add_argument("--effort", default=default_effort(), choices=EFFORT_LEVELS)

    mt = sub.add_parser("match", help="Match an invoice against its PO and goods receipts, and decide.")
    mt.add_argument("path", help="Invoice PDF/image, or a JSON file holding extracted invoice data.")
    mt.add_argument("--seed", default=DEFAULT_SEED_DIR, help="Directory with the procurement seed JSON.")
    mt.add_argument("--model", default=default_model())
    mt.add_argument("--effort", default=default_effort(), choices=EFFORT_LEVELS, help="Extraction effort.")
    mt.add_argument("--agent-effort", default=DEFAULT_AGENT_EFFORT, choices=EFFORT_LEVELS)
    mt.add_argument("--resolver", default="agent", choices=["agent", "rules"])
    mt.add_argument("--drafter", default="llm", choices=["llm", "template"])
    args = parser.parse_args(argv)

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

    store = InMemoryStore.from_dir(args.seed)
    workflow = MatchingWorkflow(
        store,
        resolver=AgentResolver(store, model=args.model, effort=args.agent_effort) if args.resolver == "agent" else None,
        drafter=LLMDrafter(model=args.model) if args.drafter == "llm" else template_drafter,
    )
    outcome = workflow.run(invoice, low_confidence=low_confidence)
    sys.stdout.write(outcome.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
