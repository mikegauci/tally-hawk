# Invoice AI — Design System

> **Version:** 1.0  
> **Status:** Approved design direction / implementation specification  
> **Updated:** 2026-10-14  
> **Product:** AI Invoice & Purchase Order Agent  
> **Audience:** Designers, frontend engineers, AI engineers, and coding assistants  
> **Stack:** Next.js + React + TypeScript + Tailwind CSS v4 + shadcn/ui + Lucide + TanStack Table

## 1. Purpose and scope

Build a polished **B2B finance operations SaaS** with two connected but distinct workflows:

- **Accounts Payable (AP):** Manage purchase orders (POs), receive supplier bills, extract invoice data with AI, match invoice line items to POs, resolve exceptions, approve bills, and record payment outcomes.
- **Accounts Receivable (AR):** Manage customers, create and issue customer invoices (optionally from customer POs), track due dates and settlements, send reminders, and manage collections.

Both workflows belong to **one workspace**, share a design system, and appear together in high-level dashboards and tasks. Do not pretend AP and AR documents or accounting states are identical.

**Product positioning:** Modern, credible enterprise fintech with AI assistance. The UI must look usable in a real finance department, not like a generic AI chatbot or a flashy crypto dashboard.

**Non-goals for the first release:** A full general ledger, ERP replacement, bank reconciliation engine, payment processor, tax filing system, or autonomous payment executor. Display only actions backed by real capabilities; otherwise mark them as *coming later* or omit them.

### Design principles

1. **Clarity over decoration.** Data, hierarchy, and actions matter more than illustrations.
2. **One workspace, two distinct workflows.** Navigation and language always clarify direction of money.
3. **AI is explainable.** Every extraction, recommendation, or discrepancy can be inspected and corrected.
4. **Humans authorize financial decisions.** AI may draft, suggest, compare, and prepare, but does not silently approve, issue, email, or pay.
5. **Money is exact.** Explicit currency, localized display, deterministic calculation, no floating-point financial arithmetic.
6. **Progressive disclosure.** Show actionable summaries first; advanced settings and detailed evidence on demand.
7. **Status means something precise.** Processing, review, document lifecycle, PO matching, and payment are separate dimensions.
8. **Accessible by default.** Keyboard-first interactions, visible focus, readable contrast, semantic controls.

---

## 2. Visual identity

**Working name:** `Invoice AI` (renameable; keep branding tokens independent from product copy).

**Style:** Restrained fintech minimalism. Light, airy surfaces; cool-gray navigation; crisp dark text; a confident blue action color; muted semantic highlights. AI gets a subtle violet accent only where truly relevant.

**Avoid:** Heavy gradients, glassmorphism, neon colors, saturated status badges, oversized charts, glowing AI orbs, purple everywhere, overly rounded controls, excessive shadows, and decorative badges on all components.

### Color palette — light theme

| Semantic role | Hex | Usage |
|---|---|---|
| Primary | `#2563EB` | Primary CTA, selected nav, links, focus highlights |
| Primary hover | `#1D4ED8` | Hover on prominent blue actions |
| App canvas | `#F8FAFC` | Main app background |
| Surface | `#FFFFFF` | Cards, sheets, tables, inputs |
| Surface muted | `#F1F5F9` | Sidebar active states, subdued containers |
| Primary ink | `#111827` | Headers and key values |
| Secondary ink | `#475569` | Body and descriptions |
| Muted ink | `#64748B` | Helper copy, secondary metadata |
| Border | `#E2E8F0` | Dividers, table grid lines, fields |
| Success foreground | `#15803D` | Settled, confirmed, successfully matched |
| Success background | `#F0FDF4` | Muted success banners |
| Warning foreground | `#B45309` | Review needed, incomplete data |
| Warning background | `#FFFBEB` | Muted warning banners |
| Danger foreground | `#DC2626` | Errors, overdue, rejected, discrepancies |
| Danger background | `#FEF2F2` | Muted danger banners |
| AI accent | `#7C3AED` | AI analysis, sparkle icon, source provenance |
| AI background | `#F5F3FF` | Quiet AI info surfaces |

**Color rules:**

- Color must not be the only carrier of status. Always pair it with legible text and, where useful, an icon.
- Primary blue is for actions and selection, **not** for payment success.
- Use success for validated/settled, warning for attention, danger for failed/overdue/mismatch, violet for AI-driven work.
- Financial direction can be blue for AP and green for AR in charts, **but legend labels are mandatory**. Do not use those chart colors as lifecycle status codes.
- Check text/background combinations for WCAG contrast before shipping.

### Dark theme

Light is the **default**. Dark mode is supported through the same semantic tokens, not a separate component library.

