// Test-only service. Never loaded by the application or a deployment.
import { createServer } from "node:http";
const id = "11111111-1111-4111-8111-111111111111";
const invoice = {
  id,
  filename: "supplier-invoice.pdf",
  media_type: "application/pdf",
  size_bytes: 1000,
  status: "awaiting_review",
  error: null,
  uploaded_at: "2026-10-14T09:00:00Z",
  updated_at: "2026-10-14T09:00:00Z",
};
const data = {
  vendor_name: "Kestrel Building Materials Ltd",
  vendor_tax_id: "MT12345678",
  invoice_number: "INV-2026-104",
  invoice_date: "2026-10-13",
  due_date: "2026-11-13",
  po_number: "PO-2041",
  currency: "EUR",
  subtotal: 100,
  tax_rate: 18,
  tax_amount: 18,
  total: 118,
  line_items: [
    {
      description: "Safety equipment",
      quantity: 2,
      unit_price: 50,
      amount: 100,
    },
  ],
};
// Requests left to answer like a sleeping Render service (an HTML 503).
let asleep = 0;
// Demo upload cap per forwarded session id, like src/tallyhawk/limits.py.
let cap = Infinity,
  uploads = {};
let current = structuredClone(invoice),
  corrected = structuredClone(data),
  reviews = [];
function detail() {
  return {
    invoice: current,
    extraction: {
      model: "test-model",
      created_at: invoice.uploaded_at,
      result: {
        extracted: {
          invoice: data,
          notes: "Verify the quantity against the original document.",
        },
        low_confidence_fields: ["po_number"],
      },
    },
    match: {
      source: reviews.some((r) => r.action === "correct")
        ? "correction"
        : "extraction",
      invoice: corrected,
      created_at: invoice.uploaded_at,
      outcome: {
        decision: "vendor_query",
        po_number: data.po_number,
        po_source: "printed",
        issues: [
          {
            code: "quantity_mismatch",
            route: "vendor",
            message:
              "Invoice bills 2 units; the purchase order allows 1 unit. Difference: 1 unit.",
          },
        ],
        lines: [
          {
            invoice_line: 0,
            description: "Safety equipment",
            billed_qty: 2,
            ordered_qty: 1,
            received_qty: 1,
            invoice_price: 50,
            po_price: 50,
            issues: ["quantity_mismatch"],
          },
        ],
        draft: {
          to: "supplier@example.test",
          subject: "Please clarify INV-2026-104",
          body: "Please confirm the quantity billed against PO-2041.",
        },
        trace: [],
      },
    },
    reviews,
  };
}
createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const parts = [];
  for await (const chunk of req) parts.push(chunk);
  const body = Buffer.concat(parts);
  res.setHeader("Content-Type", "application/json");
  if (url.pathname === "/reset") {
    current = structuredClone(invoice);
    corrected = structuredClone(data);
    reviews = [];
    asleep = 0;
    cap = Infinity;
    uploads = {};
    res.end("{}");
    return;
  }
  if (url.pathname === "/cap") {
    cap = Number(url.searchParams.get("uploads"));
    res.end("{}");
    return;
  }
  if (url.pathname === "/sleep") {
    asleep = Number(url.searchParams.get("requests"));
    res.end("{}");
    return;
  }
  if (asleep > 0) {
    asleep -= 1;
    res.setHeader("Content-Type", "text/html");
    res.writeHead(503).end("<html>Service waking up</html>");
    return;
  }
  if (req.headers.authorization !== "Bearer test-api-key") {
    res.writeHead(401).end("{}");
    return;
  }
  if (url.pathname === "/review-queue") {
    res.end(
      JSON.stringify(
        current.status === "awaiting_review"
          ? [
              {
                invoice_id: id,
                filename: invoice.filename,
                uploaded_at: invoice.uploaded_at,
                decision: "vendor_query",
                ...corrected,
                issue_count: 1,
              },
            ]
          : [],
      ),
    );
    return;
  }
  if (url.pathname === "/invoices" && req.method === "GET") {
    res.end(JSON.stringify([current]));
    return;
  }
  if (url.pathname === "/invoices" && req.method === "POST") {
    const session = req.headers["x-tallyhawk-session"];
    if (!/^[0-9a-f-]{36}$/.test(session || "")) {
      res.writeHead(400).end(JSON.stringify({ detail: "No session id." }));
      return;
    }
    uploads[session] = (uploads[session] || 0) + 1;
    if (uploads[session] > cap) {
      res.writeHead(429).end(
        JSON.stringify({
          detail: `You've reached the demo limit of ${cap} invoices per visit.`,
        }),
      );
      return;
    }
    res.writeHead(202).end(JSON.stringify({ ...current, status: "uploaded" }));
    return;
  }
  if (url.pathname.endsWith("/review")) {
    const request = JSON.parse(body);
    if (current.status !== "awaiting_review") {
      res
        .writeHead(409)
        .end(
          JSON.stringify({ detail: "This bill has already been reviewed." }),
        );
      return;
    }
    reviews.push({
      ...request,
      id: reviews.length + 1,
      created_at: invoice.uploaded_at,
    });
    if (request.action === "correct") corrected = request.corrected_invoice;
    else
      current.status = {
        approve: "approved",
        reject: "rejected",
        send_query: "vendor_queried",
      }[request.action];
    res.end(JSON.stringify(detail()));
    return;
  }
  if (url.pathname.endsWith("/file")) {
    res.setHeader("Content-Type", "application/pdf");
    res.end("%PDF-1.4\n%%EOF");
    return;
  }
  if (url.pathname === `/invoices/${id}`) {
    res.end(JSON.stringify(detail()));
    return;
  }
  res.writeHead(404).end("{}");
}).listen(8109, "127.0.0.1");
