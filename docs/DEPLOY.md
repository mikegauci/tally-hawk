# Deploy TallyHawk (demo / portfolio)

Stack: **Render** (FastAPI Docker), **Supabase** (Postgres + Storage), **Vercel** (Next.js).

## 1. Supabase

1. Create a project (demo-only; do not mix real customer data with eval seeds).
2. **Database → Connection string → URI** (pooler, transaction mode) → `DATABASE_URL`.
3. Copy **Project URL** and **service role key** (server-side only) for storage.
4. From your machine:

```bash
export DATABASE_URL='postgresql://...'
uv run tallyhawk db migrate
uv run tallyhawk db seed          # synthetic vendors/POs for demo
uv run tallyhawk demo load        # uploads 5 eval PDFs; needs OPENAI_API_KEY
```

Storage bucket `invoices` is created by migrations when applied via Supabase CLI or `db migrate`.

## 2. Render (API)

Use the repo [`render.yaml`](../render.yaml) blueprint (**New → Blueprint** in Render) or:

1. **New → Web Service**, connect GitHub, repo root, **Docker**.
2. Environment (secrets):

| Variable | Notes |
| --- | --- |
| `DATABASE_URL` | Supabase pooler URI |
| `OPENAI_API_KEY` | Extraction + agent + drafter |
| `TALLYHAWK_API_KEY` | Long random bearer token |
| `SUPABASE_URL` | `https://<ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Never expose to the browser |
| `TALLYHAWK_CORS_ORIGINS` | `https://your-app.vercel.app` |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Optional tracing |
| `TALLYHAWK_DEMO_SESSION_LIMIT` / `TALLYHAWK_DEMO_DAILY_LIMIT` | Public demo caps, e.g. `10` / `50` (off when unset) |

3. Health check path: `/health`.
4. Pre-deploy (paid): `tallyhawk db migrate`. Free tier: run migrate locally before deploy.
5. After deploy: run `demo load` from your laptop against the same `DATABASE_URL` if Render cannot reach your PDF paths (recommended).

**Limitation:** processing uses in-process background tasks; restarts can interrupt work. Retry failed items from the UI.

## 3. Vercel (web)

1. Import repo, **Root Directory** `web`, framework Next.js.
2. Environment:

| Variable | Notes |
| --- | --- |
| `TALLYHAWK_API_URL` | Render HTTPS origin, no trailing slash |
| `TALLYHAWK_API_KEY` | Same as Render |
| `WEB_PASSWORD` | Workspace sign-in password |
| `WEB_DEMO_TOKEN` | Optional; `openssl rand -hex 32` for recruiter magic links (`/login?token=…`) |
| `SESSION_SECRET` | `openssl rand -hex 32` |
| `WEB_REVIEWER_NAME` | Optional |
| `NEXT_PUBLIC_DEMO_VIDEO_URL` | Optional; linked when a reviewer hits a demo cap |

3. Deploy. Production web URL: **https://tally-hawk.vercel.app** (set `TALLYHAWK_CORS_ORIGINS` on Render to this origin).
4. Sign in, verify **Overview** shows demo counts after `demo load` and a live API.

Until Render is live, set `TALLYHAWK_API_URL` on Vercel to your API origin (default placeholder: `https://tallyhawk-api.onrender.com`).

## 4. Bounding OpenAI spend

The live demo spends real money on every invoice (about $0.038 each). Three layers keep a
forwarded magic link from becoming a large bill:

1. **Per visit:** `TALLYHAWK_DEMO_SESSION_LIMIT=10` uploads per signed browser session.
2. **Per day:** `TALLYHAWK_DEMO_DAILY_LIMIT=50` uploads across all visitors (UTC day). This
   is the real backstop, since signing in again starts a new session.
3. **Per month:** give the API key its own OpenAI project with a monthly budget (e.g. $20).
   When the budget runs out, OpenAI answers `insufficient_quota`, and the app shows a
   "demo budget used up" message instead of a generic failure.

Visitors who hit a cap see a friendly message (with the demo video link when
`NEXT_PUBLIC_DEMO_VIDEO_URL` is set). Counts live in the `demo_usage` table.

## 5. Security checklist

- Rotate `TALLYHAWK_API_KEY`, `SESSION_SECRET`, and `WEB_DEMO_TOKEN` if leaked.
- Rate-limit `/api/session` at the edge (Vercel firewall or similar) before broad exposure.
- Use separate preview credentials/backends if preview deployments must not touch production data.

## 6. Reset demo data

Visitors approve, reject and upload invoices, so the demo is put back to its curated state
every night at 03:00 UTC by the **Demo reset** GitHub Action
(`.github/workflows/demo-reset.yml`). It runs `tallyhawk demo reset`, which:

- deletes every invoice in the database and its stored file, then restores the five
  curated demo invoices from `demo/snapshot.json`, timestamps moved up to now;
- clears the upload counters (`demo_usage`), so the daily cap starts fresh;
- makes **no OpenAI calls** and leaves the procurement seed (vendors, POs, receipts) alone.

Setup: add `DATABASE_URL`, `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` as repository
secrets (Settings → Secrets and variables → Actions). Until they are set, the job logs a
warning and does nothing. Run it by hand from the Actions tab (**Run workflow**) after
setup to check it works.

Refresh the snapshot whenever the prompt, schema or model changes, against a database
holding only the demo load:

```bash
uv run tallyhawk demo load       # paid: five invoices through OpenAI (about $0.09)
uv run tallyhawk demo snapshot   # writes demo/snapshot.json; commit it
```
