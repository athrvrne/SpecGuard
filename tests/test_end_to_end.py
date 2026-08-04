"""The M2 acceptance test: a generated suite must actually pass against an API
that honours the spec it was generated from.

Everything else tests SpecGuard's parts. This tests the promise.
"""

import subprocess
import sys

import pytest
from click.testing import CliRunner

from specguard import demo_api
from specguard.demo_api import DemoServer

from specguard.cli import cli


@pytest.fixture
def generated_suite(tmp_path, petstore_path):
    out = tmp_path / "generated"
    result = CliRunner().invoke(cli, ["generate", str(petstore_path), "--out", str(out)])
    assert result.exit_code == 0, result.output
    return out


def run_pytest(suite_dir, base_url, *extra):
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(suite_dir), "-q", *extra],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "SPECGUARD_BASE_URL": base_url,
            "SPECGUARD_AUTH_TOKEN": "test-token",
        },
        cwd=suite_dir,
    )


def test_generated_suite_passes_against_a_conforming_api(generated_suite):
    with DemoServer() as base_url:
        result = run_pytest(generated_suite, base_url)

    assert result.returncode == 0, result.stdout + result.stderr
    # An all-skipped run also exits 0 — the conftest skips without a base URL —
    # so a green exit code alone would prove nothing.
    assert "skipped" not in result.stdout
    assert "20 passed" in result.stdout


def test_the_suite_is_not_trivially_small(generated_suite):
    with DemoServer() as base_url:
        result = run_pytest(generated_suite, base_url, "--collect-only")

    collected = [line for line in result.stdout.splitlines() if "::test_" in line]
    assert len(collected) >= 20, result.stdout


def test_the_suite_catches_an_api_that_stops_validating(generated_suite, monkeypatch):
    """An API that accepts anything must make the generated suite go red.

    Without this, a suite of tests that all pass proves nothing.
    """
    monkeypatch.setattr(demo_api, "STRICT", False)

    with DemoServer() as base_url:
        result = run_pytest(generated_suite, base_url, "-m", "validation")

    assert result.returncode != 0, result.stdout
