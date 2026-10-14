# TallyHawk web app

Next.js App Router, TypeScript, Tailwind v4, shadcn/ui (Base UI primitives), Lucide,
and TanStack Table. The visual specification is preserved in `DESIGN_SYSTEM.md`.

## Run locally

From the repository root, start the existing FastAPI service with the root `.env`
loaded into its environment. Uvicorn does not load that file automatically:

```sh
uv run uvicorn tallyhawk.api:app --env-file .env --reload
```

In another terminal:

```sh
cd web
npm ci
cp .env.example .env.local
# Fill the four required values described below.
npm run dev
```

Visit http://localhost:3000. No database keys or OpenAI keys belong in the web app.
Do not expose the local API publicly without `TALLYHAWK_API_KEY`.

| Variable | Value |
| --- | --- |
| `TALLYHAWK_API_URL` | Local API URL or the deployed HTTPS API origin |
| `TALLYHAWK_API_KEY` | Same bearer token as the backend |
| `WEB_PASSWORD` | A strong, unique workspace sign-in password |
| `WEB_DEMO_TOKEN` | Optional; enables `/login?token=…` magic links for portfolio reviewers (see [docs/DEMO.md](../docs/DEMO.md)) |
| `SESSION_SECRET` | Random secret, e.g. `openssl rand -hex 32` |
| `WEB_REVIEWER_NAME` | Optional shared identity recorded with reviews |

All four required values must exist before sign-in is enabled. Sessions are signed,
HTTP-only, SameSite Strict, secure in production, and expire after eight hours.
Writes check the request origin. The Next.js server forwards only allowlisted API
routes and adds the backend key; the browser never receives that key. Review identity
is assigned by the server, not accepted from the browser. Rotate `SESSION_SECRET`
to revoke all active sessions. Apply a hosting-layer rate limit to `/api/session`
before exposing sign-in broadly.

This is a **single trusted workspace**, with a shared reviewer role. It does not
implement individual user accounts, tenant isolation or role-based approval policies.
Do not reuse one deployment/backend for unrelated customers. Individual auth and
server-side tenant/role enforcement are a follow-on project.

## Deploy the two parts

The frontend and the existing Python API are separate deployments. The database and
private document storage remain on the backend's existing infrastructure.

### 1. Host the API on Render

1. Push this repository to GitHub. In Render choose **New → Web Service**, connect
   the repository, use its root directory and select **Docker**. The existing root
   `Dockerfile` is the build definition.
2. Copy `DATABASE_URL`, `OPENAI_API_KEY`, `TALLYHAWK_API_KEY`, `SUPABASE_URL`, and
   `SUPABASE_SERVICE_ROLE_KEY` from your local root `.env` into Render's secret
   environment settings. Never commit the file. Use the private storage integration;
   local container storage is temporary.
3. Set health-check path `/health`. Run `tallyhawk db migrate` as the pre-deploy
   command (available on paid Render services), or run migrations once from your
   local environment before the first deploy. Do not seed synthetic invoices into
   a real workspace.
4. Keep the Dockerfile's start command. Choose a plan in Render's UI; no paid
   resources are provisioned by this repository. Free services sleep when idle and
   are suitable for a demo, not reliable background processing.
5. Deploy, verify `/health`, and copy its HTTPS service origin, for example
   `https://YOUR-SERVICE.onrender.com`.

The current backend uses in-process FastAPI background tasks. A restart can interrupt
processing. For production volume, move processing to durable jobs before scaling.
The UI exposes retry for failed processing; stuck `processing` records need backend
recovery rather than a claim that the upload finished successfully.

References: [Render Docker](https://render.com/docs/docker),
[web services](https://render.com/docs/web-services),
[pre-deploy commands](https://render.com/docs/deploys).

### 2. Host the web app on Vercel

1. Import the same GitHub repository. Set **Root Directory** to `web` and framework
   to **Next.js**. Build command is `npm run build`; use the default output directory.
2. Add the five environment variables listed above. `TALLYHAWK_API_URL` is the Render
   origin, and `TALLYHAWK_API_KEY` must match Render. Generate a new session secret
   and choose a workspace password. Use separate preview credentials/backends if
   previews should not access production invoices.
3. Deploy. Sign in, upload a test supplier invoice, wait for processing, then open
   **My Tasks** to review exceptions. Never use a real bill for an unapproved test
   that could reach the backend's existing automatic approval rules.

The web upload limit is **4,000,000 bytes**, below Vercel's 4.5 MB request limit with
multipart overhead. The backend still accepts 20 MB directly. Supporting larger web
uploads needs a signed direct-storage upload flow. See
[Vercel function limits](https://vercel.com/docs/functions/limitations).

## Demo dataset

After the API database is migrated and seeded (`uv run tallyhawk db migrate && uv run tallyhawk db seed`
from the repo root), load five curated eval invoices through the real pipeline:

```sh
uv run tallyhawk demo load
```

Requires `DATABASE_URL`, `OPENAI_API_KEY`, and local `TALLYHAWK_STORAGE_DIR` or Supabase storage
vars. Expect roughly **$0.15–0.50** in OpenAI usage for the default set. See [docs/DEPLOY.md](../docs/DEPLOY.md).

## Implemented behavior

- `/dashboard`: AP overview — status KPIs, attention list, recent bills (no fabricated AR metrics).
- `/inbox`: multi-file upload, drag/drop, type/size validation, per-file errors,
  explicit retry, processing polling, received documents.
- `/tasks`: actual review queue, supplier/document search, sorting, 20-row pagination.
- `/payables/bills`: uploaded documents, workflow filter, search and pagination.
- `/payables/bills/[billId]`: protected source PDF/image beside extracted values,
  editable headers/lines, original-value evidence, PO and receipt comparison,
  backend exception explanations, draft supplier email, and review history.
- Confirmation dialogs for approval, rejection, follow-up and corrections. Dirty
  edits block decisions until saved/rechecked, and navigation warns about them.
- Failed/empty/loading states, responsive mobile document/data switching, keyboard
  accessible shadcn tabs and dialogs, persistent desktop sidebar collapse.
- First-visit **Product tour** (driver.js) on Overview; replay from the sidebar. Magic-link
  sign-in (`WEB_DEMO_TOKEN`) redirects to `/dashboard?tour=1`.

No payment, sending, or unsupported AR capability is implied. `send_query` records
supplier follow-up; it does **not** send email. The backend can automatically approve
clean matches, including after corrections; this is explicitly explained in the UI.
Approval does not equal payment. The current backend allows exception overrides, so
the UI requires a reason before approving flagged invoices. This UI constraint is
not a replacement for a future server-side approval policy.

The API exposes a combined workflow state. It is labelled as such; payment and
matching are not fabricated from it. Counts come from real records. Monetary values
are formatted with ISO currency codes; the web app does not sum currencies or perform
financial calculations. Corrections are revalidated by the backend. Model-reported
confidence percentages are omitted because they are not calibrated field scores.
The API has no source bounding boxes, so the UI offers side-by-side source comparison.

## Validation

```sh
npm run typecheck
npm run lint
npm run build
npm test
```

Browser tests use a separate mock API on port 8109 and a Next dev server on 3109.
They never call OpenAI or a real database. Tests use installed Google Chrome by
default. In CI set `PLAYWRIGHT_CHANNEL=chromium` and install it with
`npx playwright install --with-deps chromium`. Coverage includes the auth boundary,
cross-origin protection, upload validation, queue search, reviewer confirmation,
correction evidence, errors, and mobile/desktop layout.
