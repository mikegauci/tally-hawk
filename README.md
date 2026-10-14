# TallyHawk

**AI invoice processing for small finance teams.** TallyHawk reads supplier invoices,
pulls out the data an accounts payable clerk would type in by hand, checks that the
numbers add up, and matches each invoice against its purchase order and goods receipt so
only the problem invoices reach a person.

> Status: steps 1 and 2 of 4 are done (extraction, PO matching agent, and evals for both),
> and the backend for step 3 (Postgres schema and HTTP API) is in. See
> [the build plan](CLAUDE.md#build-plan).

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

## What step 2 does: the PO matching agent

Before paying an invoice, finance checks three documents agree. This is a **three-way match**:

- the **purchase order (PO)**: what the company agreed to buy, how many, at what price;
- the **goods receipt**: what the warehouse actually received (it can arrive in batches);
- the **invoice**: what the supplier is billing.

TallyHawk runs that check as a [LangGraph](https://langchain-ai.github.io/langgraph/) workflow:

```
check ─► lookup ─┬───────────────► match ─► decide ─┬─► approve
                 └─► investigate ─►                 ├─► draft supplier email ─► person
                    (OpenAI agent,                  └─► person (review)
                     only if no PO found)
```

| Node | What it does | LLM? |
|---|---|---|
| check | Step 1's validation errors and low-confidence fields become issues | no |
| lookup | Finds the supplier by tax ID or fuzzy name, and the PO by the number printed on the invoice | no |
| investigate | When the invoice quotes no PO, or one that isn't on file, an agent with tools (`search_vendors`, `list_purchase_orders`, `get_purchase_order`) looks for the right PO and submits it or "none" | yes, OpenAI tool calling |
| match | Pairs invoice lines with PO lines and checks prices (1% tolerance), quantities ordered and quantities received, plus duplicates, currency and supplier | no |
| decide | **approve**, **review** (a person must look) or **vendor_query** (the supplier must fix something) | no |
| draft_query | Writes the email to the supplier, quoting the invoice, PO and each problem | yes (or a template) |
| handoff | Queues the case for a person; with a checkpointer it pauses (`interrupt`) until a reviewer resumes it | no |

Design choices:

- **The money decision is deterministic.** Rules decide approve / review / query so every
  outcome can be audited; the LLM only searches for a missing PO and writes emails.
- **The agent runs only when the simple lookup fails** (9 of the 50 eval invoices), which
  keeps cost and latency down, and its answer is checked against the database: a PO it
  invents is ignored, and a PO it finds always goes to a person to confirm.
- **The data layer is an interface** (`ProcurementStore`). It runs on the in-memory JSON
  seed data or on Supabase/Postgres (`PostgresStore`) without changing the workflow, and all
  50 matching eval cases give identical outcomes on both (`tests/test_db.py`).

## Quick start

```bash
uv sync
cp .env.example .env   # add your OPENAI_API_KEY; the CLI and eval read .env automatically
uv run tallyhawk extract evals/data/invoices/inv_001.pdf
```

Match an invoice against the seeded POs and receipts. This one costs nothing because it
starts from known invoice data and uses the rules-only path:

```bash
uv run tallyhawk match evals/data/labels/inv_007.json --resolver rules --drafter template
```

It returns `vendor_query`, because 24 pairs of safety boots were billed but only 19
arrived, with a drafted email to the supplier saying so. Drop the two flags (and pass a
PDF) to run extraction, the agent and the LLM drafter.

Extraction output (abridged and illustrative; real numbers come from the eval run):

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

`evals/data/` holds 68 synthetic invoices with known answers, generated deterministically
by `evals/generate.py`: 50 standard ones and 18 deliberately hard ones. The standard set
varies on purpose:

| Variation | Why it's hard |
|---|---|
| 5 layouts (classic, US, European, compact, multi-page) | Labels and positions move around |
| European formatting (`1.234,56 €`, `11.08.2026`) | Decimal commas and day-first dates |
| Multi-page invoices with 40–55 lines | Long tables split across pages |
| Missing PO number, due date, tax ID or tax rate | Model must return null, not guess |
| Buyer's tax ID printed next to the supplier's | Easy to grab the wrong one |
| 4 invoices with the supplier's own maths wrong | Extraction must copy, validation must catch |

GPT-5.5 scored 100% on every field of the standard set, so the **hard set** (tagged `hard`)
is there to find where it breaks, and whether its confidence scores drop when it does:

| Hard case | Count | What it tests |
|---|---|---|
| Scanned sideways (`scanned_rotated`) | 2 | Page image rotated 90°, no text layer |
| Crooked, noisy scan (`scanned_skewed`) | 3 | 1.5–3.5° skew, speckle, blur |
| Fax quality (`low_res`) | 3 | 62–78 dpi JPEG, one thresholded to black and white |
| Handwritten PO (`handwritten_po`) | 2 | The PO number is only written by hand |
| Handwritten note (`handwritten_note`) | 1 | A buyer's "part paid" scribble that is not invoice data |
| Two-column layout (`two_column`) | 3 | Details and totals in a sidebar, SKUs, wrapped descriptions, a customer account number as a distractor |
| Deposit paid (`deposit_paid`) | 1 | Invoice total vs a smaller "balance due" (the label is the invoice total) |
| Two VAT rates (`mixed_tax_rates`) | 1 | No single tax rate, so `tax_rate` must be null |
| Dual currency (`dual_currency`) | 1 | USD invoice with a bold EUR equivalent |
| PAID stamp (`paid_stamp`) | 1 | A red stamp over the totals |

Scanned pages are drawn as images (no text layer), so the model has to read pixels, as it
would with a real scan or phone photo.

Run it:

```bash
uv run python -m evals.run_eval              # all 68 invoices
uv run python -m evals.run_eval --tag hard   # only the 18 hard ones
uv run python -m evals.run_eval --limit 5    # smoke test
uv run python -m evals.run_eval --rescore evals/results/<run>   # re-score (and re-price) a saved run
```

The report (`evals/results/<run>/report.md`) covers:

- **Standard vs hard**: the headline numbers for each set side by side.
- **Per-field accuracy** for every header field, plus line-item accuracy.
- **Document accuracy**: share of invoices with every field right.
- **Silent error rate**: invoices with a wrong field that were *not* sent to review. This
  is the number that matters for automation.
- **Confidence calibration**: accuracy per confidence band, and mean confidence on right
  vs wrong fields. If wrong fields still score 0.95+, confidence can't be used for routing.
- **Validation issue detection**: supplier errors caught, missed and false alarms.
- **Accuracy by tag**: document accuracy, review rate and silent errors per kind of invoice.
- **Cost per invoice** and latency.

`uv run pytest -m live` runs the same eval with pass/fail thresholds on the standard set
(the hard set is reported, not gated), and the **Extraction eval** GitHub Action runs it
on demand (add an `OPENAI_API_KEY` secret). Cost per invoice comes from
`TALLYHAWK_PRICE_INPUT_PER_MTOK` and `TALLYHAWK_PRICE_OUTPUT_PER_MTOK` (USD per million
tokens): `.env.example` has gpt-5.5's list prices, and the Action reads repository
variables of the same names. Without them the report shows tokens only.

## Matching evaluation

`evals/generate_matching.py` seeds suppliers, POs, goods receipts and already-paid
invoices around the 50 standard extraction invoices (not the hard set), giving each a scenario with a known right answer
(`evals/data/match_labels.json`). The invoices stay unchanged; the scenario is built on the
buyer's side:

| Scenario | Invoices | Right decision |
|---|---|---|
| Clean match (supplier names often spelled differently on file) | 8 | approve |
| Price a fraction of a percent over the PO | 3 | approve |
| Goods delivered in two batches | 3 | approve |
| Supplier's own arithmetic wrong | 4 | vendor_query |
| Price 5 to 12% over the PO | 4 | vendor_query |
| Fewer units received than billed | 4 | vendor_query |
| Line billed that isn't on the PO | 3 | vendor_query |
| No PO quoted, and none of the supplier's POs match | 4 | vendor_query |
| No PO quoted, but a matching open PO exists | 6 | review (agent must find it) |
| PO number has a typo | 3 | review (agent must find it) |
| Already paid (duplicate) | 2 | review |
| PO raised with a different supplier | 2 | review |
| Goods not received yet | 2 | review |
| Unknown supplier | 1 | review |
| PO in a different currency | 1 | review |

```bash
uv run python -m evals.run_match_eval --resolver rules --drafter template  # free baseline
uv run python -m evals.run_match_eval                                      # with the agent
uv run python -m evals.run_match_eval --from-run evals/results/<extraction run>  # end to end
```

The report covers decision accuracy, a decision confusion table, **false approvals**
(invoices paid that should have been stopped, the number that matters most), supplier and
PO accuracy, issue-code precision and recall, per-scenario accuracy, how often the agent
ran, and LLM calls, tokens and cost per invoice.

Rules-only baseline (no API calls): **82% decision accuracy, 0 false approvals**. The 9
misses are exactly the missing-PO and PO-typo invoices, which it sends back to the
supplier instead of finding the PO; that gap is what the agent is for. The live agent
numbers come from the **Matching eval** GitHub Action or `uv run pytest -m live -s
evals/test_live_match_eval.py`.

## The backend: database and API

The API the web app will call. It stores each uploaded invoice, runs extraction and
matching, and keeps everything a reviewer needs: what the model read, how sure it was, the
match result, and what the reviewer decided.

```
upload ─► invoices (file in Supabase Storage) ─► extractions ─► match_results ─┬─► approved ─► posted_invoices
                                                                              └─► review_queue ─► reviews
```

**Schema** (`supabase/migrations/`, plain SQL so the Supabase CLI can apply it too):

| Table | What it holds |
|---|---|
| `vendors` | Suppliers: name, tax ID, email |
| `purchase_orders`, `po_lines` | What was ordered, from whom, at what price |
| `goods_receipts`, `goods_receipt_lines` | What actually arrived against each PO |
| `posted_invoices` | Invoices already in the accounts, so a resubmitted copy is caught as a duplicate. Every invoice TallyHawk approves is added here |
| `invoices` | Each upload, its file and its status (`uploaded` → `processing` → `approved` / `awaiting_review` / `failed`; a reviewer then moves it to `approved`, `rejected` or `vendor_queried`) |
| `extractions` | What the model read, with confidence scores, tokens and cost |
| `match_results` | The three-way match outcome: decision, issues per line, drafted supplier email |
| `reviews` | What a person decided, and any fields they corrected (future eval data) |
| `review_queue` (view) | Invoices waiting for a person, with their latest match |

Row level security is on for every table with no policies yet, so Supabase's public keys
can't read anything; the API connects with the database password. Policies for signed-in
users come with the web app.

**Endpoints** (interactive docs at `/docs`; send `Authorization: Bearer $TALLYHAWK_API_KEY`):

| Method | Path | Does |
|---|---|---|
| `POST` | `/invoices` | Upload a PDF or image; extraction and matching start in the background |
| `POST` | `/invoices/{id}/process` | Run (or re-run) extraction and matching and wait for the result |
| `GET` | `/invoices?status=` | List invoices |
| `GET` | `/invoices/{id}` | Latest extraction, match outcome and review history |
| `GET` | `/invoices/{id}/file` | The original file, to show beside the extracted fields |
| `GET` | `/review-queue` | Invoices waiting for a person, oldest first |
| `POST` | `/invoices/{id}/review` | `approve`, `reject`, `send_query` (supplier must fix something), or `correct` misread fields and match again |

Run it locally against any Postgres 15+:

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tallyhawk OPENAI_API_KEY=...
uv run tallyhawk db migrate      # create the tables
uv run tallyhawk db seed         # load the 62 synthetic suppliers, 79 POs and their goods receipts
uv run uvicorn tallyhawk.api:app --reload
curl -F file=@evals/data/invoices/inv_001.pdf localhost:8000/invoices
```

For Supabase, set `DATABASE_URL` to the project's pooler connection string and add
`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` so files go to the private `invoices`
storage bucket. The `Dockerfile` builds the API for Railway or Render; run
`tallyhawk db migrate` as the pre-deploy step.

## Development

```bash
uv run pytest                 # offline tests: validation, matching, datasets, mocked OpenAI API
# database and API tests too (each run creates and drops its own database; CI runs these)
TALLYHAWK_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Stack

Python 3.12, [uv](https://docs.astral.sh/uv/), Pydantic, the OpenAI Python SDK
(Responses API with structured outputs and tool calling, GPT-5.5), LangGraph, pytest,
reportlab (synthetic invoices), FastAPI, Postgres / Supabase (psycopg 3), Docker. Coming
next: Next.js on Vercel, Supabase auth, Langfuse.
