"""Optional Langfuse tracing (no-op when LANGFUSE_* env vars are unset)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_invoice_id: ContextVar[str | None] = ContextVar("invoice_id", default=None)


def set_invoice_id(invoice_id: str | None) -> None:
    _invoice_id.set(invoice_id)


def current_invoice_id() -> str | None:
    return _invoice_id.get()


def tracing_enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


@contextmanager
def span(name: str, *, as_type: str = "span", metadata: dict[str, Any] | None = None) -> Iterator[Any]:
    if not tracing_enabled():
        yield None
        return
    from langfuse import get_client

    meta = dict(metadata or {})
    if invoice_id := current_invoice_id():
        meta.setdefault("invoice_id", invoice_id)
    client = get_client()
    with client.start_as_current_observation(name=name, as_type=as_type, metadata=meta) as observation:
        yield observation


def record_generation(
    observation: Any,
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None,
) -> None:
    if observation is None:
        return
    observation.update(
        model=model,
        usage={
            "input": input_tokens,
            "output": output_tokens,
            "total": input_tokens + output_tokens,
        },
        metadata={"cost_usd": cost_usd},
    )
