"""Deterministic parsing of short free-text answers into typed field values.

Used by MockAIProvider so the full conversation loop runs without an external
model. It is intentionally simple and conservative: if it cannot confidently
parse an answer it returns ``None`` rather than guessing.
"""

from __future__ import annotations

import re
from typing import Any

from cairn.domain_packs.schemas import FieldSpec, FieldType

DECLINED = object()

_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "a": 1,
    "an": 1,
    "two": 2,
    "a couple of": 2,
    "couple of": 2,
    "three": 3,
    "a few": 3,
    "few": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "several": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_UNITS = {"day": "D", "week": "W", "month": "M", "year": "Y"}
_DECLINE = re.compile(
    r"\b(rather not|prefer not|don'?t want to (say|answer|talk)|skip( this)?|pass)\b",
    re.IGNORECASE,
)
_YES = re.compile(r"^\s*(yes|yeah|yep|y|true|correct|i do|it does)\b", re.IGNORECASE)
_NO = re.compile(r"^\s*(no|nope|n|false|not really|i don'?t|it doesn'?t)\b", re.IGNORECASE)


def _number_pattern() -> str:
    words = sorted(_NUMBER_WORDS, key=len, reverse=True)
    return r"(\d+|" + "|".join(re.escape(w) for w in words) + r")"


_DURATION = re.compile(r"\b" + _number_pattern() + r"\s+(day|week|month|year)s?\b", re.IGNORECASE)
_INT = re.compile(r"(?<![\d.])(-?\d+)(?:\s*(?:/|out of)\s*\d+)?")


def _to_int(token: str) -> int | None:
    token = token.lower().strip()
    if token.lstrip("-").isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def parse_duration(text: str) -> str | None:
    match = _DURATION.search(text)
    if not match:
        return None
    amount = _to_int(match.group(1))
    if not amount or amount < 0:
        return None
    return f"P{amount}{_UNITS[match.group(2).lower()]}"


def parse_number(text: str, spec: FieldSpec) -> int | float | None:
    match = _INT.search(text)
    value: int | None = int(match.group(1)) if match else None
    if value is None:
        for word in sorted(_NUMBER_WORDS, key=len, reverse=True):
            if len(word) > 2 and re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
                value = _NUMBER_WORDS[word]
                break
    if value is None:
        return None
    if spec.minimum is not None and value < spec.minimum:
        return None
    if spec.maximum is not None and value > spec.maximum:
        return None
    return value


def parse_enum(text: str, spec: FieldSpec) -> str | None:
    lowered = text.lower()
    for value in spec.values or []:
        options = [value.replace("_", " "), *spec.synonyms.get(value, [])]
        if any(re.search(rf"\b{re.escape(o.lower())}\b", lowered) for o in options):
            return value
    return None


def parse_answer(text: str, spec: FieldSpec) -> Any:
    """Return a typed value, :data:`DECLINED`, or ``None`` if unparseable."""
    if _DECLINE.search(text):
        return DECLINED
    match spec.type:
        case FieldType.DURATION:
            return parse_duration(text)
        case FieldType.INTEGER | FieldType.NUMBER:
            return parse_number(text, spec)
        case FieldType.ENUM:
            return parse_enum(text, spec)
        case FieldType.BOOLEAN:
            if _YES.search(text):
                return True
            if _NO.search(text):
                return False
            return None
        case FieldType.STRING:
            cleaned = text.strip()
            return cleaned[: spec.max_length] if cleaned else None
        case FieldType.DATE:
            match_ = re.search(r"\d{4}-\d{2}-\d{2}", text)
            return match_.group(0) if match_ else None
