import json

from specguard import demo_api
import pytest
from click.testing import CliRunner
from specguard.demo_api import DemoServer

from specguard.cli import cli


@pytest.fixture
def suite(tmp_path, petstore_path):
    out = tmp_path / "generated"
    result = CliRunner().invoke(cli, ["generate", str(petstore_path), "--out", str(out)])
    assert result.exit_code == 0, result.output
    return out


def record_baseline(suite, petstore_path, base_url, out):
    return CliRunner().invoke(
        cli,
        [
            "baseline",
            "--spec", str(petstore_path),
            "--suite", str(suite),
            "--base-url", base_url,
            "--auth-token", "test-token",
            "--out", str(out),
        ],
    )


def run_guard(suite, petstore_path, base_url, baseline, report, *extra):
    return CliRunner().invoke(
        cli,
        [
            "guard",
            "--spec", str(petstore_path),
            "--suite", str(suite),
            "--base-url", base_url,
            "--baseline", str(baseline),
            "--report", str(report),
            "--auth-token", "test-token",
            *extra,
        ],
    )


# --- baseline ---------------------------------------------------------------


def test_baseline_records_the_endpoints_the_suite_exercised(tmp_path, suite, petstore_path):
    out = tmp_path / "baseline.json"
    with DemoServer() as base_url:
        result = record_baseline(suite, petstore_path, base_url, out)

    assert result.exit_code == 0, result.output
    endpoints = json.loads(out.read_text())["endpoints"]
    assert "GET /pets" in endpoints
    assert "GET /pets/{petId}" in endpoints


def test_baseline_folds_concrete_ids_onto_the_templated_route(tmp_path, suite, petstore_path):
    out = tmp_path / "baseline.json"
    with DemoServer() as base_url:
        record_baseline(suite, petstore_path, base_url, out)

    # Not "GET /pets/string" — one entry per endpoint, not per resource id.
    assert not any(
        k.startswith("GET /pets/") and "{" not in k
        for k in json.loads(out.read_text())["endpoints"]
    )


def test_baseline_warns_when_the_sample_is_thin(tmp_path, suite, petstore_path):
    out = tmp_path / "baseline.json"
    with DemoServer() as base_url:
        result = record_baseline(suite, petstore_path, base_url, out)

    assert "low confidence" in result.output.lower()


def test_baseline_refuses_to_overwrite_without_force(tmp_path, suite, petstore_path):
    out = tmp_path / "baseline.json"
    with DemoServer() as base_url:
        record_baseline(suite, petstore_path, base_url, out)
        result = record_baseline(suite, petstore_path, base_url, out)

    assert result.exit_code != 0
    assert "--force" in result.output


# --- guard ------------------------------------------------------------------


def test_guard_finds_no_drift_against_an_unchanged_api(tmp_path, suite, petstore_path):
    baseline, report = tmp_path / "baseline.json", tmp_path / "drift.json"
    with DemoServer() as base_url:
        record_baseline(suite, petstore_path, base_url, baseline)
        result = run_guard(suite, petstore_path, base_url, baseline, report)

    assert result.exit_code == 0, result.output
    assert json.loads(report.read_text())["summary"]["breaking"] == 0


def test_guard_reports_a_renamed_field_as_breaking_at_that_field(
    tmp_path, suite, petstore_path, monkeypatch
):
    """The demo: baseline, rename a required field, guard."""
    baseline, report = tmp_path / "baseline.json", tmp_path / "drift.json"

    with DemoServer() as base_url:
        record_baseline(suite, petstore_path, base_url, baseline)

    renamed = {"id": "p_1", "pet_name": "Rex", "tag": "good-boy", "status": "available"}
    monkeypatch.setattr(demo_api, "PET", renamed)

    with DemoServer() as base_url:
        result = run_guard(suite, petstore_path, base_url, baseline, report)

    assert result.exit_code != 0
    findings = json.loads(report.read_text())["findings"]
    breaking = [f for f in findings if f["severity"] == "breaking"]

    assert {f["field"] for f in breaking} == {"name", "[].name"}
    assert all(f["kind"] == "field_removed" for f in breaking)
    assert {f["field"] for f in findings if f["severity"] == "info"} == {
        "pet_name",
        "[].pet_name",
    }


def test_guard_names_the_drifted_field_in_the_console(
    tmp_path, suite, petstore_path, monkeypatch
):
    baseline, report = tmp_path / "baseline.json", tmp_path / "drift.json"
    with DemoServer() as base_url:
        record_baseline(suite, petstore_path, base_url, baseline)

    monkeypatch.setattr(
        demo_api, "PET", {"id": "p_1", "pet_name": "Rex", "status": "available"}
    )
    with DemoServer() as base_url:
        result = run_guard(suite, petstore_path, base_url, baseline, report)

    assert "name" in result.output
    assert "breaking" in result.output


def test_fail_on_warning_does_not_gate_on_an_added_field(
    tmp_path, suite, petstore_path, monkeypatch
):
    baseline, report = tmp_path / "baseline.json", tmp_path / "drift.json"
    with DemoServer() as base_url:
        record_baseline(suite, petstore_path, base_url, baseline)

    added = {"id": "p_1", "name": "Rex", "tag": "t", "status": "available", "seen_at": "now"}
    monkeypatch.setattr(demo_api, "PET", added)

    with DemoServer() as base_url:
        result = run_guard(
            suite, petstore_path, base_url, baseline, report, "--fail-on", "warning"
        )

    assert result.exit_code == 0, result.output
    assert json.loads(report.read_text())["summary"]["info"] > 0


def test_guard_can_emit_junit(tmp_path, suite, petstore_path):
    baseline, report = tmp_path / "baseline.json", tmp_path / "drift.json"
    junit = tmp_path / "drift.xml"
    with DemoServer() as base_url:
        record_baseline(suite, petstore_path, base_url, baseline)
        run_guard(suite, petstore_path, base_url, baseline, report, "--junitxml", str(junit))

    assert junit.exists()
    assert "testsuite" in junit.read_text()


def test_guard_without_a_baseline_fails_with_a_useful_message(tmp_path, suite, petstore_path):
    with DemoServer() as base_url:
        result = run_guard(
            suite, petstore_path, base_url, tmp_path / "nope.json", tmp_path / "d.json"
        )

    assert result.exit_code != 0
    assert "specguard baseline" in result.output
