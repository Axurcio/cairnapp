"""Build Pydantic models from Domain Pack observation schemas.

AI extraction output is validated against these generated models, so a pack's
YAML schema is enforced with the same rigour as hand-written Pydantic code.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, create_model

from cairn.domain_packs.schemas import FieldSpec, FieldType, ObservationSchema

# At least one component; written without look-ahead (pydantic-core's regex engine has none).
ISO_DURATION = r"^P(?:\d+Y(?:\d+M)?(?:\d+W)?(?:\d+D)?|\d+M(?:\d+W)?(?:\d+D)?|\d+W(?:\d+D)?|\d+D)$"


def python_type_for(spec: FieldSpec) -> Any:
    match spec.type:
        case FieldType.STRING:
            return Annotated[
                str,
                StringConstraints(strip_whitespace=True, min_length=1, max_length=spec.max_length),
            ]
        case FieldType.INTEGER:
            return Annotated[int, Field(ge=spec.minimum, le=spec.maximum)]
        case FieldType.NUMBER:
            return Annotated[float, Field(ge=spec.minimum, le=spec.maximum)]
        case FieldType.BOOLEAN:
            return bool
        case FieldType.ENUM:
            assert spec.values
            return Literal[tuple(spec.values)]
        case FieldType.DURATION:
            return Annotated[str, StringConstraints(pattern=ISO_DURATION)]
        case FieldType.DATE:
            return date


_MODELS: dict[str, type[BaseModel]] = {}


def observation_model(schema: ObservationSchema) -> type[BaseModel]:
    # Keyed by the full schema content so an edited schema never reuses a stale model.
    key = schema.model_dump_json()
    model = _MODELS.get(key)
    if model is None:
        definitions: dict[str, Any] = {
            name: (python_type_for(spec) | None, None) for name, spec in schema.fields.items()
        }
        model = create_model(
            f"Observation_{schema.observation_type}_{schema.version.replace('.', '_')}",
            __config__=ConfigDict(extra="forbid"),
            **definitions,
        )
        _MODELS[key] = model
    return model


def validate_fields(schema: ObservationSchema, fields: dict[str, Any]) -> dict[str, Any]:
    """Validate a full or partial field mapping; returns JSON-compatible values."""
    model = observation_model(schema)
    return model.model_validate(fields).model_dump(mode="json", include=set(fields))


def validate_field_value(schema: ObservationSchema, field_name: str, value: Any) -> Any:
    if field_name not in schema.fields:
        raise ValueError(f"unknown field '{field_name}' for {schema.observation_type}")
    return validate_fields(schema, {field_name: value})[field_name]
