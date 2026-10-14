"""Draft the email that goes back to a supplier when an invoice can't be paid as billed.

Drafts are never sent automatically: they go to a person with the invoice, who edits and
sends them. `template_drafter` needs no API call; `LLMDrafter` writes a friendlier email
from the same facts.
"""

from __future__ import annotations

from collections.abc import Callable

import openai
from pydantic import BaseModel, Field

from tallyhawk.extract import DEFAULT_MODEL, Usage, estimate_cost
from tallyhawk.matching import MatchIssue, Route
from tallyhawk.procurement import Vendor
from tallyhawk.schema import InvoiceData

DRAFT_PROMPT = """\
You write emails from a company's accounts payable team to a supplier about an invoice \
that can't be paid as billed. Be polite, short and specific: quote the invoice number, \
the PO number if there is one, and each problem with the figures given. Say what the \
supplier needs to do (for example, send a credit note or a corrected invoice, or confirm \
the PO number). Use only the facts provided; never invent amounts, dates or names. Sign \
off as "Accounts Payable". No placeholders in square brackets."""


class VendorQuery(BaseModel):
    to: str | None = Field(description="Supplier email address, or null if unknown.")
    subject: str
    body: str
    usage: Usage | None = None


Drafter = Callable[[InvoiceData, Vendor | None, str | None, list[MatchIssue]], VendorQuery]


def _facts(issues: list[MatchIssue]) -> list[str]:
    return [i.message for i in issues if i.route is Route.VENDOR]


def template_drafter(
    invoice: InvoiceData, vendor: Vendor | None, po_number: str | None, issues: list[MatchIssue]
) -> VendorQuery:
    name = vendor.name if vendor else invoice.vendor_name
    ref = f"invoice {invoice.invoice_number}" + (f" (PO {po_number})" if po_number else "")
    problems = "\n".join(f"- {fact}" for fact in _facts(issues))
    body = (
        f"Hello {name},\n\n"
        f"We can't process {ref} dated {invoice.invoice_date} for "
        f"{invoice.currency} {invoice.total:,.2f} as billed:\n\n{problems}\n\n"
        "Could you send a corrected invoice or a credit note, or let us know if we've missed something?\n\n"
        "Kind regards,\nAccounts Payable"
    )
    return VendorQuery(to=vendor.email if vendor else None, subject=f"Query on {ref}", body=body)


class _Draft(BaseModel):
    subject: str
    body: str


class LLMDrafter:
    def __init__(self, *, client: openai.OpenAI | None = None, model: str = DEFAULT_MODEL, effort: str = "low"):
        self.client = client or openai.OpenAI()
        self.model = model
        self.effort = effort

    def __call__(
        self, invoice: InvoiceData, vendor: Vendor | None, po_number: str | None, issues: list[MatchIssue]
    ) -> VendorQuery:
        from tallyhawk.tracing import span

        with span("draft_supplier_query", as_type="generation", metadata={"model": self.model}):
            return self._draft(invoice, vendor, po_number, issues)

    def _draft(
        self, invoice: InvoiceData, vendor: Vendor | None, po_number: str | None, issues: list[MatchIssue]
    ) -> VendorQuery:
        facts = "\n".join(f"- {fact}" for fact in _facts(issues))
        prompt = (
            f"Supplier: {vendor.name if vendor else invoice.vendor_name}\n"
            f"Invoice {invoice.invoice_number} dated {invoice.invoice_date}, "
            f"total {invoice.currency} {invoice.total:,.2f}\n"
            f"PO: {po_number or 'none on file'}\n"
            f"Problems:\n{facts}"
        )
        response = self.client.responses.parse(
            model=self.model,
            instructions=DRAFT_PROMPT,
            input=[{"role": "user", "content": prompt}],
            text_format=_Draft,
            reasoning={"effort": self.effort},
            max_output_tokens=4000,
            store=False,
        )
        draft = response.output_parsed
        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=estimate_cost(response.usage.input_tokens, response.usage.output_tokens),
        )
        if draft is None:  # refusal or truncation: fall back to the template so a person still gets a draft
            fallback = template_drafter(invoice, vendor, po_number, issues)
            return fallback.model_copy(update={"usage": usage})
        return VendorQuery(to=vendor.email if vendor else None, subject=draft.subject, body=draft.body, usage=usage)
