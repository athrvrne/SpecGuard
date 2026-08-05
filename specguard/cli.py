"""SpecGuard's command surface.

Generation is the only command that can involve a model. ``baseline`` and
``guard`` are deliberately LLM-free: the thing that decides whether your API
drifted has to be reproducible.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import click

from . import __version__
from .baseline_store import build_baseline, load_baseline, write_baseline
from .case_designer import design_cases
from .drift_engine import BREAKING, INFO, WARNING, diff
from .llm import get_provider
from .reporter import console_report, exceeds_threshold, junit_report, summarise, write_report
from .schema_inferer import infer
from .spec_parser import parse_spec
from .test_renderer import render_suite


@click.group()
@click.version_option(__version__, prog_name="specguard")
def cli() -> None:
    """Generate from spec, guard against drift."""


@cli.command()
@click.argument("spec", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--out",
    default="generated",
    type=click.Path(file_okay=False, path_type=Path),
    show_default=True,
    help="Directory to write the suite into.",
)
@click.option(
    "--base-url",
    default="",
    help="Baked into the scaffolded conftest as the default base URL.",
)
@click.option(
    "--provider",
    default="none",
    show_default=True,
    help="Model used to propose EXTRA cases: claude, ollama, or none. The "
    "deterministic matrix is produced either way.",
)
@click.option("--model", default=None, help="Override the provider's default model.")
def generate(spec: Path, out: Path, base_url: str, provider: str, model: str | None) -> None:
    """Turn an OpenAPI spec into a review-ready pytest suite."""
    endpoints = parse_spec(spec)
    if not endpoints:
        raise click.ClickException(f"no operations found in {spec}")

    # Resolve the provider before writing anything, so a typo fails fast
    # instead of leaving a half-generated directory behind.
    try:
        llm = get_provider(provider, model)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--provider") from exc

    suite = render_suite(endpoints, out, llm=llm, spec_name=spec.name, base_url=base_url)
    cases = suite.cases
    needs_review = [c for c in cases if c.needs_review]
    proposed = [c for c in cases if c.kind == "llm_extra"]

    click.echo(f"Parsed {len(endpoints)} endpoints from {spec}")
    click.echo(f"Wrote {len(cases)} cases to {out}/")
    for path in suite.files:
        click.echo(f"  {path.name}")
    if llm is not None:
        click.echo(f"{provider} proposed {len(proposed)} extra case(s)")

    click.echo("")
    if needs_review:
        click.secho(
            f"{len(needs_review)} case(s) marked REVIEW — SpecGuard invented data "
            "the spec did not supply:",
            fg="yellow",
        )
        for case in needs_review:
            click.echo(f"  {case.name}: {case.reason}")
        click.echo("")
    click.secho(
        "This is a draft. Read it, fix the REVIEW cases, then move what you want "
        "into your real suite.",
        fg="cyan",
    )


# --- the Guard half ---------------------------------------------------------

_spec_option = click.option(
    "--spec",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Spec to read routes from, so /pets/p_1 is filed under /pets/{petId}.",
)
_suite_option = click.option(
    "--suite",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Test suite to run while recording. Its real ids are the point.",
)
_base_url_option = click.option(
    "--base-url", required=True, help="API to record against."
)
_auth_option = click.option(
    "--auth-token",
    default="",
    envvar="SPECGUARD_AUTH_TOKEN",
    help="Credentials for the suite. Without it, protected endpoints return 401 "
    "and record nothing, leaving them unguarded.",
)
_env_option = click.option(
    "--env",
    "extra_env",
    multiple=True,
    metavar="KEY=VALUE",
    help="Extra environment for the suite. Repeatable.",
)


def _capture(
    suite: Path,
    spec: Path | None,
    base_url: str,
    auth_token: str = "",
    extra_env: tuple[str, ...] = (),
) -> dict:
    """Run a suite with the recording plugin loaded and collect what it saw."""
    routes = [ep.path for ep in parse_spec(spec)] if spec else []
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "captured.json"
        env = {
            **os.environ,
            "SPECGUARD_BASE_URL": base_url,
            "SPECGUARD_AUTH_TOKEN": auth_token,
            "SPECGUARD_ROUTES": json.dumps(routes),
            "SPECGUARD_CAPTURE": str(out),
        }
        for pair in extra_env:
            key, _, value = pair.partition("=")
            env[key] = value
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(suite), "-q", "-p", "specguard.record"],
            env=env,
            capture_output=True,
            text=True,
        )
        if not out.exists():
            output = result.stdout or result.stderr
            if "No module named pytest" in output:
                raise click.ClickException(
                    f"{sys.executable} has no pytest, so the suite could not run. "
                    "Install SpecGuard into the same environment as your tests."
                )
            raise click.ClickException("the suite recorded nothing:\n" + output)
        captured = json.loads(out.read_text())

    if not captured:
        raise click.ClickException(
            f"no HTTP calls captured from {suite} — does it use requests, and did "
            "any test actually run?"
        )
    return captured


@cli.command()
@_spec_option
@_suite_option
@_base_url_option
@_auth_option
@_env_option
@click.option("--out", default="baseline.json", type=click.Path(path_type=Path), show_default=True)
@click.option("--force", is_flag=True, help="Overwrite an existing baseline.")
def baseline(spec, suite, base_url, auth_token, extra_env, out, force) -> None:
    """Record the API's current responses as the contract to guard against."""
    if out.exists() and not force:
        raise click.ClickException(
            f"{out} already exists. Recording over the contract you are guarding "
            "against should be deliberate — pass --force if that is what you want."
        )

    captured = _capture(suite, spec, base_url, auth_token, extra_env)
    recorded = build_baseline(captured)
    write_baseline(recorded, out)

    click.echo(f"Recorded {len(recorded['endpoints'])} endpoints to {out}")

    # An endpoint with no recorded schema is not guarded at all. Saying nothing
    # would leave someone believing it was covered.
    for key, entry in recorded["endpoints"].items():
        if not entry["inferred_schema"]:
            click.secho(
                f"  not guarded: {key} returned no JSON body to record "
                f"(statuses seen: {entry['success_status'] or 'none successful'})",
                fg="yellow",
            )
        elif entry["low_confidence"]:
            click.secho(
                f"  low confidence: {key} rests on {entry['sample_size']} response(s); "
                "fields seen once are recorded as required and may cause false drift",
                fg="yellow",
            )


