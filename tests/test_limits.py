"""Demo caps helpers that need no database (the counting itself is tested in test_api.py)."""

import httpx2
import openai

from tallyhawk.limits import ANONYMOUS, DemoLimits, is_quota_error, session_id
from tallyhawk.service import failure_reason


def rate_limit_error(code: str) -> openai.RateLimitError:
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx2.Response(429, request=request)
    return openai.RateLimitError("rate limited", response=response, body={"code": code})


def test_quota_errors_are_told_apart_from_ordinary_rate_limits():
    assert is_quota_error(rate_limit_error("insufficient_quota"))
    assert not is_quota_error(rate_limit_error("rate_limit_exceeded"))
    assert not is_quota_error(RuntimeError("insufficient_quota"))


def test_failed_invoices_explain_a_used_up_budget_plainly():
    assert "budget" in failure_reason(rate_limit_error("insufficient_quota"))
    assert failure_reason(RuntimeError("model unavailable")) == "RuntimeError: model unavailable"


def test_session_ids_are_validated():
    assert session_id("3f2c9a1e-8b7d-4c6e-9f0a-1b2c3d4e5f60") == "3f2c9a1e-8b7d-4c6e-9f0a-1b2c3d4e5f60"
    assert session_id(None) == ANONYMOUS
    assert session_id("x") == ANONYMOUS
    assert session_id("drop table; --") == ANONYMOUS


def test_limits_are_off_unless_configured(monkeypatch):
    monkeypatch.delenv("TALLYHAWK_DEMO_SESSION_LIMIT", raising=False)
    monkeypatch.delenv("TALLYHAWK_DEMO_DAILY_LIMIT", raising=False)
    assert not DemoLimits.from_env().enabled
    monkeypatch.setenv("TALLYHAWK_DEMO_DAILY_LIMIT", "50")
    assert DemoLimits.from_env() == DemoLimits(per_session=None, per_day=50)
