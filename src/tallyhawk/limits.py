"""Caps that keep the public demo's OpenAI spend bounded.

Each upload (and each re-run of processing) is counted per browser session and per UTC day
in `demo_usage`. The caps are off unless `TALLYHAWK_DEMO_SESSION_LIMIT` and/or
`TALLYHAWK_DEMO_DAILY_LIMIT` are set, so local use is unlimited. The session id comes from
the web app's signed session cookie, forwarded by its server-side proxy; anyone holding the
API key could send any id, which is fine because the daily cap is the real backstop.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import openai
from psycopg_pool import ConnectionPool

SESSION_HEADER = "X-TallyHawk-Session"
_SESSION_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
ANONYMOUS = "anonymous"

QUOTA_MESSAGE = (
    "The demo's OpenAI budget for this month is used up, so new invoices can't be read right now. "
    "Everything already in the workspace is still there to explore."
)


class LimitReached(RuntimeError):
    """An upload would go over a demo cap; the message is safe to show the visitor."""


def _env_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    return int(value) if value else None


@dataclass(frozen=True)
class DemoLimits:
    per_session: int | None = None
    per_day: int | None = None

    @classmethod
    def from_env(cls) -> DemoLimits:
        return cls(_env_int("TALLYHAWK_DEMO_SESSION_LIMIT"), _env_int("TALLYHAWK_DEMO_DAILY_LIMIT"))

    @property
    def enabled(self) -> bool:
        return self.per_session is not None or self.per_day is not None


def session_id(header: str | None) -> str:
    """The forwarded session id, or `anonymous` when it is missing or malformed."""
    return header if header and _SESSION_ID.match(header) else ANONYMOUS


def claim_upload(pool: ConnectionPool, limits: DemoLimits, session: str) -> None:
    """Count one upload against the caps, or raise `LimitReached` without counting it."""
    if not limits.enabled:
        return
    day = datetime.now(UTC).date()
    with pool.connection() as conn, conn.transaction():
        # Serialise claims so two uploads at once can't both take the last slot.
        conn.execute("select pg_advisory_xact_lock(hashtext('tallyhawk.demo_usage'))")
        total = conn.execute("select coalesce(sum(uploads), 0) as n from demo_usage where day = %s", (day,)).fetchone()[
            "n"
        ]
        if limits.per_day is not None and total >= limits.per_day:
            raise LimitReached(
                f"The demo has read its {limits.per_day} invoices for today across all visitors. "
                "Uploads open again tomorrow; everything already in the workspace is still there to explore."
            )
        if limits.per_session is not None and session != ANONYMOUS:
            row = conn.execute(
                "select uploads from demo_usage where session_id = %s and day = %s", (session, day)
            ).fetchone()
            if row and row["uploads"] >= limits.per_session:
                raise LimitReached(
                    f"You've reached the demo limit of {limits.per_session} invoices per visit. "
                    "Everything already in the workspace is still there to explore."
                )
        conn.execute(
            """
            insert into demo_usage (session_id, day, uploads) values (%s, %s, 1)
            on conflict (session_id, day) do update set uploads = demo_usage.uploads + 1
            """,
            (session, day),
        )


def is_quota_error(exc: BaseException) -> bool:
    """True when OpenAI refused the call because the account or project budget is used up."""
    return isinstance(exc, openai.RateLimitError) and getattr(exc, "code", None) == "insufficient_quota"
