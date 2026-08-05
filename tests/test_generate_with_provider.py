import ast

import pytest
from click.testing import CliRunner

from specguard import cli as cli_module
from specguard.cli import cli

REPLY = """[
  {"name": "rejects_blank_name", "body": {"name": "   ", "status": "available"},
   "expected_status": 422, "reason": "description says the name must not be blank"}
]"""


class StubProvider:
    def complete(self, system, user, max_tokens=16000):
        return REPLY


@pytest.fixture
def stub_provider(monkeypatch):
    monkeypatch.setattr(cli_module, "get_provider", lambda name, model=None: StubProvider())


def generate(tmp_path, petstore_path, *extra):
    out = tmp_path / "generated"
    result = CliRunner().invoke(cli, ["generate", str(petstore_path), "--out", str(out), *extra])
    return result, out


def test_generate_runs_without_a_provider_by_default(tmp_path, petstore_path):
    result, out = generate(tmp_path, petstore_path)

    assert result.exit_code == 0, result.output
    assert "llm_extra" not in (out / "test_pets.py").read_text()


def test_provider_extras_land_in_the_generated_suite(tmp_path, petstore_path, stub_provider):
    result, out = generate(tmp_path, petstore_path, "--provider", "claude")
    source = (out / "test_pets.py").read_text()

    assert result.exit_code == 0, result.output
    assert "llm_1_rejects_blank_name" in source
    ast.parse(source)


def test_llm_cases_are_rendered_with_their_review_comment(tmp_path, petstore_path, stub_provider):
    _, out = generate(tmp_path, petstore_path, "--provider", "claude")
    source = (out / "test_pets.py").read_text()

    assert "# REVIEW: description says the name must not be blank" in source
    assert "@pytest.mark.specguard_llm" in source


def test_the_cli_reports_how_many_cases_the_model_proposed(tmp_path, petstore_path, stub_provider):
    result, _ = generate(tmp_path, petstore_path, "--provider", "claude")

    assert "1 case(s) marked REVIEW" in result.output or "proposed" in result.output.lower()


def test_an_unknown_provider_is_rejected_before_any_work(tmp_path, petstore_path):
    result, out = generate(tmp_path, petstore_path, "--provider", "gpt")

    assert result.exit_code != 0
    assert not out.exists()


def test_provider_none_is_explicitly_supported(tmp_path, petstore_path):
    result, _ = generate(tmp_path, petstore_path, "--provider", "none")
    assert result.exit_code == 0, result.output


def test_generated_suite_still_imports_nothing_from_specguard(
    tmp_path, petstore_path, stub_provider
):
    _, out = generate(tmp_path, petstore_path, "--provider", "claude")
    imported = set()
    for path in out.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

    assert "specguard" not in imported
