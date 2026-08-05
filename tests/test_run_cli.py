"""`specguard run` exists to wire the environment, not to alias pytest."""

import pytest
from click.testing import CliRunner

from specguard.cli import cli
from specguard.demo_api import DemoServer


@pytest.fixture
def suite(tmp_path, petstore_path):
    out = tmp_path / "generated"
    result = CliRunner().invoke(cli, ["generate", str(petstore_path), "--out", str(out)])
    assert result.exit_code == 0, result.output
    return out


def run(suite, base_url, *extra):
    return CliRunner().invoke(
        cli, ["run", str(suite), "--base-url", base_url, "--auth-token", "t", *extra]
    )


def test_the_suite_passes_against_a_conforming_api(suite):
    with DemoServer() as base_url:
        result = run(suite, base_url)

    assert result.exit_code == 0, result.output


def test_credentials_reach_the_suite(suite):
    # Without the token every protected endpoint 401s and the suite goes red,
    # so a green run is itself the evidence that --auth-token was wired through.
    with DemoServer() as base_url:
        authed = run(suite, base_url)
        anonymous = CliRunner().invoke(cli, ["run", str(suite), "--base-url", base_url])

    assert authed.exit_code == 0, authed.output
    assert anonymous.exit_code != 0


def test_a_failing_suite_produces_a_nonzero_exit(suite, monkeypatch):
    from specguard import demo_api

    monkeypatch.setattr(demo_api, "STRICT", False)  # stops rejecting bad payloads
    with DemoServer() as base_url:
        result = run(suite, base_url)

    assert result.exit_code != 0


def test_junit_is_written_where_asked(tmp_path, suite):
    junit = tmp_path / "results.xml"
    with DemoServer() as base_url:
        run(suite, base_url, "--junitxml", str(junit))

    assert junit.exists()
    assert "testsuite" in junit.read_text()


def test_unrecognised_arguments_are_handed_to_pytest(tmp_path, suite):
    # `-m auth` is not a SpecGuard flag; it has to reach pytest untouched.
    # Counting JUnit cases rather than reading stdout, because the suite runs
    # in a subprocess whose output the CliRunner never sees.
    everything, only_auth = tmp_path / "all.xml", tmp_path / "auth.xml"
    with DemoServer() as base_url:
        run(suite, base_url, "--junitxml", str(everything))
        result = run(suite, base_url, "--junitxml", str(only_auth), "-m", "auth")

    assert result.exit_code == 0
    assert only_auth.read_text().count("<testcase") == 3  # one per protected endpoint
    assert everything.read_text().count("<testcase") == 20


def test_extra_env_reaches_the_suite(tmp_path, suite):
    probe = suite / "test_env_probe.py"
    probe.write_text(
        "import os\n\ndef test_probe():\n    assert os.environ['TENANT'] == 'acme'\n"
    )
    with DemoServer() as base_url:
        result = run(suite, base_url, "--env", "TENANT=acme")

    assert result.exit_code == 0, result.output


def test_run_is_documented_as_a_command():
    assert "run" in CliRunner().invoke(cli, ["--help"]).output
