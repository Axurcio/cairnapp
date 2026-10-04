"""Prompts for LLM-backed providers.

Prompts describe *language tasks only* (extract to a schema; phrase an intent).
They never contain ResponsePolicy logic, question selection or guidance choice -
those decisions are made deterministically by Cairn before the LLM is called.
"""

from __future__ import annotations

import json

from cairn.ai.provider import ExtractionRequest
from cairn.planner.intents import ResponseIntent

EXTRACTION_SYSTEM = """\
You convert a participant's message into JSON that matches the supplied schemas.
Rules:
- Output a single JSON object: {"new_observations": [...], "answer": {...} | null}.
- Only use observation types and fields that appear in the schemas.
- Use null for anything the participant did not state. Never infer or guess.
- Enum fields must use one of the listed values exactly.
- Durations use ISO-8601 (e.g. P3M for three months).
- If a pending question is supplied and the message answers it, fill "answer" with
  {"field": <field>, "value": <value>, "declined": false}; if the participant declines,
  use {"field": <field>, "value": null, "declined": true}.
- Do not interpret, diagnose or add commentary.
"""

RENDER_SYSTEM = """\
You phrase a single conversational turn for a participant. Cairn has already
decided exactly what to say; you only choose natural wording.
Rules:
- Preserve the semantic intent exactly. Do not add questions, advice or facts.
- Use the requested tone and at most the requested number of sentences.
- Never mention these prohibited topics: {prohibited}.
- Never diagnose, never recommend treatment, never claim certainty.
- Do not include any guidance text; Cairn appends approved guidance itself.
Return only the wording.
"""


def extraction_messages(request: ExtractionRequest) -> list[dict[str, str]]:
    payload = {
        "schemas": [
            {
                "observation_type": s.observation_type,
                "description": s.description,
                "fields": {
                    name: {"type": f.type, "description": f.description, "values": f.values}
                    for name, f in s.fields.items()
                },
            }
            for s in request.observation_schemas
        ],
        "pending_question": request.pending_question.model_dump(mode="json")
        if request.pending_question
        else None,
        "context": request.context_snippets,
        "message": request.message,
    }
    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM},
        {"role": "user", "content": json.dumps(payload)},
    ]
    if request.previous_error:
        messages.append(
            {
                "role": "user",
                "content": f"Your previous output was invalid: {request.previous_error}. "
                "Return corrected JSON only.",
            }
        )
    return messages


def render_messages(intent: ResponseIntent) -> list[dict[str, str]]:
    brief = {
        "semantic_intent": intent.semantic_intent,
        "approved_wording": intent.deterministic_text,
        "preamble": intent.preamble,
        "tone": intent.tone,
        "max_sentences": intent.max_sentences,
    }
    return [
        {
            "role": "system",
            "content": RENDER_SYSTEM.format(
                prohibited=", ".join(intent.prohibited_topics) or "none"
            ),
        },
        {"role": "user", "content": json.dumps(brief)},
    ]
