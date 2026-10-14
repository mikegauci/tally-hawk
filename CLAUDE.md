# TallyHawk

AI invoice and purchase-order agent for SMB finance teams (accounts payable on Xero or
QuickBooks; bookkeeping firms are the SaaS angle). A user uploads a supplier invoice;
an OpenAI model (GPT-5.5) extracts structured fields with confidence scores, deterministic rules validate
them, and an agent does a three-way match (purchase order, goods receipt, invoice) and
decides: auto-approve, flag for human review, or draft a query to the vendor. Reviewer
corrections become eval data.

This is also a portfolio project: eval numbers, cost per invoice and clear architecture
matter as much as features.

## Build plan

1. **Extraction + eval set** (done in this repo): Python package `tallyhawk`, GPT-5.5 reads
   PDFs natively via structured outputs, validation rules, 50 synthetic invoices with
   ground truth, eval harness with per-field accuracy.
2. **PO matching agent** (done in this repo): seeded Supabase DB of vendors, POs and goods receipts; LangGraph
   workflow (extract → validate → match → decide → human handoff) using OpenAI tool calling;
   pgvector for fuzzy vendor matching; matching evals.
3. **Web app**: FastAPI service (Railway/Render) + Next.js/Tailwind on Vercel with upload,
   review queue (PDF beside extracted fields) and dashboard; Supabase auth and storage.
4. **Portfolio polish**: README with architecture diagram, accuracy and cost numbers,
   Langfuse tracing, demo video.

## Layout

- `src/tallyhawk/schema.py`: Pydantic models. `ExtractedInvoice` is the structured-output
  schema sent to the model, so field descriptions are part of the prompt.
- `src/tallyhawk/extract.py`: `extract_invoice` / `extract_file`. One OpenAI
  `responses.parse` call with the PDF as an `input_file` part; handles refusals and
  incomplete responses; reports tokens and cost.
- `src/tallyhawk/validation.py`: arithmetic and sanity checks; `needs_review` routes an
  invoice to a human on any error-level issue or any field below the confidence threshold.
- `src/tallyhawk/procurement.py`: vendor, PO, goods receipt and posted-invoice models; the
  `ProcurementStore` interface and `InMemoryStore` (seed JSON). Supabase implements the same
  interface later.
- `src/tallyhawk/matching.py`: deterministic three-way match, tolerances, issue routes
  (`review` vs `vendor`) and `decide`.
- `src/tallyhawk/agent.py`: OpenAI tool-calling loop (Responses API, `store=False`) that finds
  a PO when the invoice quotes none or an unknown one.
- `src/tallyhawk/drafting.py`: supplier query emails (LLM or template).
- `src/tallyhawk/workflow.py`: LangGraph graph `check → lookup → [investigate] → match →
  decide → [draft_query] → handoff`; `interrupt` at handoff when a checkpointer is set.
- `src/tallyhawk/cli.py`: `uv run tallyhawk extract invoice.pdf`, `uv run tallyhawk match invoice.pdf|label.json`.
- `evals/generate.py`: deterministic generator for `evals/data/` (PDFs + labels). Labels
  hold the values *printed* on the invoice, including deliberate supplier mistakes.
- `evals/scoring.py`, `evals/run_eval.py`: scoring and the eval runner/report.
- `evals/generate_matching.py`: deterministic seed (`evals/data/procurement/`) and matching
  labels (`evals/data/match_labels.json`), one scenario per invoice. `evals/run_match_eval.py`
  scores decisions; `evals/test_live_match_eval.py` is the paid version.
- `tests/`: offline tests (mocked API). `evals/test_live_eval.py` is the paid eval,
  marked `live`.

## Commands

```bash
uv sync                                   # install
uv run pytest                             # offline tests (no API calls)
uv run ruff check . && uv run ruff format --check .
uv run python -m evals.generate           # regenerate the eval set (deterministic)
uv run python -m evals.run_eval --limit 5 # eval smoke run (needs OPENAI_API_KEY)
uv run python -m evals.generate_matching  # regenerate matching seed + labels (deterministic)
uv run python -m evals.run_match_eval --resolver rules --drafter template  # free matching baseline
uv run python -m evals.run_match_eval     # matching eval with the agent (needs OPENAI_API_KEY)
uv run pytest -m live -s                  # full eval with pass/fail thresholds
```

## Conventions

- LLM provider is OpenAI (Mike's choice, 2026-10-14). Default model `gpt-5.5` at reasoning
  effort `medium` (override with `TALLYHAWK_MODEL`, `TALLYHAWK_EFFORT` or CLI flags). Cost is
  reported only when `TALLYHAWK_PRICE_INPUT_PER_MTOK` / `TALLYHAWK_PRICE_OUTPUT_PER_MTOK` are set.
- Extract what is printed; never "fix" a supplier's arithmetic in extraction. Validation
  is where mismatches are caught.
- Any change to the prompt, schema or model should come with a before/after eval run.
- If you change `evals/generate.py` or `evals/generate_matching.py`, regenerate the data and
  commit it; `tests/test_dataset.py` and `tests/test_matching_dataset.py` check the committed
  data matches the generators.
- Approve / review / query decisions stay deterministic; the LLM finds missing POs and drafts
  emails only. A PO the agent found always goes to review. Agent effort defaults to `low`
  (`TALLYHAWK_AGENT_EFFORT`).
- PR titles say specifically what the PR does: no "Step N" prefix and no branch names.
- Mike is new to finance terms; explain AP jargon (PO, goods receipt, three-way match)
  plainly in docs and UI.