| Semantic role | Dark hex |
|---|---|
| Background | `#0B1220` |
| Card / popover | `#111827` |
| Secondary surface | `#1E293B` |
| Text | `#F8FAFC` |
| Secondary text | `#CBD5E1` |
| Muted text | `#94A3B8` |
| Border | `#334155` |
| Primary | `#60A5FA` |
| Primary foreground | `#0B1220` |
| AI accent | `#C4B5FD` |

Validate dark semantic statuses separately; never reuse a pale success/warning/danger fill unmodified in dark mode.

---

## 3. Typography, spacing, and shape

### Typography

- **Font:** `Inter` for all UI elements (via `next/font/google` or locally hosted equivalent).
- **Monetary data:** `font-variant-numeric: tabular-nums`; right-aligned in tables.
- **Invoice/PO numbers:** May use tabular numerals; never truncate the sole visible document ID.

| Style | Desktop size | Weight | Line height | Typical use |
|---|---:|---:|---:|---|
| Page title | 28px | 600 | 36px | `Supplier Bills`, `Overview` |
| Section title | 20px | 600 | 28px | Large content region headings |
| Card title | 16px | 600 | 24px | Cards and drawer titles |
| Body | 14px | 400 | 20px | Tables, forms, content |
| Body emphasis | 14px | 500–600 | 20px | Field values, labels |
| Small | 12px | 400–500 | 16px | Metadata, table helper text |
| KPI value | 28–32px | 600 | 36–40px | Dashboard financial totals |

### Spacing scale

Based on 4px increments: `4, 8, 12, 16, 20, 24, 32, 40, 48, 64`.

- Page gutters: **32px desktop**, **24px tablet**, **16px mobile**.
- Page header → content gap: **24px**.
- Card internal padding: **20–24px**; compact cards: **16px**.
- Form vertical gap: **16px**; label-to-control gap: **6–8px**.
- Button/icon gap: **8px**.

### Corner radii and borders

| Token | Value | Use |
|---|---|---|
| `radius-xs` | 4px | Small inline accents |
| `radius-sm` | 6px | Badges, compact UI |
| `radius-md` | 8px | Buttons, inputs, dropdowns |
| `radius-lg` | 12px | Cards, dialog panels |
| `radius-xl` | 16px | Large panels, drawer interior regions |

Borders: **1px `border`**. Use shadows only for elevated content such as dialogs, menus, and the app bar if necessary. Prefer borders over shadows for cards.

### Icons

Use **Lucide React** only for standard product icons.

- Typical navigation icon: **18px**.
- Buttons: **16px**.
- Hero/empty state icon: **24–32px**.
- Keep icon stroke and alignment consistent; no emoji in the production UI.

---

## 4. Information architecture and routes

Use a **left navigation sidebar** with a workspace header at top and user/workspace menu at bottom. Navigation groups must remain in this order:

```text
Invoice AI [Workspace switcher]

WORKSPACE
  Overview                 /dashboard
  Inbox                    /inbox
  My Tasks                 /tasks

ACCOUNTS PAYABLE
  Supplier Bills           /payables/bills
  Purchase Orders          /payables/purchase-orders
  Suppliers                /payables/suppliers

ACCOUNTS RECEIVABLE
  Customer Invoices        /receivables/invoices
  Customers                /receivables/customers
  Collections              /receivables/collections

MANAGEMENT
  AI Activity              /ai/activity
  Reports                  /reports
  Settings                 /settings
```

### Detail and creation routes

```text
/payables/bills/[billId]
/payables/purchase-orders/new
/payables/purchase-orders/[poId]
/payables/suppliers/[supplierId]
/receivables/invoices/new
/receivables/invoices/[invoiceId]
/receivables/customers/[customerId]
/receivables/collections/[invoiceId]
/ai/activity/[runId]
```

### Navigation conventions

- Sidebar width: **240px expanded**, **64px collapsed**, with persistent desktop collapse state.
- Active item: pale primary background + blue text/icon + obvious focus indicator.
- Sidebar group labels: 11–12px uppercase/muted; navigation links: 13–14px.
- `My Tasks` and `Inbox` may display **numeric counts** for outstanding tasks/items. Counts must represent real data, not arbitrary decorations.
- Top header: breadcrumbs on details, page-specific primary action, optional global search, notifications, workspace/user controls.
- Global search includes suppliers, customers, bills, POs, and customer invoices with type labels to avoid ID collisions.
- Switching workspace changes tenant context, never silently merges company data.
- Use `Supplier Bills` for incoming AP documents and `Customer Invoices` for outgoing AR documents in UI labels. Avoid ambiguous global pages simply called `Invoices`.

### Responsive navigation

