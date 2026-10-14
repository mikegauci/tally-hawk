"""Run the extraction eval and report per-field accuracy.

    uv run python -m evals.run_eval                    # all 50 invoices
    uv run python -m evals.run_eval --limit 5          # quick smoke run
    uv run python -m evals.run_eval --rescore evals/results/<run>   # re-score saved predictions, no API calls

Each run writes `evals/results/<timestamp>/` with one prediction JSON per invoice,
`summary.json`, and a human-readable `report.md`.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from evals.scoring import score_invoice
from tallyhawk.extract import DEFAULT_EFFORT, DEFAULT_MODEL, ExtractionResult, extract_file
from tallyhawk.schema import HEADER_FIELDS, InvoiceData
from tallyhawk.validation import DEFAULT_CONFIDENCE_THRESHOLD, Severity

EVAL_DIR = Path(__file__).parent
DATA_DIR = EVAL_DIR / "data"
RESULTS_DIR = EVAL_DIR / "results"
# Issue codes that come from the invoice itself, which a correct extraction must reproduce.
SCORED_ISSUES = ("line_amount_mismatch", "subtotal_mismatch", "total_mismatch", "tax_mismatch", "missing_po")


def load_labels(limit: int | None = None) -> list[dict]:
    labels = [json.loads(p.read_text()) for p in sorted((DATA_DIR / "labels").glob("*.json"))]
    return labels[:limit] if limit else labels


def run_predictions(labels: list[dict], out_dir: Path, model: str, effort: str, workers: int) -> None:
    pred_dir = out_dir / "predictions"
    pred_dir.mkdir(parents=True, exist_ok=True)

    def one(label: dict) -> tuple[str, str]:
        pdf = DATA_DIR / "invoices" / f"{label['case_id']}.pdf"
        try:
            result = extract_file(pdf, model=model, effort=effort)
            payload, status = result.model_dump_json(indent=2), "ok"
        except Exception as exc:  # recorded as a failed case, not a crashed run
            payload = json.dumps({"error": f"{type(exc).__name__}: {exc}"}, indent=2)
            status = f"error ({type(exc).__name__})"
        (pred_dir / f"{label['case_id']}.json").write_text(payload + "\n")
        return label["case_id"], status

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, label) for label in labels]
        for n, future in enumerate(as_completed(futures), start=1):
            case_id, status = future.result()
            print(f"[{n}/{len(labels)}] {case_id} {status}", file=sys.stderr)


def summarize(labels: list[dict], pred_dir: Path, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> dict:
    field_hits: dict[str, list[bool]] = defaultdict(list)
    per_tag: dict[str, list[bool]] = defaultdict(list)
    calibration = {"high": [0, 0], "low": [0, 0]}  # [correct, total] for confidence >= / < threshold
    issue_tp, issue_fp, issue_fn = Counter(), Counter(), Counter()
    line_correct = line_total = 0
    docs_correct = silent_errors = flagged = 0
    failures: list[dict] = []
    costs: list[float] = []
    tokens: list[int] = []
    latencies: list[float] = []
    cases: list[dict] = []

    for label in labels:
        case_id = label["case_id"]
        raw = json.loads((pred_dir / f"{case_id}.json").read_text())
        if "error" in raw:
            failures.append({"case_id": case_id, "error": raw["error"]})
            continue
        result = ExtractionResult.model_validate(raw)
        gold = InvoiceData.model_validate(label["invoice"])
        score = score_invoice(result.extracted.invoice, gold)

        for name, ok in score["fields"].items():
            field_hits[name].append(ok)
        line_correct += score["line_fields_correct"]
        line_total += score["line_fields_total"]
        docs_correct += score["all_correct"]
        for tag in label["tags"]:
            per_tag[tag].append(score["all_correct"])

        confidences = result.extracted.confidence.model_dump()
        for name in (*HEADER_FIELDS, "line_items"):
            bucket = "high" if confidences[name] >= threshold else "low"
            calibration[bucket][0] += score["fields"][name]
            calibration[bucket][1] += 1

        predicted_issues = {i.code for i in result.issues if i.code in SCORED_ISSUES}
        expected_issues = set(label["expected_issues"])
        for code in SCORED_ISSUES:
            if code in predicted_issues and code in expected_issues:
                issue_tp[code] += 1
            elif code in predicted_issues:
                issue_fp[code] += 1
            elif code in expected_issues:
                issue_fn[code] += 1

        flagged += result.needs_review
        if not score["all_correct"] and not result.needs_review:
            silent_errors += 1
        if result.usage.cost_usd is not None:
            costs.append(result.usage.cost_usd)
        tokens.append(result.usage.input_tokens + result.usage.output_tokens)
        latencies.append(result.latency_s)
        cases.append(
            {
                "case_id": case_id,
                "all_correct": score["all_correct"],
                "wrong_fields": [k for k, v in score["fields"].items() if not v],
                "needs_review": result.needs_review,
                "issues": sorted(i.code for i in result.issues if i.severity is Severity.ERROR),
                "expected_issues": label["expected_issues"],
            }
        )

    scored = len(labels) - len(failures)
    pct = lambda hits: round(sum(hits) / len(hits), 4) if hits else None  # noqa: E731
    return {
        "n_cases": len(labels),
        "n_scored": scored,
        "failures": failures,
        "field_accuracy": {name: pct(hits) for name, hits in field_hits.items()},
        "line_item_field_accuracy": round(line_correct / line_total, 4) if line_total else None,
        "document_accuracy": round(docs_correct / scored, 4) if scored else None,
        "accuracy_by_tag": {tag: pct(hits) for tag, hits in sorted(per_tag.items())},
        "confidence_calibration": {
            "threshold": threshold,
            "high_conf_accuracy": round(calibration["high"][0] / calibration["high"][1], 4)
            if calibration["high"][1]
            else None,
            "high_conf_fields": calibration["high"][1],
            "low_conf_accuracy": round(calibration["low"][0] / calibration["low"][1], 4)
            if calibration["low"][1]
            else None,
            "low_conf_fields": calibration["low"][1],
        },
        "issue_detection": {
            code: {"tp": issue_tp[code], "fp": issue_fp[code], "fn": issue_fn[code]} for code in SCORED_ISSUES
        },
        "review_rate": round(flagged / scored, 4) if scored else None,
        "silent_error_rate": round(silent_errors / scored, 4) if scored else None,
        "cost_usd_total": round(sum(costs), 4),
        "cost_usd_per_invoice": round(statistics.mean(costs), 5) if costs else None,
        "tokens_per_invoice": round(statistics.mean(tokens)) if tokens else None,
        "latency_s_p50": round(statistics.median(latencies), 2) if latencies else None,
        "latency_s_max": max(latencies) if latencies else None,
        "cases": cases,
    }


def render_report(summary: dict, meta: dict) -> str:
    def fmt(v: float | None) -> str:
        return "n/a" if v is None else f"{v * 100:.1f}%"

    per_invoice = summary["cost_usd_per_invoice"]
    cost = "n/a (set TALLYHAWK_PRICE_* to report)" if per_invoice is None else f"${per_invoice:.4f}"
    lines = [
        "# TallyHawk extraction eval",
        "",
        f"Model `{meta['model']}`, effort `{meta['effort']}`, run {meta['started']}.",
        f"Scored {summary['n_scored']} of {summary['n_cases']} invoices ({len(summary['failures'])} failed).",
        "",
        "## Headline",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Document accuracy (every field right) | {fmt(summary['document_accuracy'])} |",
        f"| Line-item field accuracy | {fmt(summary['line_item_field_accuracy'])} |",
        f"| Sent to human review | {fmt(summary['review_rate'])} |",
        f"| Silent errors (wrong and not flagged) | {fmt(summary['silent_error_rate'])} |",
        f"| Tokens per invoice (in + out) | {summary['tokens_per_invoice']} |",
        f"| Cost per invoice | {cost} |",
        f"| Median latency | {summary['latency_s_p50']}s |",
        "",
        "## Per-field accuracy",
        "",
        "| Field | Accuracy |",
        "|---|---|",
        *(f"| {name} | {fmt(acc)} |" for name, acc in summary["field_accuracy"].items()),
        "",
        "## Confidence calibration",
        "",
        f"Fields scored at or above {summary['confidence_calibration']['threshold']}: "
        f"{fmt(summary['confidence_calibration']['high_conf_accuracy'])} correct "
        f"({summary['confidence_calibration']['high_conf_fields']} fields). Below: "
        f"{fmt(summary['confidence_calibration']['low_conf_accuracy'])} correct "
        f"({summary['confidence_calibration']['low_conf_fields']} fields).",
        "",
        "## Validation issue detection",
        "",
        "| Issue | Caught | False alarms | Missed |",
        "|---|---|---|---|",
        *(f"| {code} | {c['tp']} | {c['fp']} | {c['fn']} |" for code, c in summary["issue_detection"].items()),
        "",
        "## Accuracy by tag",
        "",
        "| Tag | Document accuracy |",
        "|---|---|",
        *(f"| {tag} | {fmt(acc)} |" for tag, acc in summary["accuracy_by_tag"].items()),
    ]
    wrong = [c for c in summary["cases"] if not c["all_correct"]]
    if wrong:
        lines += ["", "## Cases with errors", "", "| Case | Wrong fields | Flagged for review |", "|---|---|---|"]
        lines += [f"| {c['case_id']} | {', '.join(c['wrong_fields'])} | {c['needs_review']} |" for c in wrong]
    if summary["failures"]:
        lines += ["", "## Failed cases", ""] + [f"- {f['case_id']}: {f['error']}" for f in summary["failures"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default=DEFAULT_EFFORT)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rescore", type=Path, help="Existing run directory to re-score without calling the API.")
    args = parser.parse_args(argv)

    labels = load_labels(args.limit)
    if args.rescore:
        out_dir = args.rescore
        meta = json.loads((out_dir / "summary.json").read_text())["meta"]
        labels = [lb for lb in labels if (out_dir / "predictions" / f"{lb['case_id']}.json").exists()]
    else:
        started = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_dir = RESULTS_DIR / f"{started}_{args.model}"
        meta = {"model": args.model, "effort": args.effort, "started": started}
        run_predictions(labels, out_dir, args.model, args.effort, args.workers)

    summary = summarize(labels, out_dir / "predictions")
    (out_dir / "summary.json").write_text(json.dumps({"meta": meta, **summary}, indent=2) + "\n")
    report = render_report(summary, meta)
    (out_dir / "report.md").write_text(report)
    print(report)
    print(f"Saved to {out_dir}", file=sys.stderr)
    return summary


if __name__ == "__main__":
    main()
