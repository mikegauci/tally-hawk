"""Invoice extraction: an OpenAI model reads the PDF directly and fills in `ExtractedInvoice`."""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import openai
from pydantic import BaseModel

from tallyhawk.schema import ExtractedInvoice
from tallyhawk.validation import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    ValidationIssue,
    low_confidence_fields,
    needs_review,
    validate_invoice,
)

DEFAULT_MODEL = os.environ.get("TALLYHAWK_MODEL", "gpt-5.5")
DEFAULT_EFFORT = os.environ.get("TALLYHAWK_EFFORT", "medium")
EFFORT_LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]


# The functions below re-read the environment, so values from a .env loaded after import count.
def default_model() -> str:
    return os.environ.get("TALLYHAWK_MODEL") or DEFAULT_MODEL


def default_effort() -> str:
    return os.environ.get("TALLYHAWK_EFFORT") or DEFAULT_EFFORT


def load_dotenv(path: str | Path = ".env") -> None:
    """Load KEY=VALUE lines from a .env file into the environment, without overriding
    variables that are already set. Enough for this project's .env; no quoting rules."""
    path = Path(path)
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        value = value.strip().strip("'\"")
        if value:
            os.environ.setdefault(key.strip(), value)


def _env_price(name: str) -> float | None:
    value = os.environ.get(name)
    return float(value) if value else None


def estimate_cost(input_tokens: int, output_tokens: int) -> float | None:
    """USD cost from TALLYHAWK_PRICE_INPUT_PER_MTOK / TALLYHAWK_PRICE_OUTPUT_PER_MTOK (USD per
    million tokens, from OpenAI's pricing page for the model you run). Read at call time, so a
    .env loaded after import still counts. None when either price is unset."""
    price_in = _env_price("TALLYHAWK_PRICE_INPUT_PER_MTOK")
    price_out = _env_price("TALLYHAWK_PRICE_OUTPUT_PER_MTOK")
    if price_in is None or price_out is None:
        return None
    return round((input_tokens * price_in + output_tokens * price_out) / 1_000_000, 6)


SYSTEM_PROMPT = """\
You extract data from supplier invoices for an accounts payable team. The data you \
return is posted to the accounting system and matched against purchase orders, so \
copy values exactly as printed: do not correct the supplier's arithmetic, and do not \
invent values that are not on the document (use null where the schema allows it).

Dates are returned as ISO dates (YYYY-MM-DD) whatever format the invoice uses. \
Amounts are plain numbers without currency symbols or thousands separators. If an \
invoice uses a decimal comma (1.234,56) convert it to 1234.56.

Score your confidence per field honestly; a reviewer only checks fields you mark \
below 0.9, so overconfidence lets errors through."""

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class ExtractionError(RuntimeError):
    pass


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class ExtractionResult(BaseModel):
    extracted: ExtractedInvoice
    issues: list[ValidationIssue]
    low_confidence_fields: list[str]
    needs_review: bool
    model: str
    usage: Usage
    latency_s: float


def _document_part(data: bytes, media_type: str) -> dict:
    data_url = f"data:{media_type};base64,{base64.standard_b64encode(data).decode('ascii')}"
    if media_type == "application/pdf":
        return {"type": "input_file", "filename": "invoice.pdf", "file_data": data_url}
    return {"type": "input_image", "image_url": data_url, "detail": "high"}


def extract_invoice(
    data: bytes,
    media_type: str = "application/pdf",
    *,
    client: openai.OpenAI | None = None,
    model: str | None = None,
    effort: str | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> ExtractionResult:
    client = client or openai.OpenAI()
    model, effort = model or default_model(), effort or default_effort()
    started = time.perf_counter()
    response = client.responses.parse(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=[
            {
                "role": "user",
                "content": [
                    _document_part(data, media_type),
                    {"type": "input_text", "text": "Extract this invoice."},
                ],
            }
        ],
        text_format=ExtractedInvoice,
        reasoning={"effort": effort},
        max_output_tokens=16000,
        store=False,
    )
    latency = time.perf_counter() - started

    if response.status == "incomplete":
        reason = response.incomplete_details.reason if response.incomplete_details else "unknown"
        raise ExtractionError(f"Response incomplete ({reason}) before the extraction was finished.")
    refusals = [
        part.refusal
        for item in response.output
        if item.type == "message"
        for part in item.content
        if part.type == "refusal"
    ]
    if refusals:
        raise ExtractionError(f"Model declined to extract: {refusals[0]}")
    extracted = response.output_parsed
    if extracted is None:
        raise ExtractionError(f"No structured output returned (status={response.status}).")

    issues = validate_invoice(extracted.invoice)
    low = low_confidence_fields(extracted, confidence_threshold)
    return ExtractionResult(
        extracted=extracted,
        issues=issues,
        low_confidence_fields=low,
        needs_review=needs_review(issues, low),
        model=response.model,
        usage=Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=estimate_cost(response.usage.input_tokens, response.usage.output_tokens),
        ),
        latency_s=round(latency, 2),
    )


def extract_file(path: str | Path, **kwargs) -> ExtractionResult:
    path = Path(path)
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise ValueError(f"Unsupported file type: {path.suffix} (expected one of {sorted(MEDIA_TYPES)})")
    return extract_invoice(path.read_bytes(), media_type, **kwargs)