@cli.command()
@_spec_option
@_suite_option
@_base_url_option
@click.option("--baseline", "baseline_path", default="baseline.json",
              type=click.Path(path_type=Path), show_default=True)
@click.option("--report", default="drift_report.json", type=click.Path(path_type=Path),
              show_default=True)
@click.option("--junitxml", type=click.Path(path_type=Path), help="Also write JUnit XML.")
@click.option("--fail-on", type=click.Choice([BREAKING, WARNING, INFO]), default=BREAKING,
              show_default=True, help="Lowest severity that fails the build.")
@_auth_option
@_env_option
def guard(spec, suite, base_url, baseline_path, report, junitxml, fail_on,
          auth_token, extra_env) -> None:
    """Compare live responses to the baseline and report drift."""
    try:
        recorded = load_baseline(baseline_path)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    captured = _capture(suite, spec, base_url, auth_token, extra_env)

    findings = []
    for key, entry in sorted(recorded.get("endpoints", {}).items()):
        observed = captured.get(key)
        if observed is None:
            click.secho(f"not exercised, so not checked: {key}", fg="yellow")
            continue
        if not entry.get("inferred_schema"):
            click.secho(f"nothing recorded in the baseline, so not checked: {key}", fg="yellow")
            continue
        current = infer(observed.get("bodies") or [])["inferred_schema"]
        findings += diff(entry["inferred_schema"], current, key)

    write_report(findings, report)
    if junitxml:
        junit_report(findings, junitxml, fail_on=fail_on)

    click.echo(console_report(findings))
    click.echo(f"\nReport written to {report}")

    if exceeds_threshold(findings, fail_on):
        counts = summarise(findings)
        click.secho(
            f"\nFAIL: {counts[BREAKING]} breaking, {counts[WARNING]} warning "
            f"(--fail-on {fail_on})",
            fg="red",
        )
        raise SystemExit(1)


# --- the demo API -----------------------------------------------------------


@cli.command()
@click.option("--port", default=8080, show_default=True, help="Port to bind.")
@click.option("--rename", metavar="OLD:NEW",
              help="Rename a response field. This is the breaking case.")
@click.option("--add", metavar="FIELD", help="Add a new optional field (info severity).")
@click.option("--lax", is_flag=True, help="Stop rejecting invalid payloads.")
def demo(port: int, rename: str | None, add: str | None, lax: bool) -> None:
    """Run a small API that honours examples/petstore.yaml.

    Something to point SpecGuard at with no network and no setup. Restart it
    with --rename to stage a breaking change and watch `guard` catch it.
    """
    from .demo_api import DemoServer, apply_drift

    try:
        apply_drift(rename=rename, add=add, lax=lax)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc

    server = DemoServer(port=port)
    url = server.start()
    staged = []
    if rename:
        staged.append(f"rename {rename}")
    if add:
        staged.append(f"add {add}")
    if lax:
        staged.append("lax validation")

    click.echo(f"Demo API on {url}")
    if staged:
        click.secho(f"Staged drift: {', '.join(staged)}", fg="yellow")
    else:
        click.echo("Serving the healthy contract.")
    click.echo("Ctrl-C to stop.")
    try:
        server.thread.join()
    except KeyboardInterrupt:
        click.echo("\nStopping.")
    finally:
        server.stop()
