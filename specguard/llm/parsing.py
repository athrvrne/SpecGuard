"""Turning a model's reply into structured cases.

This is the only part of the LLM path that is fully deterministic, so it is
where the tests live. Nothing here calls a model.

The governing rule is **drop, never guess**. A case SpecGuard cannot read is
discarded rather than half-reconstructed: the deterministic matrix already
stands on its own, so losing a suggested case costs nothing, while inventing
one puts an unreviewable test in front of a human who trusts the tool.
"""

import json
import re

# The fields a case must have to be reviewable. `reason` is not decoration —
# it is what a human reads to approve or delete the case in seconds.
_REQUIRED = ("name", "expected_status", "reason")

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_cases(raw: str) -> list[dict]:
    """Extract test cases from a model reply. Never raises."""
    payload = _load(raw)
    if payload is None:
        return []

    if isinstance(payload, dict):
        # Either a wrapper object ({"cases": [...]}) or a lone case.
        for key in ("cases", "test_cases", "extra_cases"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]

    if not isinstance(payload, list):
        return []
    return [case for case in (_clean(item) for item in payload) if case]


def _load(raw: str):
    """The first JSON value in the reply, ignoring prose and fences around it."""
    if not raw or not raw.strip():
        return None

    fenced = _FENCE.search(raw)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(raw)

    for text in candidates:
        for opener, closer in (("[", "]"), ("{", "}")):
            start = text.find(opener)
            end = text.rfind(closer)
            if start == -1 or end <= start:
                continue
            try:
                return json.loads(text[start : end + 1])
            except (ValueError, TypeError):
                continue
    return None


def _clean(item) -> dict | None:
    """One validated case, or ``None`` if it cannot be trusted."""
    if not isinstance(item, dict):
        return None
    if any(item.get(field) in (None, "") for field in _REQUIRED):
        return None
    if not isinstance(item.get("expected_status"), int) or isinstance(
        item.get("expected_status"), bool
    ):
        return None

    body = item.get("body")
    return {
        "name": str(item["name"]),
        "kind": "llm_extra",
        "body": body if isinstance(body, dict) else None,
        "expected_status": item["expected_status"],
        "reason": str(item["reason"]),
    }
