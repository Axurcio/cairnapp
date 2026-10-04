"""Journey-level business errors (mapped to HTTP statuses by the API layer)."""

from __future__ import annotations


class JourneyError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class JourneyNotActive(JourneyError):
    status_code = 409


class ConsentRequired(JourneyError):
    status_code = 403


class InvalidRequest(JourneyError):
    status_code = 422
