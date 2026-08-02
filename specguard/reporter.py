"""Findings -> JSON, console, and JUnit XML.

Standard formats only. SpecGuard produces artifacts every CI already
understands; it never asks the pipeline to adopt a bespoke one.
"""

import json
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .drift_engine import BREAKING, INFO, WARNING
from .models import Finding

SEVERITIES = (BREAKING, WARNING, INFO)
# Ordered most severe first, so a threshold catches itself and everything above.
_RANK = {severity: index for index, severity in enumerate(SEVERITIES)}

_ICON = {BREAKING: "x", WARNING: "!", INFO: "i"}


def summarise(findings: list[Finding]) -> dict[str, int]:
    """Counts per severity, always reporting every severity."""
    counts = dict.fromkeys(SEVERITIES, 0)
    for finding in findings:
        counts[finding.severity] += 1
    return counts


def exceeds_threshold(findings: list[Finding], fail_on: str) -> bool:
    """Whether anything is at or above the severity the human chose to gate on."""
    limit = _RANK[fail_on]
    return any(_RANK[f.severity] <= limit for f in findings)


def write_report(findings: list[Finding], path: str | Path) -> Path:
    """Write ``drift_report.json``. A clean run still produces a report."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "findings": [asdict(f) for f in findings],
        "summary": summarise(findings),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def console_report(findings: list[Finding]) -> str:
    """A human-readable summary for the terminal."""
    if not findings:
        return "No drift detected."

    counts = summarise(findings)
    lines = [
        f"{counts[BREAKING]} breaking, {counts[WARNING]} warning, {counts[INFO]} info",
        "",
    ]
    for finding in findings:
        field = finding.field or "(response root)"
        lines.append(f"  [{_ICON[finding.severity]}] {finding.severity:8} {finding.endpoint}")
        lines.append(f"      {field}: {finding.detail}")
    return "\n".join(lines)


def junit_report(findings: list[Finding], path: str | Path, fail_on: str = BREAKING) -> Path:
    """Write JUnit XML: one test case per finding.

    Findings below the chosen threshold are still reported as cases, so CI shows
    the full picture, but only those at or above it are marked as failures.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    limit = _RANK[fail_on]
    failures = sum(1 for f in findings if _RANK[f.severity] <= limit)

    suite = ET.Element(
        "testsuite",
        name="specguard.drift",
        tests=str(len(findings)),
        failures=str(failures),
        errors="0",
        skipped="0",
    )
    for finding in findings:
        case = ET.SubElement(
            suite,
            "testcase",
            classname=finding.endpoint or "specguard",
            name=f"{finding.kind}:{finding.field or 'root'}",
        )
        if _RANK[finding.severity] <= limit:
            ET.SubElement(
                case, "failure", type=finding.kind, message=f"{finding.severity}: {finding.detail}"
            ).text = f"{finding.endpoint} {finding.field}: {finding.detail}"
        else:
            ET.SubElement(case, "system-out").text = f"{finding.severity}: {finding.detail}"

    tree = ET.ElementTree(suite)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path
