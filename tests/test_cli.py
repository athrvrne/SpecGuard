from click.testing import CliRunner

from specguard.cli import cli


def test_generate_writes_a_suite(tmp_path, petstore_path):
    out = tmp_path / "generated"
    result = CliRunner().invoke(cli, ["generate", str(petstore_path), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert (out / "test_pets.py").exists()
    assert (out / "conftest.py").exists()


def test_generate_reports_what_it_wrote(tmp_path, petstore_path):
    out = tmp_path / "generated"
    result = CliRunner().invoke(cli, ["generate", str(petstore_path), "--out", str(out)])

    assert "4 endpoints" in result.output
    assert "test_pets.py" in result.output


def test_generate_warns_about_cases_needing_review(tmp_path, petstore_path):
    out = tmp_path / "generated"
    result = CliRunner().invoke(cli, ["generate", str(petstore_path), "--out", str(out)])

    assert "review" in result.output.lower()


def test_generate_is_llm_free_by_default(tmp_path, petstore_path):
    # No provider flag must mean no model call and no import of one.
    out = tmp_path / "generated"
    result = CliRunner().invoke(cli, ["generate", str(petstore_path), "--out", str(out)])

    assert result.exit_code == 0
    assert "provider" not in result.output.lower()


def test_missing_spec_fails_cleanly(tmp_path):
    result = CliRunner().invoke(cli, ["generate", str(tmp_path / "nope.yaml")])

    assert result.exit_code != 0
    assert "nope.yaml" in result.output
