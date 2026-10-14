"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  ExternalLink,
  Loader2,
  Save,
  Sparkles,
  CircleAlert,
  FileText,
  Check,
  X,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Status } from "@/components/workspace-page";
import { api, date, money } from "@/lib/client";
import type { InvoiceData, InvoiceDetail } from "@/lib/types";
const fields: {
  key: Exclude<keyof InvoiceData, "line_items">;
  label: string;
  type?: string;
  nullable?: boolean;
}[] = [
  { key: "vendor_name", label: "Supplier name" },
  { key: "vendor_tax_id", label: "Supplier tax ID", nullable: true },
  { key: "invoice_number", label: "Invoice number" },
  { key: "po_number", label: "Purchase order reference", nullable: true },
  { key: "invoice_date", label: "Invoice date", type: "date" },
  { key: "due_date", label: "Due date", type: "date", nullable: true },
  { key: "currency", label: "Currency (ISO code)" },
  { key: "tax_rate", label: "Tax rate (%)", type: "number", nullable: true },
  { key: "subtotal", label: "Subtotal (excl. tax)", type: "number" },
  { key: "tax_amount", label: "Tax amount", type: "number" },
  { key: "total", label: "Total (incl. tax)", type: "number" },
];
type Action = "approve" | "reject" | "send_query" | "correct";
const actionLabels = {
  approve: "Approve bill",
  reject: "Reject bill",
  send_query: "Record supplier follow-up",
  correct: "Save corrections & recheck",
};
export function InvoiceReview({ id }: { id: string }) {
  const [detail, setDetail] = useState<InvoiceDetail | null>(null);
  const [draft, setDraft] = useState<InvoiceData | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState<Action | null>(null);
  const [note, setNote] = useState("");
  const [mobileTab, setMobileTab] = useState("data");
  const original =
    detail?.match?.invoice || detail?.extraction?.result.extracted.invoice;
  const dirty = Boolean(
    draft && original && JSON.stringify(draft) !== JSON.stringify(original),
  );
  const load = useCallback(async () => {
    try {
      const data = await api<InvoiceDetail>(`invoices/${id}`);
      setDetail(data);
      setDraft(
        data.match?.invoice ||
          data.extraction?.result.extracted.invoice ||
          null,
      );
      setError("");
    } catch (error) {
      setError((error as Error).message);
    }
  }, [id]);
  useEffect(() => {
    // Loads external API state; updates occur only after the network response.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);
  useEffect(() => {
    if (!detail || !["processing", "uploaded"].includes(detail.invoice.status))
      return;
    const timer = setInterval(() => void load(), 5000);
    return () => clearInterval(timer);
  }, [detail, load]);
  useEffect(() => {
    if (!dirty) return;
    const unload = (event: BeforeUnloadEvent) => event.preventDefault();
    const navigate = (event: MouseEvent) => {
      if (
        (event.target as HTMLElement).closest("a") &&
        !window.confirm("Discard your unsaved invoice corrections?")
      ) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", unload);
    document.addEventListener("click", navigate, true);
    return () => {
      window.removeEventListener("beforeunload", unload);
      document.removeEventListener("click", navigate, true);
    };
  }, [dirty]);
  async function submit() {
    if (!action) return;
    setBusy(true);
    setError("");
    try {
      const data = await api<InvoiceDetail>(`invoices/${id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          note: note || null,
          ...(action === "correct" ? { corrected_invoice: draft } : {}),
        }),
      });
      setDetail(data);
      setDraft(
        data.match?.invoice ||
          data.extraction?.result.extracted.invoice ||
          null,
      );
      setMessage(
        action === "correct"
          ? "Corrections saved and matching completed."
          : "Your review decision has been recorded.",
      );
      setAction(null);
      setNote("");
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!detail)
    return (
      <div className="panel empty-state">
        {error ? (
          <>
            <CircleAlert />
            <h2>Couldn’t load this invoice</h2>
            <p role="alert">{error}</p>
            <Button onClick={() => void load()}>Try again</Button>
          </>
        ) : (
          <>
            <Loader2 className="animate-spin" />
            <p>Loading invoice…</p>
          </>
        )}
      </div>
    );
  const editable = detail.invoice.status === "awaiting_review";
  const outcome = detail.match?.outcome;
  const issues = outcome?.issues || [];
  const lowConfidence = detail.extraction?.result.low_confidence_fields || [];
  const valid =
    draft &&
    draft.vendor_name.trim() &&
    draft.invoice_number.trim() &&
    draft.invoice_date &&
    /^[A-Z]{3}$/.test(draft.currency) &&
    [
      draft.subtotal,
      draft.tax_amount,
      draft.total,
      ...draft.line_items.flatMap((line) => [
        line.quantity,
        line.unit_price,
        line.amount,
      ]),
    ].every(Number.isFinite);
  return (
    <>
      <Link href="/tasks" className="back-link">
        <ArrowLeft size={16} />
        Back to review queue
      </Link>
      <div className="page-heading review-heading">
        <div>
          <p className="eyebrow">SUPPLIER BILL</p>
          <h1>{draft?.invoice_number || detail.invoice.filename}</h1>
          <p>
            {draft?.vendor_name || "Extraction pending"}{" "}
            <span className="breadcrumb-divider">·</span> Received{" "}
            {date(detail.invoice.uploaded_at)}
          </p>
        </div>
        <Status value={detail.invoice.status} />
      </div>
      {error && (
        <div className="error-banner" role="alert">
          {error}
          <Button
            variant="outline"
            onClick={() => void load()}
            disabled={dirty}
          >
            Refresh status
          </Button>
        </div>
      )}
      {message && (
        <div className="success-banner" role="status">
          <Check size={18} />
          {message}
        </div>
      )}
      <div className="review-mobile-tabs">
        <Button
          variant={mobileTab === "document" ? "default" : "outline"}
          onClick={() => setMobileTab("document")}
        >
          Document
        </Button>
        <Button
          variant={mobileTab === "data" ? "default" : "outline"}
          onClick={() => setMobileTab("data")}
        >
          Extracted data & matches
        </Button>
      </div>
      <div className={`review-grid show-${mobileTab}`}>
        <section className="panel source-panel">
          <div className="section-heading">
            <div>
              <h2>
                <FileText size={17} />
                Original document
              </h2>
              <p>{detail.invoice.filename}</p>
            </div>
            <a
              href={`/api/backend/invoices/${id}/file`}
              target="_blank"
              rel="noreferrer"
              className="icon-link"
              aria-label="Open original document in a new tab"
            >
              <ExternalLink size={17} />
            </a>
          </div>
          <div className="document-viewer">
            {detail.invoice.media_type === "application/pdf" ? (
              <object
                data={`/api/backend/invoices/${id}/file`}
                type="application/pdf"
                aria-label="Original invoice PDF"
              >
                <p>
                  Your browser cannot display this PDF.{" "}
                  <a
                    href={`/api/backend/invoices/${id}/file`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open original document
                  </a>
                </p>
              </object>
            ) : (
              <img
                src={`/api/backend/invoices/${id}/file`}
                alt={`Original supplier invoice: ${detail.invoice.filename}`}
              />
            )}
          </div>
          <div className="source-caption">
            Source document · Compare the original against the extracted values
          </div>
        </section>
        <section className="panel extracted-panel">
          <Tabs defaultValue="overview">
            <div className="review-tabs">
              <TabsList>
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="lines">Line items</TabsTrigger>
                <TabsTrigger value="matching">Matching</TabsTrigger>
                <TabsTrigger value="activity">Activity</TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value="overview" className="review-tab-content">
              <div className="section-heading">
                <div>
                  <h2>Extracted details</h2>
                  <p>
                    {editable
                      ? "Check the original and correct any misread values."
                      : "Latest recorded invoice values."}
                  </p>
                </div>
              </div>
              {detail.extraction?.result.extracted.notes && (
                <div className="ai-note">
                  <Sparkles size={16} />
                  <p>{detail.extraction.result.extracted.notes}</p>
                </div>
              )}
              {draft ? (
                <div className="fields-grid">
                  {fields.map((field) => (
                    <div
                      key={field.key}
                      className={
                        field.key === "vendor_name"
                          ? "field full-width"
                          : "field"
                      }
                    >
                      <label htmlFor={field.key}>
                        {field.label}
                        {lowConfidence.includes(field.key) && (
                          <span className="field-warning">Check source</span>
                        )}
                      </label>
                      <Input
                        id={field.key}
                        type={field.type || "text"}
                        step={field.type === "number" ? "any" : undefined}
                        value={draft[field.key] ?? ""}
                        disabled={!editable || busy}
                        onChange={(event) => {
                          const raw = event.target.value;
                          setDraft({
                            ...draft,
                            [field.key]:
                              raw === "" && field.nullable
                                ? null
                                : field.type === "number"
                                  ? raw === ""
                                    ? ""
                                    : Number(raw)
                                  : raw,
                          });
                        }}
                      />
                      {detail.extraction &&
                        draft[field.key] !==
                          detail.extraction.result.extracted.invoice[
                            field.key
                          ] && (
                          <small>
                            Originally extracted:{" "}
                            {String(
                              detail.extraction.result.extracted.invoice[
                                field.key
                              ] ?? "Not stated",
                            )}
                          </small>
                        )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-state">
                  <Loader2 size={24} />
                  <h3>
                    {detail.invoice.status === "failed"
                      ? "Processing could not finish"
                      : "Reading your invoice"}
                  </h3>
                  <p>
                    {detail.invoice.error ||
                      "Extracted details will appear here when processing finishes."}
                  </p>
                  {detail.invoice.status === "failed" && (
                    <Button
                      disabled={busy}
                      onClick={async () => {
                        setBusy(true);
                        try {
                          await api(`invoices/${id}/process`, {
                            method: "POST",
                          });
                          await load();
                        } catch (error) {
                          setError((error as Error).message);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      <RefreshCw />
                      Retry processing
                    </Button>
                  )}
                </div>
              )}
              {draft && (
                <div className="total-summary">
                  <span>Total incl. tax</span>
                  <strong className="money">
                    {money(draft.total, draft.currency)}
                  </strong>
                </div>
              )}
            </TabsContent>
            <TabsContent value="lines" className="review-tab-content">
              <h2>Invoice line items</h2>
              <p className="muted">
                Amounts as printed, excluding tax. Corrections are checked on
                the server.
              </p>
              {draft?.line_items.map((line, index) => (
                <div className="line-editor" key={index}>
                  <label htmlFor={`line-${index}`}>Item {index + 1}</label>
                  <Input
                    id={`line-${index}`}
                    value={line.description}
                    disabled={!editable || busy}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        line_items: draft.line_items.map((value, i) =>
                          i === index
                            ? { ...value, description: event.target.value }
                            : value,
                        ),
                      })
                    }
                  />
                  <div className="line-numbers">
                    {(["quantity", "unit_price", "amount"] as const).map(
                      (key) => (
                        <div key={key}>
                          <label htmlFor={`${key}-${index}`}>
                            {key === "quantity"
                              ? "Quantity"
                              : key === "unit_price"
                                ? "Unit price"
                                : "Line total"}
                          </label>
                          <Input
                            id={`${key}-${index}`}
                            type="number"
                            step="any"
                            value={Number.isNaN(line[key]) ? "" : line[key]}
                            disabled={!editable || busy}
                            onChange={(event) =>
                              setDraft({
                                ...draft,
                                line_items: draft.line_items.map((value, i) =>
                                  i === index
                                    ? {
                                        ...value,
                                        [key]:
                                          event.target.value === ""
                                            ? NaN
                                            : Number(event.target.value),
                                      }
                                    : value,
                                ),
                              })
                            }
                          />
                        </div>
                      ),
                    )}
                  </div>
                </div>
              ))}
            </TabsContent>
            <TabsContent value="matching" className="review-tab-content">
              <h2>Purchase order checks</h2>
              <p className="muted">
                {outcome?.po_number
                  ? `Purchase order ${outcome.po_number}${outcome.po_source === "agent" ? " · Suggested by AI; verify the reference" : ""}`
                  : "No purchase order matched."}
              </p>
              {issues.map((issue, index) => (
                <div className="exception-card" key={index}>
                  <CircleAlert size={17} />
                  <div>
                    <h3>{issue.code.replaceAll("_", " ")}</h3>
                    <p>{issue.message}</p>
                    <small>
                      {issue.route === "vendor"
                        ? "Supplier clarification required"
                        : "Review against the original document"}
                    </small>
                  </div>
                </div>
              ))}
              {outcome && issues.length === 0 && (
                <div className="success-banner">
                  <Check size={18} />
                  No exceptions reported by the matching rules.
                </div>
              )}
              {outcome?.lines.map((line, index) => (
                <div className="match-line" key={index}>
                  <h3>{line.description}</h3>
                  <dl>
                    <div>
                      <dt>Quantity billed</dt>
                      <dd>{line.billed_qty}</dd>
                    </div>
                    <div>
                      <dt>Quantity ordered</dt>
                      <dd>{line.ordered_qty ?? "Not available"}</dd>
                    </div>
                    <div>
                      <dt>Quantity received</dt>
                      <dd>{line.received_qty ?? "Not available"}</dd>
                    </div>
                    <div>
                      <dt>Invoice unit price</dt>
                      <dd>
                        {draft && money(line.invoice_price, draft.currency)}
                      </dd>
                    </div>
                    <div>
                      <dt>PO unit price</dt>
                      <dd>
                        {line.po_price != null && draft
                          ? money(line.po_price, draft.currency)
                          : "Not available"}
                      </dd>
                    </div>
                  </dl>
                </div>
              ))}
              {outcome?.draft && (
                <div className="draft-query">
                  <p className="eyebrow">SUGGESTED SUPPLIER EMAIL · NOT SENT</p>
                  <h3>{outcome.draft.subject}</h3>
                  <p>To: {outcome.draft.to || "Recipient not available"}</p>
                  <pre>{outcome.draft.body}</pre>
                  <p className="muted">
                    Send through your email client, then record the follow-up
                    here.
                  </p>
                </div>
              )}
            </TabsContent>
            <TabsContent value="activity" className="review-tab-content">
              <h2>Activity & review history</h2>
              <div className="activity-entry">
                <strong>Document received</strong>
                <small>{date(detail.invoice.uploaded_at)}</small>
              </div>
              {detail.extraction && (
                <div className="activity-entry">
                  <strong>Invoice extracted</strong>
                  <small>
                    {date(detail.extraction.created_at)} ·{" "}
                    {detail.extraction.model}
                  </small>
                </div>
              )}
              {detail.match && (
                <div className="activity-entry">
                  <strong>Matching completed</strong>
                  <small>
                    {date(detail.match.created_at)} ·{" "}
                    {detail.match.source === "correction"
                      ? "Reviewer corrections"
                      : "Original extraction"}
                  </small>
                  <p>
                    Recommendation:{" "}
                    {detail.match.outcome.decision.replaceAll("_", " ")}
                  </p>
                </div>
              )}
              {detail.reviews.map((review) => (
                <div className="activity-entry" key={review.id}>
                  <strong>
                    {actionLabels[review.action as Action] || review.action}
                  </strong>
                  <small>
                    {review.reviewer || "Reviewer"} · {date(review.created_at)}
                  </small>
                  {review.note && <p>{review.note}</p>}
                  {review.corrected_invoice && (
                    <details>
                      <summary>Recorded corrections</summary>
                      <pre>
                        {JSON.stringify(review.corrected_invoice, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              ))}
            </TabsContent>
          </Tabs>
          {editable && (
            <div className="review-footer">
              <p>
                {dirty
                  ? "Unsaved corrections. Save and recheck before deciding."
                  : issues.length
                    ? "Resolve flagged issues or record a reason for your decision."
                    : "Compare the source before confirming your decision."}
              </p>
              <div>
                <Button
                  variant="outline"
                  disabled={!dirty || !valid || busy}
                  onClick={() => setAction("correct")}
                >
                  <Save />
                  Save & recheck
                </Button>
                <Button
                  disabled={dirty || busy || !valid}
                  onClick={() => setAction("approve")}
                >
                  <Check />
                  Approve bill
                </Button>
                <Button
                  variant="ghost"
                  disabled={dirty || busy}
                  onClick={() => setAction("send_query")}
                >
                  Record follow-up
                </Button>
                <Button
                  variant="ghost"
                  disabled={dirty || busy}
                  onClick={() => setAction("reject")}
                >
                  <X />
                  Reject
                </Button>
              </div>
            </div>
          )}
        </section>
      </div>
      <Dialog
        open={action !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setAction(null);
        }}
      >
        <DialogContent>
          <DialogTitle>{action && actionLabels[action]}?</DialogTitle>
          <DialogDescription>
            {action === "correct"
              ? "Your corrections will be saved in review history and matching will run again. A clean match may automatically approve the bill under the current backend rules."
              : action === "approve"
                ? `Record approval for ${draft?.invoice_number}. This does not make a payment. Any remaining exceptions will stay in the audit history.`
                : action === "reject"
                  ? `Reject ${draft?.invoice_number} and remove it from the review queue.`
                  : "Record that this invoice needs supplier follow-up and remove it from the review queue. This does not send an email."}
          </DialogDescription>
          <label htmlFor="review-note">
            Review note
            {action === "approve" && issues.length
              ? " (required to explain exceptions)"
              : ""}
          </label>
          <Textarea
            id="review-note"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Explain the decision for your team…"
            disabled={busy}
          />
          {error && (
            <p role="alert" className="error-message">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setAction(null)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              onClick={submit}
              disabled={
                busy ||
                (action === "approve" && issues.length > 0 && !note.trim())
              }
            >
              {busy && <Loader2 className="animate-spin" />}Confirm
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
