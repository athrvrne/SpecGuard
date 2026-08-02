"""Reading and writing ``baseline.json`` — the recorded contract.

Kept as plain indented JSON on purpose: the baseline belongs in Git, and a
contract change should show up as a readable diff in code review.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .schema_inferer import infer

BASELINE_VERSION = 1


def build_baseline(captured: dict) -> dict:
    """Turn recorded responses into a per-endpoint contract."""
    endpoints = {}
    for key, entry in sorted(captured.items()):
        bodies = entry.get("bodies") or []
        result = infer(bodies)
        endpoints[key] = {
            "success_status": _success_status(entry.get("statuses") or []),
            "sample_size": result["sample_size"],
            "low_confidence": result["low_confidence"],
            "inferred_schema": result["inferred_schema"],
            "value_stats": result["value_stats"],
        }

    return {
        "version": BASELINE_VERSION,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "endpoints": endpoints,
    }


def _success_status(statuses: list[int]) -> int | None:
    successes = [s for s in statuses if 200 <= s < 300]
    return min(successes) if successes else None


def write_baseline(baseline: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2, sort_keys=False) + "\n")
    return path


def load_baseline(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"no baseline at {path} — record one first with `specguard baseline`"
        )
    return json.loads(path.read_text())
