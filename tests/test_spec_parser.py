import pytest

from specguard.spec_parser import parse_spec


@pytest.fixture(scope="module")
def endpoints(petstore_path):
    return parse_spec(petstore_path)


@pytest.fixture
def by_id(endpoints):
    return {ep.operation_id: ep for ep in endpoints}


def test_parses_one_endpoint_per_operation(endpoints):
    assert [(ep.method, ep.path) for ep in endpoints] == [
        ("GET", "/pets"),
        ("POST", "/pets"),
        ("GET", "/pets/{petId}"),
        ("DELETE", "/pets/{petId}"),
    ]


def test_carries_the_operation_id(by_id):
    assert set(by_id) == {"listPets", "createPet", "showPetById", "deletePet"}


def test_collects_query_params_with_their_schema(by_id):
    assert by_id["listPets"].query_params == [
        {
            "name": "limit",
            "required": False,
            "schema": {
                "type": "integer",
                "format": "int32",
                "minimum": 1,
                "maximum": 100,
            },
            "description": "How many items to return at one time (max 100).",
        },
        {
            "name": "status",
            "required": True,
            "schema": {"type": "string", "enum": ["available", "pending", "sold"]},
            "description": "",
        },
    ]


def test_inherits_path_level_params_declared_beside_the_operation(by_id):
    assert by_id["showPetById"].path_params == [
        {
            "name": "petId",
            "required": True,
            "schema": {"type": "string"},
            "description": "The id of the pet to operate on.",
        },
    ]


def test_separates_path_params_from_query_params(by_id):
    assert by_id["listPets"].path_params == []
    assert by_id["showPetById"].query_params == []


def test_resolves_request_body_ref_into_an_inline_schema(by_id):
    assert by_id["createPet"].request_schema == {
        "type": "object",
        "required": ["name", "status"],
        "properties": {
            "name": {
                "type": "string",
                "description": "Display name; must not be blank.",
                "minLength": 1,
                "maxLength": 40,
            },
            "tag": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["available", "pending", "sold"],
            },
        },
    }


def test_request_schema_is_none_when_the_operation_takes_no_body(by_id):
    assert by_id["listPets"].request_schema is None
    assert by_id["deletePet"].request_schema is None


def test_resolves_refs_nested_inside_the_response_schema(by_id):
    schema = by_id["listPets"].response_schema
    assert schema["type"] == "array"
    assert schema["items"]["required"] == ["id", "name", "status"]


def test_response_schema_is_none_for_a_bodyless_success(by_id):
    assert by_id["deletePet"].response_schema is None


def test_success_status_is_the_lowest_declared_2xx(by_id):
    assert by_id["listPets"].success_status == 200
    assert by_id["createPet"].success_status == 201
    assert by_id["deletePet"].success_status == 204


def test_records_every_numeric_status_the_operation_declares(by_id):
    # The case designer needs these to expect the API's real error codes rather
    # than guessing 422; "default" is not a status and is dropped.
    assert by_id["createPet"].declared_statuses == [201, 422]
    assert by_id["listPets"].declared_statuses == [200]
    assert by_id["deletePet"].declared_statuses == [204, 404]


def test_carries_the_human_description_of_the_operation(by_id):
    assert by_id["listPets"].description == "List all pets"


def test_collects_field_descriptions_the_schema_cannot_encode(by_id):
    # These are the natural-language notes the LLM reads in the Generate half;
    # a plain JSON Schema check can never enforce them.
    assert by_id["createPet"].field_descriptions == {
        "name": "Display name; must not be blank.",
    }


def test_field_descriptions_is_empty_without_a_request_body(by_id):
    assert by_id["showPetById"].field_descriptions == {}


def test_operations_inherit_the_document_wide_security_requirement(by_id):
    assert by_id["createPet"].requires_auth is True
    assert by_id["showPetById"].requires_auth is True


def test_an_empty_operation_security_list_opts_out_of_auth(by_id):
    assert by_id["listPets"].requires_auth is False


def test_recursive_schema_ref_terminates(tmp_path):
    spec = tmp_path / "recursive.yaml"
    spec.write_text(
        """
openapi: 3.0.3
info: {title: Tree, version: '1.0'}
paths:
  /nodes:
    post:
      operationId: createNode
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/Node'}
      responses:
        '201': {description: ok}
components:
  schemas:
    Node:
      type: object
      properties:
        name: {type: string}
        parent: {$ref: '#/components/schemas/Node'}
"""
    )

    schema = parse_spec(spec)[0].request_schema

    assert schema["properties"]["name"] == {"type": "string"}
    assert schema["properties"]["parent"] == {"$ref": "#/components/schemas/Node"}
