# Demo walkthrough script (3–5 minutes)

Record this after running `uv run tallyhawk demo load` against your demo database and
deploying the web app. Replace the demo video URL in the root README when published.

## Setup before recording

1. Backend running with seeded procurement data and demo invoices loaded.
2. Web app signed in with your workspace password.
3. Browser zoom 100%, light or dark theme — pick one and keep it.

## Beat 1 — Overview (45s)

1. Land on **Overview** (`/dashboard`).
2. Point out KPI cards: needs review, supplier follow-up, processing, approved, failed.
3. Say: counts come from real uploads, not mock AR/AP totals.
4. Scroll to **Needs your attention** and **Recent supplier bills**.

## Beat 2 — Inbox (30s)

1. Open **Inbox**, show drag-and-drop upload (optional: upload one small PDF if time).
2. Mention: extraction and three-way match run on the server; large files use the API directly.

## Beat 3 — Exception review (90s)

1. Open **My Tasks** and pick the short-delivery case (`inv_007` if you used the default demo set).
2. Open the bill detail: PDF on the left, extracted fields on the right.
3. Show **Matching**: quantity received vs billed.
4. Show the **draft supplier email** (follow-up is recorded; email is not sent automatically).
5. Explain: approve / reject / send query are audited; approval is not payment.

## Beat 4 — Clean approve path (45s)

1. Open an **approved** bill from the demo set (`inv_001`).
2. Briefly show empty or minimal exception list and approved status on Overview.

## Beat 5 — Portfolio numbers (30s)

1. Switch to the GitHub README or [docs/EVAL_SNAPSHOT.md](EVAL_SNAPSHOT.md).
2. Mention standard-set extraction accuracy, zero silent errors on standard invoices, and matching eval with zero false approvals on the rules baseline.

## Closing line

"TallyHawk keeps the payment decision deterministic and uses AI only to read documents, find missing POs, and draft supplier queries."

## Sharing with reviewers (hiring managers)

1. **Public demo video** — Link from the root README (best when the Render API is cold or you want zero friction).
2. **Live app magic link** — Set `WEB_DEMO_TOKEN` on Vercel (`openssl rand -hex 32`). Send privately:

   `https://tally-hawk.vercel.app/login?token=<WEB_DEMO_TOKEN>`

   The link signs the visitor in and starts the in-app **Product tour** (Overview → My Tasks → sample bill **Matching** tab for three-way PO/receipt checks). If My Tasks is empty, the tour stops with a note to run `demo load`. Do not commit the token or paste the full URL in the public README. Rotate the env var if the link leaks.

3. **Backup** — Plain site URL plus `WEB_PASSWORD` for people who already have credentials.

Remind viewers that demo data comes from `uv run tallyhawk demo load`, that **approval is recorded—not payment**, and that on Render’s free tier the API may take ~30s to wake up (refresh Overview or use the video first).