- **≥1280px:** full sidebar by default, optional collapse; multi-column finance views.
- **768–1279px:** collapsible sidebar, simplified table columns, compact KPI grid.
- **<768px:** navigation in a drawer, top-level page header, one-column forms, horizontal-scrolling or card-based table fallback.
- Do not force a three-column source-document review on small screens. Use tabs (`Document`, `Extracted Data`, `Matches`) on mobile.

---

## 5. Page templates

### 5.1 Overview (`/dashboard`)

**Purpose:** A single, trustworthy summary of AP and AR.

Desktop composition:

1. Header: `Overview`, subtitle, date filter.
2. Four KPI cards: **Outstanding Payables**, **Outstanding Receivables**, **Overdue Payables**, **Overdue Receivables**. Specify currency and whether each amount includes tax.
3. Time-series chart: AP and AR amounts by month, with visible legend and axis labels.
4. Invoice status breakdown, keeping AP and AR metrics separate or explicitly segmented.
5. Two parallel recent lists: **Recent Supplier Bills** and **Recent Customer Invoices**.
6. **Needs Your Attention** strip: pending reviews, discrepancies, overdue invoices, failed processing.

**Data rule:** Never add different currencies together without showing the conversion rate/date and that the figure is converted. For multi-currency workspaces, prefer per-currency totals.

### 5.2 Inbox (`/inbox`)

Unified entry point for uploads/imports: drag-and-drop, files and email imports (if connected), classification, processing, and routing.

- Columns: received date, document name, sender/source, suggested type, processing, owner, actions.
- Classification choices: Supplier Bill, Supplier PO, Customer PO, Other, Unknown.
- AI-proposed classification must be correctable before routing.
- Unsupported/corrupt/duplicate files show recoverable errors.

### 5.3 My Tasks (`/tasks`)

A work queue, not another document database. Each task must have reason, owner, priority, due date, related document, next action. Filter by AP/AR and task type.

Examples: `Verify extracted VAT`, `Resolve PO mismatch`, `Approve supplier bill`, `Review customer invoice before send`, `Check overdue reminder`.

### 5.4 Supplier Bills (`/payables/bills`)

- Title/subtitle + **Upload invoice** primary button.
- Tabs: `All`, `Needs review`, `Awaiting approval`, `Approved`, `Paid`; counts only from actual data.
- Filters: search, supplier, status, match result, date, amount range, owner.
- Table: checkbox, supplier, invoice number, invoice date, due date, total, **review status**, **match status**, payment indicator, row menu.
- Actions: `View`, `Review extraction`, `Resolve match`, `Submit for approval`, `Approve` (permission gated), `Record payment` (if implemented).
- Default sort: actionable items first, then due date (make user-sortable).

### 5.5 Invoice Review (`/payables/bills/[billId]`)

The product's **signature experience**. On desktop use a split workspace:

- **Left 55–60%:** PDF/image viewer with page thumbnails, zoom, search, rotation if supported, clickable source bounding boxes.
- **Right 40–45%:** structured invoice fields, extraction evidence, PO matching, AI analysis, exceptions, action footer.
- Tabs: `Overview`, `Line Items`, `Matching`, `AI Analysis`, `Activity`.
- Metadata: supplier, number, invoice date, due date, currency, net/tax/gross, PO reference, payment terms.
- Clicking an extracted field highlights the corresponding area in the original PDF when coordinates are available.
- Inline editing of extracted fields preserves **original value**, **corrected value**, **who edited**, and **timestamp**.
- Every discrepancy states **expected value**, **observed value**, **difference**, and **why it matters**.
- Human-confirmed values supersede model output, but edits remain auditable.
- Sticky footer: primary next safe action + secondary `Save changes`. Disable approval if required fields or policy blockers are unresolved.

Sample exception copy:

> **Amount differs from purchase order**  
> PO total: €2,300.00 · Supplier invoice: €2,450.00 · Difference: **+€150.00**  
> Review the invoice line items and PO before approving.

### 5.6 Purchase Orders (`/payables/purchase-orders`)

- Table: PO ID, supplier, order date, owner, total, currency, approval state, receipt state, billed amount, remaining balance.
- Creation flow: supplier → line items → tax/currency → review → submit for approval → issue.
- PO details: summary, supplier, lines, linked bills, receipts (if enabled), approvals and activity timeline.
- **Two-way matching:** Supplier bill vs approved PO.
- **Three-way matching (phase 2):** Supplier bill vs PO vs goods/service receipt, with item-level receiving. Never claim three-way match without receipt data.
- A PO can be partially billed or partially received; do not force a single simplistic status.

### 5.7 Suppliers (`/payables/suppliers`)

List and detail screens. Profile shows legal entity name, contact information, billing address, verified bank details (if implemented), tax ID, recent bills, related POs, and activity. Sensitive changes require elevated permission and logging.

