"""Run the matching eval: does each invoice get the right decision, supplier and PO?

    uv run python -m evals.run_match_eval                       # agent + LLM drafts (needs OPENAI_API_KEY)
    uv run python -m evals.run_match_eval --resolver rules --drafter template   # rules-only baseline, free
    uv run python -m evals.run_match_eval --from-run evals/results/<extraction run>   # end to end

By default the invoices come from the ground-truth labels, which isolates matching from
extraction mistakes. `--from-run` uses a saved extraction eval run instead, so extraction
errors and low-confidence fields flow through as they would in production.

Each run writes `evals/results/match_<timestamp>/` with one outcome JSON per invoice,
`summary.json` and `report.md`.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from evals.generate_matching import SCENARIOS
from tallyhawk.agent import DEFAULT_AGENT_EFFORT, AgentResolver
from tallyhawk.drafting import LLMDrafter, template_drafter
from tallyhawk.extract import DEFAULT_MODEL, ExtractionResult, load_dotenv
from tallyhawk.matching import Decision
from tallyhawk.procurement import InMemoryStore
from tallyhawk.schema import InvoiceData
from tallyhawk.workflow import MatchingWorkflow, MatchOutcome

EVAL_DIR = Path(__file__).parent
DATA_DIR = EVAL_DIR / "data"
SEED_DIR = DATA_DIR / "procurement"
RESULTS_DIR = EVAL_DIR / "results"
DECISIONS = [d.value for d in Decision]


def load_match_labels(limit: int | None = None) -> list[dict]:
    labels = json.loads((DATA_DIR / "match_labels.json").read_text())
    return labels[:limit] if limit else labels


def load_inputs(labels: list[dict], from_run: Path | None) -> dict[str, tuple[InvoiceData, list[str]] | str]:
    """Invoice + low-confidence fields per case, or an error string if extraction failed."""
    inputs: dict[str, tuple[InvoiceData, list[str]] | str] = {}
    for label in labels:
        case_id = label["case_id"]
        if from_run is None:
            gold = json.loads((DATA_DIR / "labels" / f"{case_id}.json").read_text())
            inputs[case_id] = (InvoiceData.model_validate(gold["invoice"]), [])
            continue
        raw = json.loads((from_run / "predictions" / f"{case_id}.json").read_text())
        if "error" in raw:
            inputs[case_id] = f"extraction failed: {raw['error']}"
        else:
            result = ExtractionResult.model_validate(raw)
            inputs[case_id] = (result.extracted.invoice, result.low_confidence_fields)
    return inputs


def run_outcomes(labels: list[dict], inputs: dict, workflow: MatchingWorkflow, out_dir: Path, workers: int) -> None:
    pred_dir = out_dir / "outcomes"
    pred_dir.mkdir(parents=True, exist_ok=True)

    def one(label: dict) -> tuple[str, str]:
        case_id = label["case_id"]
        given = inputs[case_id]
        started = time.perf_counter()
        try:
            if isinstance(given, str):
                raise RuntimeError(given)
            invoice, low_confidence = given
            outcome = workflow.run(invoice, low_confidence=low_confidence)
            payload = {**outcome.model_dump(mode="json"), "latency_s": round(time.perf_counter() - started, 2)}
            status = outcome.decision.value
        except Exception as exc:  # recorded as a failed case, not a crashed run
            payload, status = {"error": f"{type(exc).__name__}: {exc}"}, f"error ({type(exc).__name__})"
        (pred_dir / f"{case_id}.json").write_text(json.dumps(payload, indent=2) + "\n")
        return case_id, status

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, label) for label in labels]
        for n, future in enumerate(as_completed(futures), start=1):
            case_id, status = future.result()
            print(f"[{n}/{len(labels)}] {case_id} {status}", file=sys.stderr)


def summarize(labels: list[dict], outcome_dir: Path) -> dict:
    confusion = {exp: dict.fromkeys(DECISIONS, 0) for exp in DECISIONS}
    by_scenario: dict[str, list[bool]] = defaultdict(list)
    code_tp, code_fp, code_fn = Counter(), Counter(), Counter()
    correct = vendor_ok = po_ok = issues_ok = 0
    false_approvals: list[str] = []
    failures: list[dict] = []
    agent_runs = drafts_expected = drafts_ok = 0
    calls: list[int] = []
    tokens: list[int] = []
    costs: list[float] = []
    latencies: list[float] = []
    cases: list[dict] = []

    for label in labels:
        case_id = label["case_id"]
        raw = json.loads((outcome_dir / f"{case_id}.json").read_text())
        if "error" in raw:
            failures.append({"case_id": case_id, "error": raw["error"]})
            continue
        outcome = MatchOutcome.model_validate(raw)
        expected = label["expected_decision"]
        got = outcome.decision.value
        confusion[expected][got] += 1
        hit = got == expected
        correct += hit
        by_scenario[label["scenario"]].append(hit)
        if got == "approve" and expected != "approve":
            false_approvals.append(case_id)

        vendor_ok += outcome.vendor_id == label["expected_vendor_id"]
        po_ok += outcome.po_number == label["expected_po_number"]
        codes = {i.code for i in outcome.issues}
        wanted = set(label["expected_issues"])
        issues_ok += codes == wanted
        for code in codes | wanted:
            if code in codes and code in wanted:
                code_tp[code] += 1
            elif code in codes:
                code_fp[code] += 1
            else:
                code_fn[code] += 1

        agent_runs += outcome.resolution is not None
        if got == "vendor_query":
            drafts_expected += 1
            body = f"{outcome.draft.subject}\n{outcome.draft.body}" if outcome.draft else ""
            mentions_po = outcome.po_number is None or outcome.po_number in body
            drafts_ok += outcome.invoice_number in body and mentions_po
        calls.append(outcome.llm_calls)
        tokens.append(outcome.input_tokens + outcome.output_tokens)
        if outcome.cost_usd is not None:
            costs.append(outcome.cost_usd)
        latencies.append(raw.get("latency_s", 0.0))
        cases.append(
            {
                "case_id": case_id,
                "scenario": label["scenario"],
                "expected": expected,
                "decision": got,
                "issues": sorted(codes),
                "expected_issues": sorted(wanted),
                "po_number": outcome.po_number,
                "expected_po_number": label["expected_po_number"],
                "agent_reasoning": outcome.resolution.reasoning if outcome.resolution else None,
            }
        )

    scored = len(labels) - len(failures)
    ratio = lambda n: round(n / scored, 4) if scored else None  # noqa: E731
    return {
        "n_cases": len(labels),
        "n_scored": scored,
        "failures": failures,
        "decision_accuracy": ratio(correct),
        "false_approvals": false_approvals,
        "false_approval_rate": ratio(len(false_approvals)),
        "auto_approval_rate": ratio(sum(row["approve"] for row in confusion.values())),
        "vendor_accuracy": ratio(vendor_ok),
        "po_accuracy": ratio(po_ok),
        "issue_set_accuracy": ratio(issues_ok),
        "issue_codes": {
            code: {"tp": code_tp[code], "fp": code_fp[code], "fn": code_fn[code]}
            for code in sorted(set(code_tp) | set(code_fp) | set(code_fn))
        },
        "confusion": confusion,
        "accuracy_by_scenario": {s: round(sum(h) / len(h), 4) for s, h in sorted(by_scenario.items())},
        "agent_invocation_rate": ratio(agent_runs),
        "draft_mentions_refs": round(drafts_ok / drafts_expected, 4) if drafts_expected else None,
        "llm_calls_per_invoice": round(statistics.mean(calls), 2) if calls else None,
        "tokens_per_invoice": round(statistics.mean(tokens)) if tokens else None,
        "cost_usd_total": round(sum(costs), 4),
        "cost_usd_per_invoice": round(sum(costs) / scored, 5) if costs and scored else None,
        "latency_s_p50": round(statistics.median(latencies), 2) if latencies else None,
        "cases": cases,
    }


def render_report(summary: dict, meta: dict) -> str:
    def fmt(v: float | None) -> str:
        return "n/a" if v is None else f"{v * 100:.1f}%"

    cost = summary["cost_usd_per_invoice"]
    cost_text = "n/a (no LLM calls, or TALLYHAWK_PRICE_* unset)" if cost is None else f"${cost:.4f}"
    lines = [
        "# TallyHawk matching eval",
        "",
        f"Resolver `{meta['resolver']}`, drafter `{meta['drafter']}`, model `{meta['model']}`, "
        f"input `{meta['input']}`, run {meta['started']}.",
        f"Scored {summary['n_scored']} of {summary['n_cases']} invoices ({len(summary['failures'])} failed).",
        "",
        "## Headline",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Decision accuracy | {fmt(summary['decision_accuracy'])} |",
        f"| False approvals (approved but shouldn't be) | {len(summary['false_approvals'])} |",
        f"| Auto-approved | {fmt(summary['auto_approval_rate'])} |",
        f"| Right supplier | {fmt(summary['vendor_accuracy'])} |",
        f"| Right PO (or correctly none) | {fmt(summary['po_accuracy'])} |",
        f"| Exactly the right issues | {fmt(summary['issue_set_accuracy'])} |",
        f"| Agent invoked | {fmt(summary['agent_invocation_rate'])} |",
        f"| Supplier emails quoting invoice and PO | {fmt(summary['draft_mentions_refs'])} |",
        f"| LLM calls per invoice | {summary['llm_calls_per_invoice']} |",
        f"| Tokens per invoice | {summary['tokens_per_invoice']} |",
        f"| Cost per invoice | {cost_text} |",
        "",
        "## Decisions (rows: expected, columns: actual)",
        "",
        "| | " + " | ".join(DECISIONS) + " |",
        "|---|" + "---|" * len(DECISIONS),
        *(
            f"| {exp} | " + " | ".join(str(summary["confusion"][exp][got]) for got in DECISIONS) + " |"
            for exp in DECISIONS
        ),
        "",
        "## Accuracy by scenario",
        "",
        "| Scenario | What it tests | Decision accuracy |",
        "|---|---|---|",
        *(f"| {s} | {SCENARIOS[s][2]} | {fmt(acc)} |" for s, acc in summary["accuracy_by_scenario"].items()),
        "",
        "## Issue codes",
        "",
        "| Code | Found | False alarms | Missed |",
        "|---|---|---|---|",
        *(f"| {code} | {c['tp']} | {c['fp']} | {c['fn']} |" for code, c in summary["issue_codes"].items()),
    ]
    wrong = [c for c in summary["cases"] if c["decision"] != c["expected"] or c["issues"] != c["expected_issues"]]
    if wrong:
        lines += [
            "",
            "## Cases that differ from the label",
            "",
            "| Case | Scenario | Expected | Got | Issues | Expected issues |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {c['case_id']} | {c['scenario']} | {c['expected']} | {c['decision']} | "
            f"{', '.join(c['issues'])} | {', '.join(c['expected_issues'])} |"
            for c in wrong
        ]
    if summary["failures"]:
        lines += ["", "## Failed cases", ""] + [f"- {f['case_id']}: {f['error']}" for f in summary["failures"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resolver", default="agent", choices=["agent", "rules"])
    parser.add_argument("--drafter", default="llm", choices=["llm", "template"])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default=DEFAULT_AGENT_EFFORT, help="Reasoning effort for the agent.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--from-run", type=Path, help="Extraction eval run to take invoices from (end to end).")
    args = parser.parse_args(argv)
    load_dotenv()

    labels = load_match_labels(args.limit)
    store = InMemoryStore.from_dir(SEED_DIR)
    workflow = MatchingWorkflow(
        store,
        resolver=AgentResolver(store, model=args.model, effort=args.effort) if args.resolver == "agent" else None,
        drafter=LLMDrafter(model=args.model) if args.drafter == "llm" else template_drafter,
    )
    started = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_DIR / f"match_{started}_{args.resolver}"
    meta = {
        "resolver": args.resolver,
        "drafter": args.drafter,
        "model": args.model if args.drafter == "llm" or args.resolver == "agent" else "none",
        "effort": args.effort,
        "input": str(args.from_run) if args.from_run else "gold labels",
        "started": started,
    }
    run_outcomes(labels, load_inputs(labels, args.from_run), workflow, out_dir, args.workers)
    summary = summarize(labels, out_dir / "outcomes")
    (out_dir / "summary.json").write_text(json.dumps({"meta": meta, **summary}, indent=2) + "\n")
    report = render_report(summary, meta)
    (out_dir / "report.md").write_text(report)
    print(report)
    print(f"Saved to {out_dir}", file=sys.stderr)
    return summary


if __name__ == "__main__":
    main()
