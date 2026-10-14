"""`tallyhawk extract invoice.pdf` prints the extraction result as JSON."""

from __future__ import annotations

import argparse
import sys

from tallyhawk.extract import DEFAULT_EFFORT, DEFAULT_MODEL, EFFORT_LEVELS, extract_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tallyhawk")
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="Extract structured fields from an invoice PDF or image.")
    ex.add_argument("path")
    ex.add_argument("--model", default=DEFAULT_MODEL)
    ex.add_argument("--effort", default=DEFAULT_EFFORT, choices=EFFORT_LEVELS)
    args = parser.parse_args(argv)

    result = extract_file(args.path, model=args.model, effort=args.effort)
    sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
