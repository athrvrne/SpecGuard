import pytest

from specguard.case_designer import design_cases
from specguard.spec_parser import parse_spec


@pytest.fixture(scope="module")
def by_id(petstore_path):
    return {ep.operation_id: ep for ep in parse_spec(petstore_path)}


def cases_of_kind(endpoint, kind):
    return [c for c in design_cases(endpoint) if c.kind == kind]


# --- happy path -------------------------------------------------------------


def test_every_endpoint_gets_exactly_one_happy_case(by_id):
    for ep in by_id.values():
        assert len(cases_of_kind(ep, "happy")) == 1


def test_happy_case_expects_the_specs_success_status(by_id):
    assert cases_of_kind(by_id["deletePet"], "happy")[0].expected_status == 204
    assert cases_of_kind(by_id["createPet"], "happy")[0].expected_status == 201


def test_happy_case_body_is_built_from_the_request_schema(by_id):
    case = cases_of_kind(by_id["createPet"], "happy")[0]
    assert case.body == {"name": "string", "tag": "string", "status": "available"}


def test_happy_case_for_a_bodyless_endpoint_sends_no_body(by_id):
    assert cases_of_kind(by_id["listPets"], "happy")[0].body is None


def test_enum_fields_use_a_declared_value_not_a_synthesised_one(by_id):
    case = cases_of_kind(by_id["createPet"], "happy")[0]
    assert case.body["status"] == "available"


def test_required_query_params_are_included_in_the_happy_path(by_id):
    case = cases_of_kind(by_id["listPets"], "happy")[0]
    assert case.query == {"status": "available"}


def test_path_params_are_substituted_into_the_url(by_id):
    case = cases_of_kind(by_id["showPetById"], "happy")[0]
    assert "{" not in case.path
    assert case.path.startswith("/pets/")


def test_a_synthesised_path_param_is_flagged_for_review(by_id):
    # /pets/{petId} has no example in the spec, so the id is a guess and the
    # test will 404 against a real API until a human supplies a real one.
    case = cases_of_kind(by_id["showPetById"], "happy")[0]
    assert case.needs_review is True
    assert "petId" in case.reason


def test_an_endpoint_without_path_params_is_not_flagged(by_id):
    assert cases_of_kind(by_id["listPets"], "happy")[0].needs_review is False


# --- validation -------------------------------------------------------------


def test_one_case_drops_each_required_field(by_id):
    dropped = {
        c.name.rsplit("_", 2)[-2]
        for c in cases_of_kind(by_id["createPet"], "validation")
        if c.name.endswith("_missing")
    }
    assert dropped == {"name", "status"}


def test_the_dropped_field_is_actually_absent_from_the_body(by_id):
    case = next(
        c
        for c in cases_of_kind(by_id["createPet"], "validation")
        if c.name.endswith("name_missing")
    )
    assert "name" not in case.body
    assert "status" in case.body


def test_one_case_sends_each_field_with_the_wrong_type(by_id):
    case = next(
        c
        for c in cases_of_kind(by_id["createPet"], "validation")
        if c.name.endswith("name_wrong_type")
    )
    assert not isinstance(case.body["name"], str)


def test_validation_cases_expect_the_error_code_the_spec_declares(by_id):
    # Petstore declares 422; an API declaring 400 must get 400, not a guess.
    cases = cases_of_kind(by_id["createPet"], "validation")
    assert cases
    assert all(c.expected_status == 422 for c in cases)


def test_endpoints_without_a_body_get_no_validation_cases(by_id):
    assert cases_of_kind(by_id["listPets"], "validation") == []


# --- boundary ---------------------------------------------------------------


def test_string_length_bounds_produce_an_accepted_and_a_rejected_case(by_id):
    # name is minLength 1, maxLength 40.
    cases = {c.name.rsplit("name_", 1)[-1]: c for c in cases_of_kind(by_id["createPet"], "boundary")}
    assert len(cases["min_length"].body["name"]) == 1
    assert cases["min_length"].expected_status == 201
    assert len(cases["max_length"].body["name"]) == 40
    assert cases["max_length"].expected_status == 201
    assert len(cases["under_min_length"].body["name"]) == 0
    assert cases["under_min_length"].expected_status == 422
    assert len(cases["over_max_length"].body["name"]) == 41
    assert cases["over_max_length"].expected_status == 422


def test_numeric_bounds_on_a_query_param_are_exercised(by_id):
    # limit is minimum 1, maximum 100.
    cases = {c.name.rsplit("limit_", 1)[-1]: c for c in cases_of_kind(by_id["listPets"], "boundary")}
    assert cases["minimum"].query["limit"] == 1
    assert cases["maximum"].query["limit"] == 100
    assert cases["under_minimum"].query["limit"] == 0
    assert cases["over_maximum"].query["limit"] == 101


def test_a_field_with_no_declared_bounds_gets_no_boundary_cases(by_id):
    names = [c.name for c in cases_of_kind(by_id["createPet"], "boundary")]
    assert not any("tag" in n for n in names)


# --- auth -------------------------------------------------------------------


def test_a_protected_endpoint_gets_an_unauthenticated_case(by_id):
    cases = cases_of_kind(by_id["showPetById"], "auth")
    assert len(cases) == 1
    assert cases[0].expected_status == 401


def test_the_auth_case_sends_no_credentials(by_id):
    case = cases_of_kind(by_id["showPetById"], "auth")[0]
    assert case.headers == {}
    assert case.send_auth is False


def test_a_public_endpoint_gets_no_auth_case(by_id):
    assert cases_of_kind(by_id["listPets"], "auth") == []


def test_deterministic_matrix_runs_without_a_provider(by_id):
    # The floor must stand on its own — this is the whole point of the design.
    assert design_cases(by_id["createPet"], llm=None) == design_cases(by_id["createPet"])


def test_falls_back_to_422_when_the_spec_declares_no_error_response(tmp_path):
    from specguard.spec_parser import parse_spec as parse

    spec = tmp_path / "silent.yaml"
    spec.write_text(
        """
openapi: 3.0.3
info: {title: Silent, version: '1.0'}
paths:
  /things:
    post:
      operationId: createThing
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [name]
              properties:
                name: {type: string}
      responses:
        '201': {description: ok}
"""
    )
    cases = [c for c in design_cases(parse(spec)[0]) if c.kind == "validation"]
    assert cases and all(c.expected_status == 422 for c in cases)
