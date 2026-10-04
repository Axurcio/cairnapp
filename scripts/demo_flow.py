"""Exercise a running Cairn API with the SYNTHETIC demo journeys.

``python scripts/demo_flow.py [--api http://localhost:8000]``

Runs the scaffold's acceptance flows and exits non-zero if any expectation fails:

1. health demo: "My right hand has been shaky lately." -> asks duration
2. health demo: "About three months." -> updates the observation, asks severity
3. mentorship demo: "I keep getting overlooked..." -> asks recent_project_example
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import httpx
from demo_ids import (
    HEALTH_JOURNEY_ID,
    HEALTH_PARTICIPANT_ID,
    MENTORSHIP_JOURNEY_ID,
    MENTORSHIP_PARTICIPANT_ID,
    participant_headers,
)

STEPS: list[tuple[str, Any, Any, str, str]] = [
    (
        "health",
        HEALTH_JOURNEY_ID,
        HEALTH_PARTICIPANT_ID,
        "My right hand has been shaky lately.",
        "hand_shaking.duration",
    ),
    (
        "health",
        HEALTH_JOURNEY_ID,
        HEALTH_PARTICIPANT_ID,
        "About three months.",
        "hand_shaking.severity",
    ),
    (
        "mentorship",
        MENTORSHIP_JOURNEY_ID,
        MENTORSHIP_PARTICIPANT_ID,
        "I keep getting overlooked when projects are assigned.",
        "recent_project_example",
    ),
]


def main(api: str) -> int:
    failures = 0
    with httpx.Client(base_url=api, timeout=30) as client:
        print(f"GET /health -> {client.get('/health').json()}")
        for name, journey_id, participant_id, text, expected_question in STEPS:
            response = client.post(
                f"/v1/journeys/{journey_id}/messages",
                json={"text": text},
                headers=participant_headers(participant_id),
            )
            response.raise_for_status()
            body = response.json()
            action = body["next_action"]
            ok = action["question_id"] == expected_question
            failures += 0 if ok else 1
            print(f"\n[{name}] participant: {text}")
            print(f"[{name}] cairn:       {body['response']['text']}")
            print(
                f"[{name}] decision:    {action['action_type']} {action['question_id']} "
                f"({action['policy_id']}@{action['policy_version']}, "
                f"pack {action['domain_pack']}@{action['domain_pack_version']})"
            )
            print(f"[{name}] reason:      {action['reason']}")
            if body["observation"]:
                filled = {k: v for k, v in body["observation"]["fields"].items() if v is not None}
                print(f"[{name}] observation: {filled}")
            matched = [p["rule_id"] for p in body["pattern_evaluations"] if p["matched"]]
            if matched:
                print(f"[{name}] patterns:    matched {matched}")
            print(f"[{name}] projection:  {body['explanation']['context']['projection']}")
            print(f"[{name}] {'PASS' if ok else 'FAIL'} (expected {expected_question})")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=os.environ.get("CAIRN_API_URL", "http://localhost:8000"))
    sys.exit(main(parser.parse_args().api))
