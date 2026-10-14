"""Extraction against a mocked OpenAI Responses API: request shape, parsing and error paths."""

import json

import httpx2
import openai
import pytest
from conftest import make_extracted

from tallyhawk import extract
from tallyhawk.extract import ExtractionError, extract_invoice


def mock_client(invoice, *, outcome="ok", captured=None, confidence=0.98):
    body = make_extracted(invoice, confidence).model_dump_json()

    def handler(request):
        if captured is not None:
            captured.update(json.loads(request.content))
        if outcome == "refusal":
            content = [{"type": "refusal", "refusal": "I can't help with that."}]
        else:
            content = [{"type": "output_text", "text": body, "annotations": []}]
        return httpx2.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1760000000,
                "status": "incomplete" if outcome == "incomplete" else "completed",
                "incomplete_details": {"reason": "max_output_tokens"} if outcome == "incomplete" else None,
                "model": "gpt-5.5",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_test",
                        "status": "completed",
                        "role": "assistant",
                        "content": content,
                    }
                ],
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
                "usage": {
                    "input_tokens": 3000,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 500,
                    "output_tokens_details": {"reasoning_tokens": 200},
                    "total_tokens": 3500,
                },
            },
        )

    return openai.OpenAI(api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))


def test_extracts_and_validates(invoice, monkeypatch):
    monkeypatch.setenv("TALLYHAWK_PRICE_INPUT_PER_MTOK", "2.0")
    monkeypatch.setenv("TALLYHAWK_PRICE_OUTPUT_PER_MTOK", "10.0")
    captured = {}
    result = extract_invoice(b"%PDF-1.4", client=mock_client(invoice, captured=captured))

    assert result.extracted.invoice == invoice
    assert result.issues == [] and not result.needs_review
    assert result.usage.cost_usd == pytest.approx((3000 * 2 + 500 * 10) / 1e6)

    content = captured["input"][0]["content"]
    assert content[0]["type"] == "input_file"
    assert content[0]["file_data"].startswith("data:application/pdf;base64,")
    assert captured["reasoning"] == {"effort": "medium"}
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True


def test_cost_is_none_without_prices(invoice, monkeypatch):
    monkeypatch.delenv("TALLYHAWK_PRICE_INPUT_PER_MTOK", raising=False)
    result = extract_invoice(b"%PDF-1.4", client=mock_client(invoice))
    assert result.usage.cost_usd is None and result.usage.input_tokens == 3000


def test_low_confidence_flags_review(invoice):
    result = extract_invoice(b"%PDF-1.4", client=mock_client(invoice, confidence=0.5))
    assert result.needs_review
    assert "total" in result.low_confidence_fields


def test_refusal_raises(invoice):
    with pytest.raises(ExtractionError, match="declined"):
        extract_invoice(b"%PDF-1.4", client=mock_client(invoice, outcome="refusal"))


def test_incomplete_raises(invoice):
    with pytest.raises(ExtractionError, match="max_output_tokens"):
        extract_invoice(b"%PDF-1.4", client=mock_client(invoice, outcome="incomplete"))


def test_load_dotenv_sets_prices_without_overriding(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nTALLYHAWK_PRICE_INPUT_PER_MTOK=5\nexport TALLYHAWK_PRICE_OUTPUT_PER_MTOK='30'\nEMPTY=\n")
    monkeypatch.setenv("TALLYHAWK_PRICE_INPUT_PER_MTOK", "")  # so monkeypatch restores it afterwards
    monkeypatch.delenv("TALLYHAWK_PRICE_INPUT_PER_MTOK")
    monkeypatch.setenv("TALLYHAWK_PRICE_OUTPUT_PER_MTOK", "40")
    extract.load_dotenv(env)
    assert extract.estimate_cost(1_000_000, 1_000_000) == 45.0  # 5 from .env + 40 already set
