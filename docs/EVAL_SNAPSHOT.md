# Evaluation snapshot (pinned runs)

Headline numbers for portfolio readers. Regenerate with the commands below; full reports
land under `evals/results/` (gitignored locally).

## Extraction (GPT-5.5, standard + hard set)

Run: `uv run python -m evals.run_eval`

Pinned run: `evals/results/20261014T131749Z_gpt-5.5/report.md`

| Metric | All (68) | Standard (50) | Hard (18) |
| --- | --- | --- | --- |
| Document accuracy | 91.2% | 100.0% | 66.7% |
| Line-item field accuracy | 99.9% | 100.0% | 99.4% |
| Sent to human review | 13.2% | 8.0% | 27.8% |
| Silent errors | 4.4% | 0.0% | 16.7% |
| Cost per invoice | $0.0278 | — | — |

The live CI gate uses the **standard set only** (`uv run pytest -m live`).

## Matching (rules baseline, no LLM)

Run: `uv run python -m evals.run_match_eval --resolver rules --drafter template`

Pinned run: `evals/results/match_20261014T153251Z_rules/report.md`

| Metric | Value |
| --- | --- |
| Decision accuracy | 82.0% |
| False approvals | 0 |
| Auto-approved | 28.0% |

The nine misses are missing-PO and PO-typo scenarios that need the agent (`--resolver agent`).

## Matching (with agent)

Run: `uv run python -m evals.run_match_eval` (needs `OPENAI_API_KEY`) or the **Matching eval** GitHub Action.

Pinned runs: `evals/results/match_20261015T101533Z_agent/report.md` (gold labels) and
`evals/results/match_20261015T101657Z_agent/report.md` (end to end, invoices taken from the
pinned extraction run above).

| Metric | Gold labels | End to end |
| --- | --- | --- |
| Decision accuracy | 100.0% | 100.0% |
| False approvals | 0 | 0 |
| Auto-approved | 28.0% | 28.0% |
| Right PO (or correctly none) | 100.0% | 100.0% |
| Agent invoked | 28.0% | 28.0% |
| LLM calls per invoice | 1.3 | 1.28 |
| Cost per invoice | $0.0095 | $0.0098 |

The agent fixes all nine missing-PO and PO-typo cases the rules baseline gets wrong, and
every PO it finds still goes to a human. 28% auto-approved is the ceiling: 14 of the 50
scenarios should be approved.

**Read these numbers with care.** The 50 matching scenarios sit on the standard invoices,
where extraction is already 100% accurate, so "end to end" here doesn't yet test how
matching copes with extraction mistakes from scans. The matching eval is saturated and
needs harder scenarios (see [Known weaknesses](../README.md#known-weaknesses-and-next-steps)).

## Cost per invoice

Extraction ($0.0278) plus matching with the agent ($0.0098): about **$0.038 per invoice**
at gpt-5.5 list prices ($5 / $30 per million input / output tokens).
