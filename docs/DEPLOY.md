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
| `SESSION_SECRET` | `openssl rand -hex 32` |
| `WEB_REVIEWER_NAME` | Optional |

3. Deploy. Production web URL: **https://tally-hawk.vercel.app** (set `TALLYHAWK_CORS_ORIGINS` on Render to this origin).
4. Sign in, verify **Overview** shows demo counts after `demo load` and a live API.

Until Render is live, set `TALLYHAWK_API_URL` on Vercel to your API origin (default placeholder: `https://tallyhawk-api.onrender.com`).

## 4. Security checklist

- Rotate `TALLYHAWK_API_KEY` and `SESSION_SECRET` if leaked.
- Rate-limit `/api/session` at the edge (Vercel firewall or similar) before broad exposure.
- Use separate preview credentials/backends if preview deployments must not touch production data.

## 5. Reset demo data

```bash
uv run tallyhawk db seed
uv run tallyhawk demo load
```

Or truncate `invoices` and related tables in Supabase SQL editor, then `demo load` again.
