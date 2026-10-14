# TallyHawk

**AI invoice processing for small finance teams.** TallyHawk reads supplier invoices,
pulls out the data an accounts payable clerk would type in by hand, checks that the
numbers add up, and (in the next step) matches each invoice against its purchase order
and goods receipt so only the problem invoices reach a person.

> Status: step 1 of 4, extraction and evaluation. See [the build plan](CLAUDE.md#build-plan).

## What step 1 does

```
invoice.pdf ──► OpenAI GPT-5.5 (reads the PDF directly, structured output)
                  │  vendor, invoice no., dates, PO number, currency,
                  │  line items, subtotal, tax, total + confidence per field
                  ▼
             Validation rules
                  │  qty × price = line amount? lines = subtotal?
                  │  subtotal + tax = total? tax rate × subtotal = tax?
                  ▼
     auto-OK  or  needs review (any rule broken, or any field < 0.9 confidence)
```

- **No OCR pipeline.** The model reads the PDF natively; the output is constrained to a
  Pydantic schema via structured outputs, so it always parses.
- **Confidence per field.** The reviewer only has to look at what the model was unsure
  about, and the eval measures whether that confidence is trustworthy.
- **Validation catches supplier mistakes too.** Extraction copies what's printed; the
  rules then flag invoices whose own arithmetic is wrong.

## Quick start

```bash
uv sync
cp .env.example .env   # add your OPENAI_API_KEY, then: export $(cat .env | xargs)
uv run tallyhawk extract evals/data/invoices/inv_001.pdf
```

Output (abridged and illustrative; real numbers come from the eval run):

```json
{
  "extracted": {
    "invoice": { "vendor_name": "Kestrel Building Materials Ltd", "po_number": "HVH-3330", "total": 884.0, ... },
    "confidence": { "vendor_name": 0.99, "po_number": 0.97, ... }
  },
  "issues": [],
  "needs_review": false,
  "usage": { "input_tokens": 3120, "output_tokens": 640, "cost_usd": 0.025 }
}
```

## Evaluation

`evals/data/` holds 50 synthetic invoices with known answers, generated deterministically
by `evals/generate.py`. They vary on purpose:

| Variation | Why it's hard |
|---|---|
| 5 layouts (classic, US, European, compact, multi-page) | Labels and positions move around |
| European formatting (`1.234,56 €`, `11.08.2026`) | Decimal commas and day-first dates |
| Multi-page invoices with 40–55 lines | Long tables split across pages |
| Missing PO number, due date, tax ID or tax rate | Model must return null, not guess |
| Buyer's tax ID printed next to the supplier's | Easy to grab the wrong one |
| 4 invoices with the supplier's own maths wrong | Extraction must copy, validation must catch |

Run it:

```bash
uv run python -m evals.run_eval            # all 50 invoices
uv run python -m evals.run_eval --limit 5  # smoke test
```

The report (`evals/results/<run>/report.md`) covers:

- **Per-field accuracy** for every header field, plus line-item accuracy.
- **Document accuracy**: share of invoices with every field right.
- **Silent error rate**: invoices with a wrong field that were *not* sent to review. This
  is the number that matters for automation.
- **Confidence calibration**: accuracy of high- vs low-confidence fields.
- **Validation issue detection**: supplier errors caught, missed and false alarms.
- **Cost per invoice** and latency.

`uv run pytest -m live` runs the same eval with pass/fail thresholds, and the
**Extraction eval** GitHub Action runs it on demand (add an `OPENAI_API_KEY` secret).
To get cost per invoice, set `TALLYHAWK_PRICE_INPUT_PER_MTOK` and
`TALLYHAWK_PRICE_OUTPUT_PER_MTOK` from OpenAI's pricing page (as env vars locally, or
repository variables for the Action); otherwise the report shows tokens only.

## Development

```bash
uv run pytest                 # offline tests: validation, scoring, dataset integrity, mocked API
uv run ruff check . && uv run ruff format --check .
```

## Stack

Python 3.12, [uv](https://docs.astral.sh/uv/), Pydantic, the OpenAI Python SDK
(Responses API, GPT-5.5), pytest, reportlab (synthetic invoices). Coming next: LangGraph, Supabase
(Postgres + pgvector), FastAPI, Next.js on Vercel, Langfuse.
