"""EvidenceStore: binary evidence in object storage, metadata in Postgres."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any, Protocol


class EvidenceStore(Protocol):
    name: str

    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def health(self) -> bool: ...


def _safe_key(key: str) -> str:
    if ".." in key.split("/") or key.startswith("/"):
        raise ValueError("invalid object key")
    return key


class LocalEvidenceStore:
    """Filesystem store for tests and minimal local runs."""

    name = "local"

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        return self._root / _safe_key(key)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)

    async def health(self) -> bool:
        await asyncio.to_thread(self._root.mkdir, parents=True, exist_ok=True)
        return True


class MinioEvidenceStore:
    """S3-compatible store (MinIO locally). The ``minio`` SDK is confined to this class."""

    name = "minio"

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from minio import Minio

            client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self._client = client
        self._bucket = bucket
        self._bucket_ready = False

    async def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        exists = await asyncio.to_thread(self._client.bucket_exists, self._bucket)
        if not exists:
            await asyncio.to_thread(self._client.make_bucket, self._bucket)
        self._bucket_ready = True

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self._ensure_bucket()
        await asyncio.to_thread(
            self._client.put_object,
            self._bucket,
            _safe_key(key),
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )

    async def get(self, key: str) -> bytes:
        def _read() -> bytes:
            response = self._client.get_object(self._bucket, _safe_key(key))
            try:
                data: bytes = response.read()
                return data
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(_read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.remove_object, self._bucket, _safe_key(key))

    async def health(self) -> bool:
        try:
            await self._ensure_bucket()
            return True
        except Exception:
            return False