### 5.8 Customer Invoices (`/receivables/invoices`)

- Title/subtitle + **Create invoice** primary button.
- Tabs: `All`, `Drafts`, `Outstanding`, `Overdue`, `Paid`, `Void`.
- Filters: customer, issue date, due date, invoice state, settlement state, currency.
- Table: invoice number, customer, issue date, due date, total, balance due, invoice state, collection status, actions.
- Row actions: `View`, `Duplicate as draft`, `Send` (if implemented), `Record payment`, `Send reminder` (if implemented), `Void` (permission gated).

### 5.9 Customer Invoice Editor (`/receivables/invoices/new`)

A structured, pleasant form: not a chat-only invoice generator.

1. **Customer:** select existing or create new.
2. **Invoice details:** number, issue date, due date, currency, customer PO reference (optional), payment terms.
3. **Line items:** description, quantity, price, tax rate, amount; keyboard friendly and dynamically expandable.
4. **Totals:** subtotal, tax breakdown, adjustments (optional), grand total.
5. **Notes / payment instructions.**
6. **Preview:** printable PDF-like rendering.
7. **Footer:** `Save draft`, `Preview`, `Issue` or `Preview & send` only if sending is integrated.

AI can suggest line items from an uploaded customer PO but the user must confirm them. Do not call this AP PO matching: it's an outgoing AR drafting aid.

### 5.10 Customers (`/receivables/customers`)

Contact and billing information, customer PO references, default currency/terms, invoice history, outstanding balance, collection activity.

### 5.11 Collections (`/receivables/collections`)

- Focus on unpaid/open receivables and follow-up actions.
- Aging buckets: `Current`, `1–30`, `31–60`, `61–90`, `90+ days overdue`.
- List: customer, oldest invoice, overdue amount, aging, last reminder, next action.
- Reminders: preview email content and select recipients before sending.
- Partial payments reduce balance due; they don't automatically mark an invoice fully paid.

### 5.12 AI Activity (`/ai/activity`)

Track each automation run: task, related document, start/end, duration, agent/model version (if available), steps, tools invoked, inputs/outputs (redacted), validation results, errors, reviewer corrections, costs when measured.

### 5.13 Reports and Settings

- **Reports:** AP aging, AR aging, spending by supplier, invoice processing time, PO mismatch rate, exception reasons, AI processing throughput. Label calculation method and reporting period.
- **Settings:** company identity and locale, currencies, users/roles, approval rules, tax display policy, document numbering, AI options, integrations, notifications, security and audit options.

---

## 6. Status taxonomy — never use one generic `status` for everything

A document may simultaneously be extracted, awaiting approval, matched to a PO, and unpaid. Model these as independent fields.

### AP supplier bill

| Field | Suggested values | Meaning |
|---|---|---|
| `processingStatus` | `received`, `processing`, `processed`, `failed` | Ingestion/extraction only |
| `reviewStatus` | `not_reviewed`, `needs_review`, `reviewed` | Human validation |
| `approvalStatus` | `not_submitted`, `pending`, `approved`, `rejected` | Authorization |
| `matchStatus` | `not_applicable`, `unmatched`, `matched`, `discrepancy` | Comparison with PO |
| `paymentStatus` | `unpaid`, `partially_paid`, `paid` | Actual settlement |

### AR customer invoice

| Field | Suggested values | Meaning |
|---|---|---|
| `invoiceStatus` | `draft`, `open`, `paid`, `void`, `uncollectible` | Document/invoice lifecycle, close to Stripe's model |
| `deliveryStatus` | `not_sent`, `sending`, `sent`, `delivery_failed` | Email/delivery only |
| `collectionStatus` | `not_due`, `due`, `overdue`, `in_followup`, `resolved` | Collections UI state |
| `amountPaid` / `balanceDue` | Money values | Partial payment truth; don't invent a sixth Stripe state |

**Critical:** `overdue` is a derived temporal condition, not necessarily an invoice lifecycle transition. `sent` is delivery metadata, not the same thing as `open`. Treat payment processor/provider states as authoritative when integrated.

### Purchase order

Track `approvalStatus`, `issueStatus`, `receiptStatus`, `billingStatus` independently. An issued PO may still be partially received, partially billed, and linked to a discrepancy.

### UI presentation

Statuses may appear as quiet, compact **status chips** in tables: pale background, text, 1 optional icon, accessible name. Avoid badges in major headings and KPI cards. Do not mix semantic warning color with AI violet.

| Semantic treatment | Examples |
|---|---|
| Success | `Matched`, `Approved`, `Paid` |
| Warning | `Needs review`, `Pending approval`, `Partially paid` |
| Danger | `Discrepancy`, `Extraction failed`, `Overdue`, `Rejected` |
| Neutral | `Draft`, `Unmatched`, `Not sent` |
| Information | `Processing`, `Open` |

