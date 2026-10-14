"""Where uploaded invoice files live: Supabase Storage in production, a local folder otherwise."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

INVOICE_BUCKET = "invoices"


class FileStore(Protocol):
    def put(self, path: str, data: bytes, media_type: str) -> None: ...

    def get(self, path: str) -> bytes: ...


class LocalFileStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _resolve(self, path: str) -> Path:
        target = (self.root / path).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError(f"Path escapes the storage folder: {path}")
        return target

    def put(self, path: str, data: bytes, media_type: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def get(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()


class SupabaseFileStore:
    """Supabase Storage over its REST API, using the service role key (server side only:
    that key bypasses row level security, so it must never reach a browser)."""

    def __init__(self, url: str, service_key: str, bucket: str = INVOICE_BUCKET, client: httpx.Client | None = None):
        self.base = f"{url.rstrip('/')}/storage/v1/object/{bucket}"
        self.client = client or httpx.Client(
            headers={"Authorization": f"Bearer {service_key}", "apikey": service_key}, timeout=60
        )

    def put(self, path: str, data: bytes, media_type: str) -> None:
        response = self.client.post(
            f"{self.base}/{quote(path)}", content=data, headers={"Content-Type": media_type, "x-upsert": "true"}
        )
        response.raise_for_status()

    def get(self, path: str) -> bytes:
        response = self.client.get(f"{self.base}/{quote(path)}")
        response.raise_for_status()
        return response.content


def file_store_from_env() -> FileStore:
    """Supabase Storage when SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set, else a local
    folder (TALLYHAWK_STORAGE_DIR, default ./storage)."""
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if url and key:
        return SupabaseFileStore(url, key)
    return LocalFileStore(os.environ.get("TALLYHAWK_STORAGE_DIR", "storage"))
