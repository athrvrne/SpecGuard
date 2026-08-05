"""``TestCase`` list -> pytest source.

Deterministic and snapshot-testable: the same cases always render byte-identical
output. The result is plain pytest over ``requests`` — nothing it emits imports
SpecGuard, so a generated suite outlives the tool that wrote it.
"""

from datetime import datetime, timezone
from pathlib import Path
from pprint import pformat
from typing import NamedTuple

from jinja2 import Environment, PackageLoader, StrictUndefined

from .case_designer import design_cases
from .models import EndpointModel, TestCase

# Written once and then left alone, so a human can edit them without fear of a
# regeneration wiping the change.
SCAFFOLD_ONCE = ("conftest.py", "schemas.py", "README.md")


def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("specguard", "templates"),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["repr"] = repr
    env.filters["pyliteral"] = lambda value: pformat(value, indent=4, width=88, sort_dicts=False)
    return env


def module_name_for(ep: EndpointModel) -> str:
    """Group endpoints into modules by their first path segment."""
    segments = [s for s in ep.path.strip("/").split("/") if s and not s.startswith("{")]
    return f"test_{segments[0].replace('-', '_') if segments else 'root'}.py"


def render_module(
    groups: list[tuple[EndpointModel, list[TestCase]]], spec_name: str = "the spec"
) -> str:
    """Render one pytest module for a group of endpoints."""
    schema_names = sorted(
        {
            assertion["schema_name"]
            for _, cases in groups
            for case in cases
            for assertion in case.assertions
            if assertion.get("kind") == "json_schema"
        }
    )
    template = _environment().get_template("test_module.py.j2")
    return template.render(groups=groups, schema_names=schema_names, spec_name=spec_name)


class RenderedSuite(NamedTuple):
    """What a generation run produced."""

    files: list[Path]
    cases: list[TestCase]


def render_suite(
    endpoints: list[EndpointModel],
    out_dir: str | Path,
    *,
    llm=None,
    spec_name: str = "the spec",
    base_url: str = "",
) -> "RenderedSuite":
    """Write a full suite to ``out_dir``.

    Returns both the files written and the cases they came from, so a caller
    that wants to report on the cases doesn't have to design them a second
    time — which, with a provider configured, would mean paying for every
    model call twice.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    env = _environment()

    schemas: dict[str, dict] = {}
    grouped: dict[str, list[tuple[EndpointModel, list[TestCase]]]] = {}
    designed: list[TestCase] = []
    for ep in endpoints:
        cases = design_cases(ep, llm=llm)
        _attach_schema_assertions(ep, cases, schemas)
        grouped.setdefault(module_name_for(ep), []).append((ep, cases))
        designed += cases

    written = []
    for module, groups in sorted(grouped.items()):
        path = out_dir / module
        path.write_text(render_module(groups, spec_name=spec_name))
        written.append(path)

    written += _scaffold(env, out_dir, schemas, spec_name, base_url)
    return RenderedSuite(files=written, cases=designed)


def _attach_schema_assertions(
    ep: EndpointModel, cases: list[TestCase], schemas: dict[str, dict]
) -> None:
    """Give each happy case a JSON Schema assertion, if the spec described one."""
    if not ep.response_schema:
        return
    name = _schema_const_name(ep)
    schemas[name] = ep.response_schema
    for case in cases:
        if case.kind == "happy":
            case.assertions.append({"kind": "json_schema", "schema_name": name})


def _schema_const_name(ep: EndpointModel) -> str:
    stem = ep.operation_id or f"{ep.method}_{ep.path}"
    cleaned = "".join(c if c.isalnum() else "_" for c in stem).strip("_")
    return f"{cleaned.upper()}_RESPONSE"


def _scaffold(
    env: Environment,
    out_dir: Path,
    schemas: dict[str, dict],
    spec_name: str,
    base_url: str,
) -> list[Path]:
    """Write the support files, but never over one that already exists."""
    context = {
        "spec_name": spec_name,
        "base_url": base_url,
        "out_dir": out_dir.name,
        "schemas": sorted(schemas.items()),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    written = []
    for name in SCAFFOLD_ONCE:
        path = out_dir / name
        if path.exists():
            continue
        path.write_text(env.get_template(f"{name}.j2").render(**context))
        written.append(path)
    return written