---

## 7. Component library

Prefer accessible **shadcn/ui primitives** plus product-specific wrappers. Build reusable patterns rather than page-by-page one-offs.

### Global shell

- `AppShell`, `AppSidebar`, `SidebarSection`, `WorkspaceSwitcher`, `TopBar`, `Breadcrumbs`, `UserMenu`, `GlobalSearch`, `NotificationPanel`.
- `PageHeader`: breadcrumb (optional), title, subtitle, action slot.
- `SectionHeader`: label, description, actions.

### Foundation

- `Button` variants: `primary`, `secondary`, `outline`, `ghost`, `destructive`, `link`.
- `IconButton` requires an accessible label.
- `Input`, `Textarea`, `Select`, `Combobox`, `DatePicker`, `Checkbox`, `RadioGroup`, `Tabs`, `Tooltip`, `Popover`, `Dialog`, `AlertDialog`, `Sheet`, `DropdownMenu`.
- All input fields: always label, help text where needed, server/error state, disabled state, visible focus.
- Button heights: **40px default**, **36px compact**, **44px for prominent touch actions**.
- Use destructive confirmation for void/delete, permission changes, and irreversible sends when appropriate.

### Finance components

| Component | Required behavior |
|---|---|
| `Money` | Format integer minor units via locale and ISO currency; avoid JS floating point arithmetic |
| `FinancialKpiCard` | Currency, amount, period, optional delta and source context |
| `FinanceDataTable` | Filter, sort, pagination, selection, empty/loading/error states |
| `InvoiceStatusChip` | Domain + status, human-readable text |
| `DocumentNumber` | Full ID plus copy affordance |
| `LineItemsEditor` | Keyboard-editable qty/price/tax, validated totals |
| `TotalsBreakdown` | Subtotal, tax bases/rates, total, paid, due |
| `AgingSummary` | Explicit bucket boundaries and reporting date |
| `ApprovalTimeline` | Actor, event, timestamp, comment, outcome |
| `MatchComparison` | Side-by-side invoice vs PO, deltas and resolution |
| `DocumentViewer` | PDF pages, zoom, source highlights, accessible fallback |
| `DocumentUpload` | Type/size validation, progress, errors, retry |

### AI components

| Component | Required behavior |
|---|---|
| `AIInsightPanel` | Clearly marked as a suggestion or analysis, not a decision |
| `ExtractionField` | Extracted value, evidence, manual edit, optional confidence |
| `EvidenceHighlight` | Link structured field to document page/area where available |
| `ConfidenceIndicator` | Numeric score **only** if calibrated/meaningful; otherwise descriptive confidence or omit |
| `AgentRunTimeline` | Explicit start, steps, result, failures and retries |
| `ExceptionCard` | What differs, amount/field, source documents, next action |
| `HumanApprovalGate` | Clear permission, effect, and confirmation |

**AI never marks an invoice as paid, approved, or delivered simply because the model predicts it should be.**

### Component state coverage

For every interactive component test: `default`, `hover`, `focus-visible`, `active`, `disabled`, `loading`, `error`, `empty`, `success` where relevant.

---

## 8. Table and form behavior

### Data tables

- Sticky header in long tables; row hover treatment subtle.
- First column is object identity; financial figures aligned right; statuses grouped consistently.
- Search text input above table. Filters applied locally for small datasets or server-side for large datasets.
- Pagination default **20 or 25** rows; record count visible.
- Checkboxes for bulk actions only when bulk operations are safe and supported.
- A row click opens its detail page, but links, checkboxes, and menus must remain individually operable.
- Show sortable column affordances, not just hidden click-to-sort.
- Saved filters are optional; not essential for initial release.
- Use semantic `<table>` for ordinary tables. Use an ARIA `grid` only if implementing the expected keyboard/focus model for interactive editing.

### Forms

- Labels above controls, not placeholder-only.
- Validate required financial identifiers, dates, currency, positive/negative amount constraints and duplicate invoice numbers as appropriate.
- Display field errors directly under the corresponding control and summarize when a submission fails.
- Inputs for currencies may accept user-friendly strings but parse to exact decimal amounts server-side. Recompute and verify totals server-side.
- Default currency follows workspace preferences; preserve currency on every record.
- Differentiate `Save draft`, `Issue`, `Send`, `Approve`, and `Record payment` as distinct actions.
- Warn before navigating away from unsaved data.

---

## 9. AI-assisted workflow UX

### Supplier invoice flow (AP)

```text
Upload/import → Classify → Extract → Validate fields →
Find candidate PO → Compare totals/line items → Flag issues →
Human review → Approval → Record settlement
```

