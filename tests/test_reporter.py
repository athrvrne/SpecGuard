import json
import xml.etree.ElementTree as ET

from specguard.drift_engine import BREAKING, INFO, WARNING
from specguard.models import Finding
from specguard.reporter import (
    _ordered,
    console_report,
    exceeds_threshold,
    junit_report,
    summarise,
    write_report,
)


def finding(severity, kind="field_removed", field="currency"):
    return Finding(
        endpoint="GET /pets/{petId}",
        severity=severity,
        kind=kind,
        field=field,
        detail="was required in baseline, absent in current response",
    )


FINDINGS = [finding(BREAKING), finding(WARNING, "enum_added", "status"), finding(INFO, "field_added", "tag")]


# --- summary ----------------------------------------------------------------


def test_summary_counts_each_severity():
    assert summarise(FINDINGS) == {"breaking": 1, "warning": 1, "info": 1}


def test_summary_reports_zeroes_rather_than_omitting_a_severity():
    assert summarise([]) == {"breaking": 0, "warning": 0, "info": 0}


# --- ordering ---------------------------------------------------------------
#
# The engine sorts within one endpoint, but a run concatenates many endpoints,
# so the breaking findings end up scattered through the output. Every report
# orders them globally instead: the thing that fails the build reads first.


def test_console_report_puts_every_breaking_finding_first():
    scattered = [finding(INFO), finding(BREAKING), finding(WARNING), finding(BREAKING)]
    lines = [ln for ln in console_report(scattered).splitlines() if "] " in ln]

    severities = [ln.split("]")[1].split()[0] for ln in lines]
    assert severities == [BREAKING, BREAKING, WARNING, INFO]


def test_the_json_report_uses_the_same_order_as_the_console(tmp_path):
    scattered = [finding(INFO), finding(BREAKING), finding(WARNING)]
    path = tmp_path / "drift.json"
    write_report(scattered, path)

    written = [f["severity"] for f in json.loads(path.read_text())["findings"]]
    assert written == [BREAKING, WARNING, INFO]


def test_ordering_is_stable_for_findings_of_equal_severity():
    same = [finding(BREAKING, field="b"), finding(BREAKING, field="a")]
    assert [f.field for f in _ordered(same)] == ["b", "a"]


# --- json report ------------------------------------------------------------


def test_report_matches_the_documented_json_shape(tmp_path):
    path = tmp_path / "drift.json"
    write_report(FINDINGS, path)
    payload = json.loads(path.read_text())

    assert set(payload) == {"generated_at", "findings", "summary"}
    assert payload["summary"] == {"breaking": 1, "warning": 1, "info": 1}
    assert payload["findings"][0] == {
        "endpoint": "GET /pets/{petId}",
        "severity": "breaking",
        "kind": "field_removed",
        "field": "currency",
        "detail": "was required in baseline, absent in current response",
    }


def test_a_clean_run_still_writes_a_report(tmp_path):
    path = tmp_path / "drift.json"
    write_report([], path)

    assert json.loads(path.read_text())["findings"] == []


# --- gating -----------------------------------------------------------------


def test_fail_on_breaking_ignores_warnings_and_info():
    assert exceeds_threshold([finding(WARNING), finding(INFO)], BREAKING) is False
    assert exceeds_threshold([finding(BREAKING)], BREAKING) is True


def test_fail_on_warning_also_catches_breaking():
    assert exceeds_threshold([finding(BREAKING)], WARNING) is True
    assert exceeds_threshold([finding(INFO)], WARNING) is False


def test_fail_on_info_catches_everything():
    assert exceeds_threshold([finding(INFO)], INFO) is True


def test_nothing_fails_a_clean_run():
    assert exceeds_threshold([], INFO) is False


# --- console ----------------------------------------------------------------


def test_console_report_names_the_endpoint_field_and_severity():
    text = console_report(FINDINGS)
    assert "GET /pets/{petId}" in text
    assert "currency" in text
    assert "breaking" in text


def test_console_report_says_so_when_there_is_no_drift():
    assert "no drift" in console_report([]).lower()


# --- junit ------------------------------------------------------------------


def test_junit_has_one_case_per_finding_with_breaking_as_a_failure(tmp_path):
    path = tmp_path / "drift.xml"
    junit_report(FINDINGS, path, fail_on=BREAKING)
    root = ET.fromstring(path.read_text())

    assert root.get("tests") == "3"
    assert root.get("failures") == "1"
    cases = root.findall(".//testcase")
    assert len(cases) == 3
    assert len(cases[0].findall("failure")) == 1


def test_junit_below_the_threshold_is_recorded_but_not_failed(tmp_path):
    path = tmp_path / "drift.xml"
    junit_report([finding(INFO)], path, fail_on=BREAKING)
    root = ET.fromstring(path.read_text())

    assert root.get("failures") == "0"
    assert root.findall(".//testcase")
