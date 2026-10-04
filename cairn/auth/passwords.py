"""Password hashing with scrypt (standard library, memory-hard).

Hashes are self-describing (``scrypt$<n>$<r>$<p>$<salt>$<hash>``) so the cost
parameters can be raised later without invalidating existing passwords.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from functools import cache

_N = 2**15
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16
# 128 * N * r bytes are needed; leave headroom above hashlib's 32 MiB default.
_MAXMEM = 64 * 1024 * 1024
MIN_PASSWORD_LENGTH = 12


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=_DKLEN, maxmem=_MAXMEM)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _derive(password, salt, _N, _R, _P)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = encoded.split("$")
        if scheme != "scrypt":
            return False
        candidate = _derive(password, _unb64(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, _unb64(digest))


@cache
def dummy_hash() -> str:
    """A hash to verify against when the email is unknown, so timing does not reveal
    which accounts exist."""
    return hash_password(secrets.token_urlsafe(16))