1. Immediately display `Uploading…` then `Processing…` with asynchronous progression.
2. Display extracted values beside the source document.
3. Mark missing or uncertain fields clearly; an uncertain field is not necessarily a confirmed error.
4. Explain match recommendation with supplier, PO ID, line-level matches and differences.
5. Require review on mismatches or configurable policy breaches; no opaque silent overrides.
6. Preserve all edits, overrides and approvals in the activity log.

### Customer invoice flow (AR)

```text
Choose customer / import customer PO → Generate editable draft →
Review lines & taxes → Preview → Issue → Send (if enabled) →
Monitor due/overdue → Follow up → Record/reconcile settlement
```

AI can extract data from customer POs, draft descriptions, propose reminders and identify inconsistencies, but all outgoing documents/messages must be confirmed by an authorized human unless an explicit automation policy has been configured.

### AI confidence display

- Show per-field extraction confidence only if backed by an actual measured/calibrated score.
- Never display invented confidence percentages such as `100%` as design filler in production.
- A single document-wide score is not a substitute for per-field validation.
- Always support `AI unavailable`, `low-quality scan`, `no evidence found`, `model timeout`, and `manual entry` fallbacks.

---

## 10. Accessible interactions and feedback

- Target **WCAG 2.2 AA**.
- Keyboard navigable sidebar, filters, dialogs, tables, document controls, and line-item editor.
- Visible `focus-visible` ring, logical focus order, escape to dismiss overlays, focus restoration after dialogs.
- Use `aria-live` for significant asynchronous results but avoid reading every background step aloud.
- Text alternative to colored charts and clear data tables for complex visualizations.
- Never rely on hover alone for critical finance actions.
- Destructive confirmations state the affected document and irreversible effect.
- Use optimistic UI only where rollback is safe. For financial writes, show authoritative confirmation from backend.
- Progress states: skeleton (initial data), spinner (short task), explicit queued/running state (long AI processing).
- Every empty state explains why the view is empty and offers one relevant action.

### Microcopy

- Prefer `Upload supplier invoice` to `Add document`.
- Prefer `Record payment` to `Pay now` unless actual bank/payment integration exists.
- Prefer `Review discrepancy` to vague `Fix issue`.
- Prefer `Suggested match` to `AI verified` when verification has not occurred.
- Dates and times should respect workspace locale/time zone, with consistent formatting.

---

## 11. Motion, charts, and responsive design

**Motion:** 120–180ms for hover/focus, 180–240ms for drawers and dialogs. Respect `prefers-reduced-motion`. Avoid animated chart entrances that delay data visibility.

**Charts:** Use Recharts or equivalent, limited hues, clear legends, explicit axis units, accessible summaries. Financial periods and currencies must be shown. Avoid donut charts when a simple table communicates the data better.

**Desktop review layout:** two-column document+analysis split. **Tablet:** adjustable split or vertically stacked viewer with tabs. **Mobile:** documents and form content in separate tabs; full-width primary actions. Tables may shift into item cards when necessary, keeping amount/status/document number visible.

---

## 12. Reference CSS tokens — Tailwind v4 + shadcn/ui

Copy the following as a **starting theme scaffold**, then layer it onto the `app/globals.css` produced by your actual shadcn/UI installation. It defines core product tokens and is not a replacement for every framework/plugin stylesheet.

```css
@import "tailwindcss";
@custom-variant dark (&:where(.dark, .dark *));

:root {
  --radius: 0.75rem;
  --background: #f8fafc;
  --foreground: #111827;
  --card: #ffffff;
  --card-foreground: #111827;
  --popover: #ffffff;
  --popover-foreground: #111827;
  --primary: #2563eb;
  --primary-foreground: #ffffff;
  --secondary: #f1f5f9;
  --secondary-foreground: #111827;
  --muted: #f1f5f9;
  --muted-foreground: #64748b;
  --accent: #eff6ff;
  --accent-foreground: #1d4ed8;
  --destructive: #dc2626;
  --border: #e2e8f0;
  --input: #e2e8f0;
  --ring: #2563eb;

  /* Product-specific semantic tokens */
  --surface-muted: #f1f5f9;
  --text-secondary: #475569;
  --success: #15803d;
  --success-background: #f0fdf4;
  --warning: #b45309;
  --warning-background: #fffbeb;
  --danger-background: #fef2f2;
  --ai-accent: #7c3aed;
  --ai-background: #f5f3ff;
}

.dark {
  --background: #0b1220;
  --foreground: #f8fafc;
  --card: #111827;
  --card-foreground: #f8fafc;
  --popover: #111827;
  --popover-foreground: #f8fafc;
  --primary: #60a5fa;
  --primary-foreground: #0b1220;
  --secondary: #1e293b;
  --secondary-foreground: #f8fafc;
  --muted: #1e293b;
  --muted-foreground: #94a3b8;
  --accent: #1e3a8a;
  --accent-foreground: #eff6ff;
  --destructive: #f87171;
  --border: #334155;
  --input: #334155;
  --ring: #60a5fa;

  --surface-muted: #1e293b;
  --text-secondary: #cbd5e1;
  --success: #86efac;
  --success-background: #052e16;
  --warning: #fcd34d;
  --warning-background: #451a03;
  --danger-background: #450a0a;
  --ai-accent: #c4b5fd;
  --ai-background: #2e1065;
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);

  --color-surface-muted: var(--surface-muted);
  --color-text-secondary: var(--text-secondary);
  --color-success: var(--success);
  --color-success-background: var(--success-background);
  --color-warning: var(--warning);
  --color-warning-background: var(--warning-background);
  --color-danger-background: var(--danger-background);
  --color-ai-accent: var(--ai-accent);
  --color-ai-background: var(--ai-background);
}

@layer base {
  body {
    @apply bg-background text-foreground antialiased;
  }

  * {
    @apply border-border;
  }
}

.money,
.document-id,
.financial-numeric {
  font-variant-numeric: tabular-nums;
}
```

