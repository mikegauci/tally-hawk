-- TallyHawk schema: the procurement records invoices are matched against, and the
-- invoices themselves as they move through extraction, matching and human review.
--
-- Plain-English glossary:
--   purchase order (PO)  what the buyer agreed to buy, from which supplier, at what price
--   goods receipt (GRN)  what the warehouse actually received against a PO
--   three-way match      checking the invoice against both of the above before paying
--   posted invoice       an invoice already entered in the accounting system
--
-- Every table has row level security on with no policies: Supabase's public API keys
-- (anon / authenticated) see nothing. The FastAPI service connects as the database owner,
-- which bypasses RLS. Policies for signed-in users come with the web app.

-- Document numbers compare ignoring case and whitespace ("inv 0042" = "INV0042").
-- Mirrors tallyhawk.procurement.normalize_ref.
create or replace function public.normalize_ref(value text) returns text
language sql immutable parallel safe
set search_path = ''
as $$ select lower(regexp_replace(value, '\s', '', 'g')) $$;

-- Procurement -------------------------------------------------------------------------

create table public.vendors (
    vendor_id text primary key,
    name text not null,
    tax_id text,
    tax_id_key text generated always as (public.normalize_ref(tax_id)) stored,
    email text not null,
    address text not null,
    created_at timestamptz not null default now()
);
create index vendors_tax_id_key_idx on public.vendors (tax_id_key);

create table public.purchase_orders (
    po_number text primary key,
    po_number_key text generated always as (public.normalize_ref(po_number)) stored unique,
    vendor_id text not null references public.vendors (vendor_id),
    order_date date not null,
    currency char(3) not null,
    status text not null check (status in ('open', 'closed')),
    created_at timestamptz not null default now()
);
create index purchase_orders_vendor_idx on public.purchase_orders (vendor_id, status);

create table public.po_lines (
    po_number text not null references public.purchase_orders (po_number) on delete cascade,
    line_no integer not null,
    description text not null,
    quantity numeric(14, 4) not null,
    unit_price numeric(14, 4) not null,
    primary key (po_number, line_no)
);

create table public.goods_receipts (
    receipt_number text primary key,
    po_number text not null references public.purchase_orders (po_number) on delete cascade,
    received_date date not null,
    created_at timestamptz not null default now()
);
create index goods_receipts_po_idx on public.goods_receipts (po_number);

create table public.goods_receipt_lines (
    receipt_number text not null references public.goods_receipts (receipt_number) on delete cascade,
    po_line integer not null,
    quantity numeric(14, 4) not null,
    primary key (receipt_number, po_line)
);

create table public.posted_invoices (
    id bigint generated always as identity primary key,
    vendor_id text not null references public.vendors (vendor_id),
    invoice_number text not null,
    invoice_number_key text generated always as (public.normalize_ref(invoice_number)) stored,
    invoice_date date not null,
    total numeric(14, 2) not null,
    status text not null check (status in ('posted', 'paid')),
    -- set when TallyHawk approved the invoice itself (null for seeded / imported rows)
    invoice_id uuid,
    created_at timestamptz not null default now()
);
create index posted_invoices_lookup_idx on public.posted_invoices (vendor_id, invoice_number_key);

-- Invoices through the pipeline -------------------------------------------------------

create table public.invoices (
    id uuid primary key default gen_random_uuid(),
    filename text not null,
    media_type text not null,
    storage_path text not null,
    size_bytes integer not null,
    sha256 text not null,
    -- uploaded -> processing -> approved | awaiting_review | failed
    -- a reviewer then moves awaiting_review to approved, rejected or vendor_queried
    status text not null default 'uploaded' check (
        status in ('uploaded', 'processing', 'approved', 'awaiting_review', 'vendor_queried', 'rejected', 'failed')
    ),
    error text,
    uploaded_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index invoices_status_idx on public.invoices (status, uploaded_at);
create index invoices_sha256_idx on public.invoices (sha256);

alter table public.posted_invoices
    add constraint posted_invoices_invoice_fk foreign key (invoice_id) references public.invoices (id) on delete set null;

-- One row per extraction run (re-processing an invoice adds a row).
create table public.extractions (
    id bigint generated always as identity primary key,
    invoice_id uuid not null references public.invoices (id) on delete cascade,
    model text not null,
    extracted jsonb not null,           -- tallyhawk.schema.ExtractedInvoice: fields + confidence
    issues jsonb not null,              -- validation issues
    low_confidence_fields text[] not null,
    needs_review boolean not null,
    input_tokens integer not null,
    output_tokens integer not null,
    cost_usd numeric(12, 6),
    latency_s numeric(8, 2),
    created_at timestamptz not null default now()
);
create index extractions_invoice_idx on public.extractions (invoice_id, created_at desc);

-- One row per matching run: after extraction, and again after a reviewer corrects fields.
create table public.match_results (
    id bigint generated always as identity primary key,
    invoice_id uuid not null references public.invoices (id) on delete cascade,
    extraction_id bigint references public.extractions (id) on delete set null,
    source text not null check (source in ('extraction', 'correction')),
    invoice_data jsonb not null,        -- the invoice fields this match ran on
    decision text not null check (decision in ('approve', 'review', 'vendor_query')),
    vendor_id text,
    po_number text,
    outcome jsonb not null,             -- tallyhawk.workflow.MatchOutcome: issues, lines, draft, trace
    cost_usd numeric(12, 6),
    created_at timestamptz not null default now()
);
create index match_results_invoice_idx on public.match_results (invoice_id, created_at desc);

-- What a person decided. Corrections (reviewer-fixed fields next to what the model read)
-- are future eval data.
create table public.reviews (
    id bigint generated always as identity primary key,
    invoice_id uuid not null references public.invoices (id) on delete cascade,
    match_result_id bigint references public.match_results (id) on delete set null,
    action text not null check (action in ('approve', 'reject', 'send_query', 'correct')),
    corrected_invoice jsonb,
    note text,
    reviewer text,
    created_at timestamptz not null default now()
);
create index reviews_invoice_idx on public.reviews (invoice_id, created_at);

-- The review queue: invoices waiting for a person, with their latest match.
create view public.review_queue with (security_invoker = true) as
select
    i.id as invoice_id,
    i.filename,
    i.uploaded_at,
    m.id as match_result_id,
    m.decision,
    m.vendor_id,
    m.po_number,
    m.invoice_data ->> 'invoice_number' as invoice_number,
    m.invoice_data ->> 'vendor_name' as vendor_name,
    (m.invoice_data ->> 'total')::numeric as total,
    m.invoice_data ->> 'currency' as currency,
    jsonb_array_length(m.outcome -> 'issues') as issue_count
from public.invoices i
join lateral (
    select * from public.match_results mr where mr.invoice_id = i.id order by mr.created_at desc, mr.id desc limit 1
) m on true
where i.status = 'awaiting_review';

alter table public.vendors enable row level security;
alter table public.purchase_orders enable row level security;
alter table public.po_lines enable row level security;
alter table public.goods_receipts enable row level security;
alter table public.goods_receipt_lines enable row level security;
alter table public.posted_invoices enable row level security;
alter table public.invoices enable row level security;
alter table public.extractions enable row level security;
alter table public.match_results enable row level security;
alter table public.reviews enable row level security;
