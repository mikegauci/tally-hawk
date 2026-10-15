"use client";
import { Bot, Cpu, FileScan } from "lucide-react";
import type { InvoiceDetail, PipelineStep } from "@/lib/types";
// What each LangGraph node does, in plain words (src/tallyhawk/workflow.py).
const labels: Record<string, string> = {
  check: "Validate the extracted fields",
  lookup: "Look up the supplier and PO",
  investigate: "AI agent searches for the PO",
  match: "Three-way match: PO, goods receipt, invoice",
  decide: "Decide: approve, review or query",
  draft_query: "Draft the supplier email",
  handoff: "Hand off to a person",
};
const decisions: Record<string, string> = {
  approve: "auto-approve",
  review: "send to a reviewer",
  vendor_query: "query the supplier",
};
type Row = PipelineStep & { label: string; engine: string; ai: boolean };
function duration(ms: number) {
  if (ms < 0.1) return "<0.1 ms";
  if (ms < 1000) return `${ms.toFixed(ms < 10 ? 1 : 0)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
function cost(usd: number | null) {
  return usd === null ? "cost not tracked" : `$${usd.toFixed(4)}`;
}
export function PipelineTrace({ detail }: { detail: InvoiceDetail }) {
  const extraction = detail.extraction;
  const outcome = detail.match?.outcome;
  const rows: Row[] = [];
  if (extraction && detail.match?.source !== "correction") {
    const usage = extraction.result.usage;
    rows.push({
      name: "extract",
      label: "Read the invoice (PDF or scan)",
      engine: extraction.model,
      ai: true,
      summary: [
        `${extraction.result.low_confidence_fields.length} low-confidence field(s)`,
        `${extraction.result.issues?.length ?? 0} validation issue(s)`,
      ],
      duration_ms: (extraction.result.latency_s ?? 0) * 1000,
      llm_calls: 1,
      input_tokens: usage?.input_tokens ?? 0,
      output_tokens: usage?.output_tokens ?? 0,
      cost_usd: usage?.cost_usd ?? null,
    });
  }
  for (const step of outcome?.steps ?? [])
    rows.push({
      ...step,
      summary:
        step.name === "decide"
          ? step.summary.map((value) => decisions[value] ?? value)
          : step.summary,
      label: labels[step.name] ?? step.name,
      ai: step.llm_calls > 0,
      engine:
        step.llm_calls > 0
          ? (extraction?.model ?? "LLM")
          : step.name === "draft_query"
            ? "Template"
            : "Rules",
    });
  const ai = rows.filter((row) => row.ai);
  const costs = ai.map((row) => row.cost_usd);
  const total = {
    ms: rows.reduce((sum, row) => sum + row.duration_ms, 0),
    calls: rows.reduce((sum, row) => sum + row.llm_calls, 0),
    tokens: rows.reduce(
      (sum, row) => sum + row.input_tokens + row.output_tokens,
      0,
    ),
    cost:
      costs.length && !costs.includes(null)
        ? costs.reduce((a, b) => a! + b!, 0)
        : null,
  };
  return (
    <>
      <h2>Pipeline trace</h2>
      <p className="muted">
        Every step this invoice went through. Approve, review and query
        decisions are made by deterministic rules; the model only reads the
        invoice, looks for a missing PO and drafts supplier emails.
      </p>
      {detail.match?.source === "correction" && (
        <p className="muted">
          Showing the re-match after a reviewer corrected fields, so there is no
          extraction step.
        </p>
      )}
      {rows.length > 0 && (
        <p className="pipeline-total" aria-label="Pipeline totals">
          <strong>{duration(total.ms)}</strong> in total · {total.calls} model
          call{total.calls === 1 ? "" : "s"} ·{" "}
          {total.tokens.toLocaleString("en")} tokens · {cost(total.cost)}
        </p>
      )}
      <ol className="pipeline-steps">
        {rows.map((row, index) => (
          <li key={`${row.name}-${index}`} className={row.ai ? "is-ai" : ""}>
            <span className="pipeline-icon" aria-hidden>
              {row.name === "extract" ? (
                <FileScan size={15} />
              ) : row.ai ? (
                <Bot size={15} />
              ) : (
                <Cpu size={15} />
              )}
            </span>
            <div>
              <div className="pipeline-heading">
                <strong>{row.label}</strong>
                <span className="pipeline-engine">{row.engine}</span>
              </div>
              {row.summary.length > 0 && <p>{row.summary.join(" · ")}</p>}
              <small>
                {duration(row.duration_ms)}
                {row.llm_calls > 0 &&
                  ` · ${(row.input_tokens + row.output_tokens).toLocaleString("en")} tokens (${row.input_tokens.toLocaleString("en")} in, ${row.output_tokens.toLocaleString("en")} out) · ${cost(row.cost_usd)}`}
              </small>
            </div>
          </li>
        ))}
      </ol>
      {outcome && !outcome.steps?.length && (
        <div className="pipeline-legacy">
          <p className="muted">
            This invoice was matched before step timing was recorded. The
            matching steps were:
          </p>
          <ul>
            {outcome.trace.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {!extraction && !outcome && (
        <p className="muted">This invoice hasn&apos;t been processed yet.</p>
      )}
    </>
  );
}