**Note:** Match the version-specific shadcn/ui-generated CSS tokens and `@theme` conventions after initialization, rather than introducing duplicate or conflicting token definitions. `--radius` is available to shadcn components; retain their generated radius scale or derive it from this base.

### Example usage

```tsx
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function OutstandingPayablesCard() {
  return (
    <Card className="rounded-xl border-border shadow-none">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          Outstanding Payables
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="money text-3xl font-semibold tracking-tight">€128,450.00</p>
        <p className="mt-1 text-xs text-text-secondary">As of 14 Oct 2026 · EUR</p>
        <Button className="mt-4" variant="outline">View supplier bills</Button>
      </CardContent>
    </Card>
  );
}
```

Example figures are **illustrative UI content**, not real financial data.

---

## 13. Navigation configuration example

Use a typed config rather than hardcoding sidebar items in JSX.

```ts
// src/config/navigation.ts
import {
  Activity,
  Building2,
  CalendarClock,
  ChartNoAxesCombined,
  ClipboardList,
  FileText,
  Inbox,
  LayoutDashboard,
  ListTodo,
  ReceiptText,
  Settings,
  Users,
  type LucideIcon,
} from "lucide-react";

export type NavigationItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  badgeKey?: "unreadInbox" | "myTasks";
};

export type NavigationGroup = {
  label: string;
  items: NavigationItem[];
};

export const navigation: NavigationGroup[] = [
  {
    label: "Workspace",
    items: [
      { label: "Overview", href: "/dashboard", icon: LayoutDashboard },
      { label: "Inbox", href: "/inbox", icon: Inbox, badgeKey: "unreadInbox" },
      { label: "My Tasks", href: "/tasks", icon: ListTodo, badgeKey: "myTasks" },
    ],
  },
  {
    label: "Accounts Payable",
    items: [
      { label: "Supplier Bills", href: "/payables/bills", icon: ReceiptText },
      { label: "Purchase Orders", href: "/payables/purchase-orders", icon: ClipboardList },
      { label: "Suppliers", href: "/payables/suppliers", icon: Building2 },
    ],
  },
  {
    label: "Accounts Receivable",
    items: [
      { label: "Customer Invoices", href: "/receivables/invoices", icon: FileText },
      { label: "Customers", href: "/receivables/customers", icon: Users },
      { label: "Collections", href: "/receivables/collections", icon: CalendarClock },
    ],
  },
  {
    label: "Management",
    items: [
      { label: "AI Activity", href: "/ai/activity", icon: Activity },
      { label: "Reports", href: "/reports", icon: ChartNoAxesCombined },
      { label: "Settings", href: "/settings", icon: Settings },
    ],
  },
];
```

Apply route permissions in addition to navigation visibility: **hidden menu items are not authorization**.

---

## 14. Suggested project organization

```text
src/
  app/
    (app)/
      layout.tsx
      dashboard/page.tsx
      inbox/page.tsx
      tasks/page.tsx
      payables/
        bills/page.tsx
        bills/[billId]/page.tsx
        purchase-orders/page.tsx
        purchase-orders/new/page.tsx
        purchase-orders/[poId]/page.tsx
        suppliers/page.tsx
      receivables/
        invoices/page.tsx
        invoices/new/page.tsx
        invoices/[invoiceId]/page.tsx
        customers/page.tsx
        collections/page.tsx
      ai/activity/page.tsx
      reports/page.tsx
      settings/page.tsx
    globals.css
  components/
    ui/                  # shadcn/ui primitives
    layout/              # sidebar, topbar, page-header
    finance/             # money, statuses, KPIs, tables
    invoices/            # invoice forms, document viewer
    purchase-orders/     # PO editor and comparison
    ai/                  # extraction, evidence, run log
  config/navigation.ts
  lib/format.ts          # locale-aware formatting
  lib/money.ts           # exact financial calculations
  lib/permissions.ts
  types/finance.ts
```

