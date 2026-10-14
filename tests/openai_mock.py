"""A fake OpenAI Responses API: serves canned responses in order and records each request."""

import json

import httpx2
import openai


def response_body(output: list[dict], input_tokens: int = 1000, output_tokens: int = 100) -> dict:
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1760000000,
        "status": "completed",
        "incomplete_details": None,
        "model": "gpt-5.5",
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": input_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": output_tokens,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": input_tokens + output_tokens,
        },
    }


def function_call(name: str, arguments: dict, n: int = 1) -> dict:
    return {
        "type": "function_call",
        "id": f"fc_{name}_{n}",
        "call_id": f"call_{name}_{n}",
        "name": name,
        "arguments": json.dumps(arguments),
        "status": "completed",
    }


def message(text: str) -> dict:
    return {
        "type": "message",
        "id": "msg_test",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def scripted_client(outputs: list[list[dict]], requests: list[dict] | None = None) -> openai.OpenAI:
    """Each call to the API returns the next entry of `outputs` as the response's output items."""
    queue = list(outputs)

    def handler(request):
        if requests is not None:
            requests.append(json.loads(request.content))
        return httpx2.Response(200, json=response_body(queue.pop(0)))

    return openai.OpenAI(api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
