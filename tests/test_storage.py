"""File stores: local folder, and Supabase Storage over a mocked HTTP transport."""

import json

import httpx
import pytest

from tallyhawk.storage import LocalFileStore, SupabaseFileStore


def test_local_store_round_trip_and_delete(tmp_path):
    store = LocalFileStore(tmp_path)
    store.put("a/one.pdf", b"1", "application/pdf")
    assert store.get("a/one.pdf") == b"1"
    store.delete(["a/one.pdf", "a/missing.pdf"])  # missing files are fine
    assert not (tmp_path / "a" / "one.pdf").exists()
    with pytest.raises(ValueError):
        store.delete(["../outside.pdf"])


def test_supabase_delete_removes_paths_in_batches():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    store = SupabaseFileStore(
        "https://x.supabase.co", "key", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    store.delete([f"{i}/f.pdf" for i in range(150)])
    assert [r.method for r in requests] == ["DELETE", "DELETE"]
    assert str(requests[0].url) == "https://x.supabase.co/storage/v1/object/invoices"
    assert [len(json.loads(r.content)["prefixes"]) for r in requests] == [100, 50]
