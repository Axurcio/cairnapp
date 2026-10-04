"""Deterministic evaluation of declarative Domain Pack conditions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cairn.domain_packs.schemas import Condition, ConditionOp


def is_present(value: Any) -> bool:
    return value is not None and value != "" and value != []


def evaluate(condition: Condition, fields: Mapping[str, Any]) -> bool:
    if condition.all is not None:
        return all(evaluate(c, fields) for c in condition.all)
    if condition.any is not None:
        return any(evaluate(c, fields) for c in condition.any)
    if condition.not_ is not None:
        return not evaluate(condition.not_, fields)

    assert condition.field is not None
    assert condition.op is not None
    actual = fields.get(condition.field)
    expected = condition.value
    match condition.op:
        case ConditionOp.EXISTS:
            return is_present(actual)
        case ConditionOp.MISSING:
            return not is_present(actual)
        case ConditionOp.EQ:
            return bool(actual == expected)
        case ConditionOp.NE:
            return bool(actual != expected)
        case ConditionOp.IN:
            return actual in (expected or [])
        case ConditionOp.NOT_IN:
            return actual not in (expected or [])
        case ConditionOp.CONTAINS:
            return (
                isinstance(actual, str)
                and isinstance(expected, str)
                and expected.lower() in actual.lower()
            )
        case ConditionOp.GT | ConditionOp.GTE | ConditionOp.LT | ConditionOp.LTE:
            if not isinstance(actual, int | float) or not isinstance(expected, int | float):
                return False
            if condition.op is ConditionOp.GT:
                return actual > expected
            if condition.op is ConditionOp.GTE:
                return actual >= expected
            if condition.op is ConditionOp.LT:
                return actual < expected
            return actual <= expected
    raise AssertionError(f"unhandled operator {condition.op}")  # pragma: no cover
