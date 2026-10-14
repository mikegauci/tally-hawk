"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  CircleAlert,
  FileCheck2,
  FileText,
  Loader2,
  MailWarning,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Status } from "@/components/workspace-page";
import { api, date } from "@/lib/client";
import type { InvoiceRecord, QueueItem } from "@/lib/types";

async function all<T>(path: string): Promise<T[]> {
  const rows: T[] = [];
  for (let offset = 0; ; offset += 200) {
    const page = await api<T[]>(`${path}?limit=200&offset=${offset}`);
    rows.push(...page);
    if (page.length < 200) return rows;
  }
}

const STATUS_ORDER: InvoiceRecord["status"][] = [
  "awaiting_review",
  "vendor_queried",
  "processing",
  "uploaded",
  "approved",
  "rejected",
  "failed",
];

export function DashboardPage() {
  const [invoices, setInvoices] = useState<InvoiceRecord[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

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
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch matches workspace pages
    void refresh();
    const timer = setInterval(() => {
      if (!document.hidden) void refresh();
    }, 10_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const counts = useMemo(() => {
    const byStatus: Record<string, number> = {};
    for (const item of invoices) {
      byStatus[item.status] = (byStatus[item.status] || 0) + 1;
    }
    const processing =
      (byStatus.processing || 0) + (byStatus.uploaded || 0);
    return {
      byStatus,
      processing,
      awaitingReview: byStatus.awaiting_review || 0,
      vendorQuery: byStatus.vendor_queried || 0,
      approved: byStatus.approved || 0,
      failed: byStatus.failed || 0,
      total: invoices.length,
    };
  }, [invoices]);

  const recent = useMemo(
    () =>
      [...invoices]
        .sort(
          (a, b) =>
            new Date(b.uploaded_at).getTime() -
            new Date(a.uploaded_at).getTime(),
        )
        .slice(0, 8),
    [invoices],
  );

  const attention = useMemo(() => {
    const failed = invoices.filter((i) => i.status === "failed");
    const processing = invoices.filter(
      (i) => i.status === "processing" || i.status === "uploaded",
    );
    return { failed, processing, queue };
  }, [invoices, queue]);

  const maxStatusCount = Math.max(1, ...Object.values(counts.byStatus));

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">ACCOUNTS PAYABLE</p>
          <h1>Overview</h1>
          <p>
            Supplier bills only — counts and statuses from your uploaded
            documents. Receivables are not part of this workspace.
          </p>
        </div>
        <Button
          variant="outline"
          disabled={refreshing}
          onClick={() => void refresh()}
        >
          {refreshing ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <RefreshCw size={16} />
          )}
          Refresh
        </Button>
      </div>

      {error && (
        <div className="panel error-banner" role="alert">
          {error}
        </div>
      )}

      <div className="metrics metrics-wide">
        <Metric
          label="Needs review"
          value={loading ? "—" : counts.awaitingReview}
          text="Waiting in your queue"
          icon={CircleAlert}
          tone="warning"
        />
        <Metric
          label="Supplier follow-up"
          value={loading ? "—" : counts.vendorQuery}
          text="Query recorded · email not sent"
          icon={MailWarning}
          tone="warning"
        />
        <Metric
          label="Processing"
          value={loading ? "—" : counts.processing}
          text="Extraction and matching"
          icon={FileText}
          tone="blue"
        />
        <Metric
          label="Approved"
          value={loading ? "—" : counts.approved}
          text="Recorded · not payment"
          icon={FileCheck2}
          tone="success"
        />
        <Metric
          label="Failed"
          value={loading ? "—" : counts.failed}
          text="Retry from Inbox"
          icon={XCircle}
          tone="danger"
        />
      </div>

      <div className="dashboard-grid">
        <section className="panel">
          <div className="section-heading">
            <h2>Needs your attention</h2>
            <Link className={buttonVariants({ variant: "ghost", size: "sm" })} href="/tasks">
              Open review queue
              <ArrowRight size={14} />
            </Link>
          </div>
          {loading ? (
            <p className="muted">Loading…</p>
          ) : attention.queue.length === 0 &&
            attention.failed.length === 0 &&
            attention.processing.length === 0 ? (
            <p className="muted">No open exceptions. Upload a supplier invoice from Inbox.</p>
          ) : (
            <ul className="attention-list">
              {attention.queue.slice(0, 5).map((item) => (
                <li key={item.invoice_id}>
                  <div>
                    <strong>{item.vendor_name}</strong>
                    <span>{item.invoice_number}</span>
                  </div>
                  <Link href={`/payables/bills/${item.invoice_id}`}>
                    Review
                    <ArrowRight size={14} />
                  </Link>
                </li>
              ))}
              {attention.failed.slice(0, 3).map((item) => (
                <li key={item.id} className="attention-failed">
                  <div>
                    <strong>{item.filename}</strong>
                    <span>Processing failed</span>
                  </div>
                  <Link href="/inbox">Retry from Inbox</Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel">
          <h2>Status breakdown</h2>
          <p className="muted small">
            {counts.total} supplier bill{counts.total === 1 ? "" : "s"} in this workspace
          </p>
          <ul className="status-breakdown">
            {STATUS_ORDER.filter((s) => counts.byStatus[s]).map((status) => (
              <li key={status}>
                <Status value={status} />
                <div className="status-bar-track">
                  <div
                    className="status-bar-fill"
                    style={{
                      width: `${(100 * (counts.byStatus[status] || 0)) / maxStatusCount}%`,
                    }}
                  />
                </div>
                <span className="status-count">{counts.byStatus[status]}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="panel">
        <div className="section-heading">
          <h2>Recent supplier bills</h2>
          <Link
            className={buttonVariants({ variant: "ghost", size: "sm" })}
            href="/payables/bills"
          >
            View all
            <ArrowRight size={14} />
          </Link>
        </div>
        {loading ? (
          <p className="muted">Loading…</p>
        ) : recent.length === 0 ? (
          <p className="muted">
            No bills yet.{" "}
            <Link href="/inbox" className="text-link">
              Upload from Inbox
            </Link>
            .
          </p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Received</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {recent.map((row) => (
                  <tr key={row.id}>
                    <td>{row.filename}</td>
                    <td>{date(row.uploaded_at)}</td>
                    <td>
                      <Status value={row.status} />
                    </td>
                    <td>
                      <Link
                        className={buttonVariants({ variant: "ghost", size: "sm" })}
                        href={`/payables/bills/${row.id}`}
                      >
                        View
                        <ArrowRight size={14} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
