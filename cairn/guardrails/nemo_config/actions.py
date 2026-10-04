"""Deterministic NeMo actions (loaded by NeMo from this config directory).

These are a second, independent layer. Cairn's Domain Pack SafetyPolicy is the
authoritative check; these generic rules catch anything that slips past it.
"""

import re

from nemoguardrails.actions import action

# Do not diagnose.
_DIAGNOSIS = re.compile(
    r"\b(you (have|are suffering from)|this (is|confirms|indicates)|diagnos(is|ed|e))\b"
    r".{0,40}\b(disease|disorder|syndrome|condition|parkinson\w*)",
    re.IGNORECASE,
)
# Do not produce unapproved treatment advice.
_TREATMENT = re.compile(
    r"\b(you should|you need to|i recommend|try) (take|taking|start|stop|increase|reduce)"
    r"|\b\d+\s?mg\b|\bdosage\b",
    re.IGNORECASE,
)
# Do not claim certainty unsupported by context.
_CERTAINTY = re.compile(
    r"\b(definitely|certainly|without (a )?doubt|100%|guaranteed)\b", re.IGNORECASE
)
# Keep the model on the supplied ResponseIntent; refuse obvious prompt injection.
_INJECTION = re.compile(
    r"\b(ignore (all |any )?(previous|prior|above) instructions|system prompt|you are now)\b",
    re.IGNORECASE,
)


@action(name="cairn_check_input")
async def cairn_check_input(text: str = "") -> bool:
    return not _INJECTION.search(text or "")


@action(name="cairn_check_output")
async def cairn_check_output(text: str = "") -> bool:
    text = text or ""
    return not (_DIAGNOSIS.search(text) or _TREATMENT.search(text) or _CERTAINTY.search(text))
