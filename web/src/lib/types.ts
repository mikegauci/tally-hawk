export type InvoiceStatus =
  | "uploaded"
  | "processing"
  | "approved"
  | "awaiting_review"
  | "vendor_queried"
  | "rejected"
  | "failed";
export type InvoiceRecord = {
  id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  status: InvoiceStatus;
  error: string | null;
  uploaded_at: string;
  updated_at: string;
};
export type QueueItem = {
  invoice_id: string;
  filename: string;
  uploaded_at: string;
  decision: "approve" | "review" | "vendor_query";
  vendor_name: string;
  invoice_number: string;
  total: number;
  currency: string;
  po_number: string | null;
  issue_count: number;
};
export type InvoiceData = {
  vendor_name: string;
  vendor_tax_id: string | null;
  invoice_number: string;
  invoice_date: string;
  due_date: string | null;
  po_number: string | null;
  currency: string;
  subtotal: number;
  tax_rate: number | null;
  tax_amount: number;
  total: number;
  line_items: {
    description: string;
    quantity: number;
    unit_price: number;
    amount: number;
  }[];
};
export type InvoiceDetail = {
  invoice: InvoiceRecord;
  extraction: {
    model: string;
    result: {
      extracted: { invoice: InvoiceData; notes: string | null };
      low_confidence_fields: string[];
      issues?: { code: string; message: string }[];
      usage?: Usage;
      latency_s?: number;
    };
    created_at: string;
  } | null;
  match: {
    source: string;
    invoice: InvoiceData;
    created_at: string;
    outcome: {
      decision: string;
      po_number: string | null;
      po_source: string | null;
      issues: { code: string; message: string; route: string }[];
      lines: {
        invoice_line: number;
        description: string;
        billed_qty: number;
        ordered_qty: number | null;
        received_qty: number | null;
        invoice_price: number;
        po_price: number | null;
        issues: string[];
      }[];
      draft: { to: string | null; subject: string; body: string } | null;
      trace: string[];
      // Absent on invoices matched before per-step timing was recorded.
      steps?: PipelineStep[];
    };
  } | null;
  reviews: {
    id: number;
    action: string;
    reviewer: string | null;
    note: string | null;
    created_at: string;
    corrected_invoice: InvoiceData | null;
  }[];
};
export type Usage = {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
};
export type PipelineStep = {
  name: string;
  summary: string[];
  duration_ms: number;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
};