### Implementation expectations

- App shell is server-rendered where practical; interactive tables and documents are client components.
- Use server-enforced multi-tenant data isolation and role-based permissions.
- Treat invoice uploads as sensitive data: validate file types and sizes, enforce access checks, virus/malware scanning as appropriate, secure storage, and retention/deletion controls.
- Record audit events for AI decisions, user edits, approval changes, sends, voids, bank detail changes, and payments.
- Use deterministic computation for totals and matching; LLMs assist extraction and interpretation rather than replacing accounting rules.
- Support empty, loading, failed, and partial-success states in all API-connected screens.

---

## 15. Design implementation phases

### Phase 1 — UI foundation

- [ ] Initialize Next.js/TypeScript/Tailwind/shadcn/ui.
- [ ] Add Inter, semantic tokens, color mode, icon convention.
- [ ] Build AppShell, Sidebar, TopBar, breadcrumbs, responsive navigation.
- [ ] Build buttons, inputs, cards, status chips, empty/loading/error patterns.
- [ ] Add Storybook and initial component examples.

### Phase 2 — Finance screens

- [ ] Overview dashboard with independently labelled AP and AR sections.
- [ ] Supplier Bills table and detailed invoice review.
- [ ] Purchase Orders table and creation/detail screens.
- [ ] Customer Invoices table and invoice editor/preview.
- [ ] Suppliers, Customers, Collections, Inbox, My Tasks.

### Phase 3 — AI interaction surfaces

- [ ] Source-aware extraction panel and editable fields.
- [ ] PO match comparison with rule-based amounts/line deltas.
- [ ] Exceptions and approval gate components.
- [ ] AI activity timeline, failure, retry, and audit views.

### Phase 4 — Production UX hardening

- [ ] Responsive QA at 360px, 768px, 1024px, 1440px.
- [ ] Keyboard and screen reader QA, reduced motion, contrast.
- [ ] Permissions and safe action confirmations.
- [ ] Currency/locale/rounding consistency checks.
- [ ] Test upload failures, duplicate documents, missing fields, mismatched PO, partial payment, and AI timeout.

---

## 16. Acceptance criteria

The design system is correctly implemented when:

1. A user can immediately tell **who owes whom** on every AP/AR screen.
2. Sidebar groups, labels, routes, and selected states are consistent throughout the app.
3. Every meaningful value (especially money, dates, invoice IDs, and tax) is legible and appropriately formatted.
4. Shared components look and behave consistently across AP and AR.
5. Supplier invoice review displays original evidence alongside extracted values and explains discrepancies.
6. PO matching, approval, extraction, and payment have separate states.
7. Customer invoice creation supports an editable line-item form and accurate preview.
8. Every high-impact operation has a clear, permission-checked confirmation path.
9. There are no fake AI confidence scores or implicit automated approvals/payments.
10. The UI works without mouse input and remains usable on desktop, tablet, and mobile.
11. The application's visual style resembles a credible, production-ready business finance product: restrained blue/gray palette, consistent whitespace, readable tables, and minimal decoration.

---

## 17. References informing product and UI decisions

These links are **references**, not claims that Invoice AI already includes any third-party feature.

- [shadcn/ui — Theming](https://ui.shadcn.com/docs/theming): semantic CSS variables, foreground/background pairs, radius conventions, dark theme.
- [Ramp — Procurement Quick Start](https://support.ramp.com/ramp-procurement-quick-start-guide/): purchase request → PO → invoice → match → approval/payment, including two- and three-way matching.
- [Ramp — 3-Way Match](https://support.ramp.com/3-way-match-with-ramp-procurement): PO, bill, and receipt relationships.
- [Stripe — Invoice states](https://support.stripe.com/questions/invoice-states?locale=en-GB): draft/open/paid/void/uncollectible lifecycle reference for AR.
- [W3C WAI-ARIA APG — Grid pattern](https://www.w3.org/WAI/ARIA/apg/patterns/grid/): table vs interactive grid focus behavior.
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/): accessibility target.

**Design decisions pending product implementation:** email integrations, actual payment rails, full three-way receipt handling, currency conversion, invoicing jurisdiction and tax compliance rules, external accounting/ERP sync, configurable authorization policies. These require deliberate functional design and should not be visually implied as already available.
