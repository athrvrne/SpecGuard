import ast

import pytest

from specguard.case_designer import design_cases
from specguard.spec_parser import parse_spec
from specguard.test_renderer import module_name_for, render_module, render_suite


@pytest.fixture(scope="module")
def endpoints(petstore_path):
    return parse_spec(petstore_path)


@pytest.fixture(scope="module")
def by_id(endpoints):
    return {ep.operation_id: ep for ep in endpoints}


@pytest.fixture(scope="module")
def pets_module(by_id):
    ep = by_id["createPet"]
    return render_module([(ep, design_cases(ep))])


def test_rendered_module_is_valid_python(pets_module):
    ast.parse(pets_module)


def test_every_case_becomes_a_test_function(by_id, pets_module):
    ep = by_id["createPet"]
    tree = ast.parse(pets_module)
    rendered = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert {c.name for c in design_cases(ep)} <= rendered


def test_test_functions_take_the_api_fixture(pets_module):
    tree = ast.parse(pets_module)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            assert "api" in [a.arg for a in node.args.args]


def test_cases_needing_review_carry_a_review_comment(by_id):
    ep = by_id["showPetById"]
    source = render_module([(ep, design_cases(ep))])
    assert "REVIEW:" in source
    assert "path parameter(s) petId were invented" in source


def test_a_case_that_stands_on_its_own_gets_no_review_comment(by_id):
    ep = by_id["listPets"]
    source = render_module([(ep, design_cases(ep))])
    assert "REVIEW:" not in source


def test_the_auth_case_explicitly_drops_credentials(by_id):
    ep = by_id["showPetById"]
    source = render_module([(ep, design_cases(ep))])
    assert "auth=False" in source


def test_rendering_is_deterministic(by_id):
    ep = by_id["createPet"]
    cases = design_cases(ep)
    assert render_module([(ep, cases)]) == render_module([(ep, cases)])


def test_modules_are_grouped_by_the_first_path_segment(by_id):
    assert module_name_for(by_id["listPets"]) == "test_pets.py"
    assert module_name_for(by_id["showPetById"]) == "test_pets.py"


# --- suite scaffolding ------------------------------------------------------


def test_suite_writes_one_module_per_group_plus_scaffolding(tmp_path, endpoints):
    render_suite(endpoints, tmp_path)
    written = {p.name for p in tmp_path.iterdir()}
    assert written == {"test_pets.py", "conftest.py", "schemas.py", "README.md"}


def test_scaffolding_is_valid_python(tmp_path, endpoints):
    render_suite(endpoints, tmp_path)
    ast.parse((tmp_path / "conftest.py").read_text())
    ast.parse((tmp_path / "schemas.py").read_text())


def test_regenerating_never_clobbers_an_edited_conftest(tmp_path, endpoints):
    render_suite(endpoints, tmp_path)
    conftest = tmp_path / "conftest.py"
    conftest.write_text("# my own fixture\n")

    render_suite(endpoints, tmp_path)

    assert conftest.read_text() == "# my own fixture\n"


def test_regenerating_does_refresh_the_test_modules(tmp_path, endpoints):
    render_suite(endpoints, tmp_path)
    module = tmp_path / "test_pets.py"
    module.write_text("# stale\n")

    render_suite(endpoints, tmp_path)

    assert module.read_text() != "# stale\n"


def test_generated_suite_does_not_import_specguard(tmp_path, endpoints):
    # The suite must survive SpecGuard being uninstalled. Env var and marker
    # names may mention it; a runtime dependency may not.
    render_suite(endpoints, tmp_path)
    imported = set()
    for path in tmp_path.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

    assert imported == {"os", "pytest", "requests", "jsonschema", "schemas"}


# --- template overrides -----------------------------------------------------


def test_a_user_template_replaces_the_built_in_one(tmp_path, by_id):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "test_module.py.j2").write_text("# my house style\n")

    source = render_module(
        [(by_id["listPets"], design_cases(by_id["listPets"]))], template_dir=templates
    )

    assert source.strip() == "# my house style"


def test_templates_not_overridden_fall_back_to_the_built_ins(tmp_path, endpoints):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "test_module.py.j2").write_text("# my house style\n")
    out = tmp_path / "generated"

    render_suite(endpoints, out, template_dir=templates)

    assert (out / "test_pets.py").read_text().strip() == "# my house style"
    assert "def api(" in (out / "conftest.py").read_text()  # still the built-in


def test_a_missing_template_dir_is_rejected_clearly(tmp_path, by_id):
    with pytest.raises(FileNotFoundError, match="template"):
        render_module([(by_id["listPets"], [])], template_dir=tmp_path / "nope")
