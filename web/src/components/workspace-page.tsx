"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowDownUp,
  ArrowRight,
  CheckCheck,
  CircleAlert,
  FileCheck2,
  FileText,
  Inbox,
  Loader2,
  RefreshCw,
  Search,
  Upload,
  XCircle,
} from "lucide-react";
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { UploadPanel } from "@/components/upload";
import { api, date, money, statusLabels } from "@/lib/client";
import type { InvoiceRecord, QueueItem } from "@/lib/types";
export function Status({ value }: { value: string }) {
  return (
    <span className={`status status-${value}`}>
      {value === "approved" ? (
        <CheckCheck size={13} />
      ) : value === "awaiting_review" ? (
        <CircleAlert size={13} />
      ) : value === "failed" || value === "rejected" ? (
        <XCircle size={13} />
      ) : value === "processing" ? (
        <Loader2 size={13} className="animate-spin" />
      ) : null}
      {statusLabels[value] || value}
    </span>
  );
}
async function all<T>(path: string): Promise<T[]> {
  const rows: T[] = [];
  for (let offset = 0; ; offset += 200) {
    const page = await api<T[]>(`${path}?limit=200&offset=${offset}`);
    rows.push(...page);
    if (page.length < 200) return rows;
  }
}
export function WorkspacePage({ view }: { view: "inbox" | "tasks" | "bills" }) {
  const [invoices, setInvoices] = useState<InvoiceRecord[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const [records, tasks] = await Promise.all([
        all<InvoiceRecord>("invoices"),
        all<QueueItem>("review-queue"),
      ]);
      setInvoices(records);
      setQueue(tasks);
      setError("");
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => {
      if (!document.hidden) void refresh();
    }, 10_000);
    return () => clearInterval(timer);
  }, [refresh]);
  const active = invoices.filter(
    (item) => item.status === "processing" || item.status === "uploaded",
  ).length;
  const rows = useMemo(
    () =>
      view === "tasks"
        ? queue.map((item) => ({
            id: item.invoice_id,
            status: "awaiting_review",
            ...item,
          }))
        : invoices.map((item) => ({
            ...item,
            ...queue.find((task) => task.invoice_id === item.id),
          })),
    [invoices, queue, view],
  );
  type Row = (typeof rows)[number];
  const columns = useMemo<ColumnDef<Row>[]>(
    () => [
      {
        accessorKey: "filename",
        header: view === "tasks" ? "Supplier / Invoice" : "Document",
        cell: ({ row }) => (
          <Link
            className="document-link"
            href={`/payables/bills/${row.original.id}`}
          >
            <span className="file-icon">
              <FileText size={19} />
            </span>
            <span>
              <strong>
                {row.original.vendor_name || row.original.filename}
              </strong>
              <small>{row.original.invoice_number || "Supplier invoice"}</small>
            </span>
          </Link>
        ),
      },
      {
        accessorKey: "uploaded_at",
        header: "Received",
        cell: ({ getValue }) => (
          <span className="nowrap">{date(getValue<string>())}</span>
        ),
      },
      ...(view === "tasks"
        ? [
            {
              accessorKey: "total",
              header: "Total incl. tax",
              cell: ({ row }: { row: { original: Row } }) => (
                <span className="money">
                  {money(row.original.total!, row.original.currency!)}
                </span>
              ),
            },
            {
              accessorKey: "issue_count",
              header: "Review reason",
              cell: ({ row }: { row: { original: Row } }) => (
                <span>
                  <span className="status status-awaiting_review">
                    {row.original.decision === "vendor_query"
                      ? "Supplier discrepancy"
                      : "Verify details"}
                  </span>
                  <small className="cell-subtext">
                    {row.original.issue_count}{" "}
                    {row.original.issue_count === 1 ? "issue" : "issues"} to
                    inspect
                  </small>
                </span>
              ),
            },
          ]
        : [
            {
              accessorKey: "status",
              header: "Workflow state",
              cell: ({ getValue }: { getValue: () => unknown }) => (
                <Status value={String(getValue())} />
              ),
            },
          ]),
      {
        id: "action",
        header: "",
        enableSorting: false,
        cell: ({ row }) => (
          <Link
            className={buttonVariants({ variant: "ghost", size: "sm" })}
            href={`/payables/bills/${row.original.id}`}
          >
            {row.original.status === "awaiting_review" ? "Review" : "View"}
            <ArrowRight size={14} />
            <span className="sr-only"> {row.original.filename}</span>
          </Link>
        ),
      },
    ],
    [view],
  );
  const filtered = useMemo(
    () => rows.filter((row) => filter === "all" || row.status === filter),
    [rows, filter],
  );
  const table = useReactTable({
    data: filtered,
    columns,
    state: { globalFilter: search },
    onGlobalFilterChange: setSearch,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: { pageSize: 20 },
      sorting: [{ id: "uploaded_at", desc: view !== "tasks" }],
    },
  });
  return (
    <>
      <div
        className="page-heading"
        {...(view === "tasks" ? { "data-tour": "tasks-intro" } : {})}
      >
        <div>
          <p className="eyebrow">
            {view === "inbox" ? "YOUR DOCUMENTS, IN ORDER" : "ACCOUNTS PAYABLE"}
          </p>
          <h1>
            {view === "inbox"
              ? "Inbox"
              : view === "tasks"
                ? "Review queue"
                : "Supplier Bills"}
          </h1>
          <p>
            {view === "inbox"
              ? "From supplier invoice to a clear next step."
              : view === "tasks"
                ? "A closer look where it matters. Review exceptions before moving bills forward."
                : "Track incoming invoices from upload through review and approval."}
          </p>
        </div>
        {view !== "inbox" && (
          <Link className={buttonVariants()} href="/inbox">
            <Upload />
            Upload invoice
          </Link>
        )}
      </div>
      <div
        className="metrics"
        {...(view === "tasks" ? { "data-tour": "tasks-metrics" } : {})}
      >
        <Metric
          label="Needs review"
          value={loading ? "—" : queue.length}
          text="Ready for a human check"
          icon={CircleAlert}
          tone="warning"
        />
        <Metric
          label="Processing"
          value={loading ? "—" : active}
          text="Extraction & purchase order checks"
          icon={FileText}
          tone="blue"
        />
        <Metric
          label="Approved"
          value={
            loading
              ? "—"
              : invoices.filter((item) => item.status === "approved").length
          }
          text="Approval recorded · not payment"
          icon={FileCheck2}
          tone="success"
        />
      </div>
      {view === "inbox" && (
        <div className="inbox-grid">
          <UploadPanel onUploaded={() => void refresh()} />
          <aside className="panel workflow-card">
            <p className="eyebrow">A CLEAR PATH FOR EVERY INVOICE</p>
            <h2>
              Less entry.
              <br />
              More oversight.
            </h2>
            <div className="workflow-step">
              <span>01</span>
              <div>
                <h3>Upload the original</h3>
                <p>
                  Keep your source document alongside its extracted details.
                </p>
              </div>
            </div>
            <div className="workflow-step">
              <span>02</span>
              <div>
                <h3>Let the checks run</h3>
                <p>
                  Read the invoice and compare it with the purchase order and
                  receipts.
                </p>
              </div>
            </div>
            <div className="workflow-step">
              <span>03</span>
              <div>
                <h3>Review the exceptions</h3>
                <p>
                  Inspect flagged details, correct extraction, and record your
                  decision.
                </p>
              </div>
            </div>
            <div className="policy-note">
              Clean matches may be automatically approved by the current backend
              rules. Approval does not record a payment.
            </div>
          </aside>
        </div>
      )}
      <section
        className="panel table-panel"
        {...(view === "tasks" ? { "data-tour": "tasks-queue" } : {})}
      >
        <div className="section-heading">
          <div>
            <h2>
              {view === "inbox"
                ? "Received documents"
                : view === "tasks"
                  ? "Waiting for your review"
                  : "All supplier bills"}
              <span className="count">{loading ? "—" : rows.length}</span>
            </h2>
            <p>
              {view === "tasks"
                ? "Oldest first. Open an invoice to inspect its source and flagged details."
                : "Original documents and their latest workflow state."}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refresh()}
            disabled={refreshing}
          >
            <RefreshCw className={refreshing ? "animate-spin" : ""} />
            Refresh
          </Button>
        </div>
        <div className="table-toolbar">
          <div className="search-input">
            <Search size={16} />
            <Input
              aria-label="Search documents"
              placeholder={
                view === "tasks"
                  ? "Search supplier, invoice or document…"
                  : "Search documents…"
              }
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          {view !== "tasks" && (
            <select
              aria-label="Filter workflow state"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            >
              <option value="all">All workflow states</option>
              {Object.entries(statusLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </div>
        {error && (
          <div role="alert" className="error-banner">
            <CircleAlert size={18} />
            <div>
              <strong>Couldn’t refresh documents</strong>
              <p>{error}</p>
            </div>
            <Button variant="outline" onClick={() => void refresh()}>
              Try again
            </Button>
          </div>
        )}
        {error && !rows.length ? null : loading ? (
          <div className="empty-state" role="status">
            <Loader2 className="animate-spin" />
            <h3>Loading your documents…</h3>
          </div>
        ) : !table.getFilteredRowModel().rows.length ? (
          <div className="empty-state">
            <Inbox size={30} />
            <h3>
              {search || filter !== "all"
                ? "No matching documents"
                : view === "tasks"
                  ? "Nothing waiting for review"
                  : "Your inbox starts here"}
            </h3>
            <p>
              {search || filter !== "all"
                ? "Try another search or clear your filters."
                : view === "tasks"
                  ? "Invoices that need a closer look will appear here after processing."
                  : "Upload a supplier invoice to extract its details and start the checks."}
            </p>
            {(search || filter !== "all") && (
              <Button
                variant="outline"
                onClick={() => {
                  setSearch("");
                  setFilter("all");
                }}
              >
                Clear filters
              </Button>
            )}
          </div>
        ) : (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  {table.getHeaderGroups().map((group) => (
                    <tr key={group.id}>
                      {group.headers.map((header) => (
                        <th key={header.id}>
                          {header.column.getCanSort() ? (
                            <button
                              onClick={header.column.getToggleSortingHandler()}
                            >
                              {flexRender(
                                header.column.columnDef.header,
                                header.getContext(),
                              )}
                              <ArrowDownUp size={12} />
                            </button>
                          ) : (
                            flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )
                          )}
                        </th>
                      ))}
                    </tr>
                  ))}
                </thead>
                <tbody>
                  {table.getRowModel().rows.map((row) => (
                    <tr key={row.id}>
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id}>
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pagination">
              <span>
                {table.getFilteredRowModel().rows.length} documents · Page{" "}
                {table.getState().pagination.pageIndex + 1} of{" "}
                {table.getPageCount()}
              </span>
              <div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!table.getCanPreviousPage()}
                  onClick={() => table.previousPage()}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!table.getCanNextPage()}
                  onClick={() => table.nextPage()}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </section>
    </>
  );
}
function Metric({
  label,
  value,
  text,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string | number;
  text: string;
  icon: typeof FileText;
  tone: string;
}) {
  return (
    <div className="panel metric">
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        <small>{text}</small>
      </div>
      <span className={`metric-icon ${tone}`}>
        <Icon size={20} />
      </span>
    </div>
  );
}
