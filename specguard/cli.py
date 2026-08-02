"""SpecGuard's command surface.

Only ``generate`` exists today; ``baseline``, ``guard`` and ``run`` arrive with
the Guard half. Generation is the only command that can involve a model — Guard
is deliberately LLM-free.
"""

from pathlib import Path

import click

from . import __version__
from .case_designer import design_cases
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
def generate(spec: Path, out: Path, base_url: str) -> None:
    """Turn an OpenAPI spec into a review-ready pytest suite."""
    endpoints = parse_spec(spec)
    if not endpoints:
        raise click.ClickException(f"no operations found in {spec}")

    written = render_suite(endpoints, out, spec_name=spec.name, base_url=base_url)

    cases = [case for ep in endpoints for case in design_cases(ep)]
    needs_review = [c for c in cases if c.needs_review]

    click.echo(f"Parsed {len(endpoints)} endpoints from {spec}")
    click.echo(f"Wrote {len(cases)} cases to {out}/")
    for path in written:
        click.echo(f"  {path.name}")

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
