"""Upload validation: size limit, content-type allowlist and magic-byte checks."""

from __future__ import annotations

import hashlib

_MAGIC: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "application/pdf": (b"%PDF-",),
    "audio/wav": (b"RIFF",),
    "audio/mpeg": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
}


class EvidenceValidationError(ValueError):
    def __init__(self, reason: str, *, status_code: int = 422) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


def validate_upload(data: bytes, content_type: str, *, allowed: list[str], max_bytes: int) -> str:
    """Validate and return the SHA-256 checksum."""
    base_type = content_type.split(";")[0].strip().lower()
    if base_type not in allowed:
        raise EvidenceValidationError(f"content type '{base_type}' is not allowed", status_code=415)
    if not data:
        raise EvidenceValidationError("empty upload")
    if len(data) > max_bytes:
        raise EvidenceValidationError(f"upload exceeds {max_bytes} bytes", status_code=413)
    signatures = _MAGIC.get(base_type)
    if signatures and not any(data.startswith(sig) for sig in signatures):
        raise EvidenceValidationError(f"content does not match declared type '{base_type}'")
    if base_type in ("text/plain", "application/json"):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EvidenceValidationError("text evidence must be UTF-8") from exc
    return hashlib.sha256(data).hexdigest()
