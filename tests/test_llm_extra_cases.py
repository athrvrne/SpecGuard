"""The LLM adds to the deterministic floor. It never replaces or overrides it."""

import pytest

from specguard.case_designer import design_cases
from specguard.spec_parser import parse_spec

GOOD = """Here are two extra cases:
```json
[
  {"name": "rejects_blank_name", "body": {"name": "   ", "status": "available"},
   "expected_status": 422, "reason": "description says the name must not be blank"},
  {"name": "rejects_unicode_only_name", "body": {"name": "\\u200b", "status": "available"},
   "expected_status": 422, "reason": "a zero-width space is blank to a human"}
]
```"""


class StubProvider:
    """Records what it was asked, returns what it was told to."""

    def __init__(self, reply=GOOD):
        self.reply = reply
        self.system = None
        self.user = None
        self.calls = 0

    def complete(self, system: str, user: str, max_tokens: int = 16000) -> str:
        self.calls += 1
        self.system, self.user = system, user
        return self.reply


class ExplodingProvider:
    def complete(self, system, user, max_tokens=16000):
        raise RuntimeError("connection refused")


@pytest.fixture(scope="module")
def create_pet(petstore_path):
    return next(ep for ep in parse_spec(petstore_path) if ep.operation_id == "createPet")


def extras(cases):
    return [c for c in cases if c.kind == "llm_extra"]


# --- the floor still stands -------------------------------------------------


def test_the_deterministic_cases_are_unchanged_when_a_provider_is_present(create_pet):
    floor = design_cases(create_pet)
    with_llm = design_cases(create_pet, llm=StubProvider())

    assert [c for c in with_llm if c.kind != "llm_extra"] == floor


def test_extras_are_appended_after_the_deterministic_cases(create_pet):
    cases = design_cases(create_pet, llm=StubProvider())
    kinds = [c.kind for c in cases]

    assert kinds[-2:] == ["llm_extra", "llm_extra"]
    assert "llm_extra" not in kinds[:-2]


def test_a_provider_failure_degrades_to_the_floor_instead_of_crashing(create_pet):
    assert design_cases(create_pet, llm=ExplodingProvider()) == design_cases(create_pet)


def test_an_unparseable_reply_degrades_to_the_floor(create_pet):
    assert design_cases(create_pet, llm=StubProvider("I'd rather not.")) == design_cases(create_pet)


def test_endpoints_with_no_field_descriptions_are_not_sent_to_the_model(petstore_path):
    # Nothing for the model to infer from, so spending a call is waste.
    list_pets = next(ep for ep in parse_spec(petstore_path) if ep.operation_id == "listPets")
    provider = StubProvider()

    design_cases(list_pets, llm=provider)

    assert provider.calls == 0


# --- the review gate --------------------------------------------------------


def test_every_llm_case_is_flagged_for_review(create_pet):
    assert all(c.needs_review for c in extras(design_cases(create_pet, llm=StubProvider())))


def test_every_llm_case_carries_the_models_stated_reason(create_pet):
    cases = extras(design_cases(create_pet, llm=StubProvider()))
    assert cases[0].reason == "description says the name must not be blank"


def test_llm_cases_inherit_the_endpoints_method_and_path(create_pet):
    case = extras(design_cases(create_pet, llm=StubProvider()))[0]
    assert (case.method, case.path) == ("POST", "/pets")


def test_llm_case_names_are_prefixed_so_they_cannot_collide_with_the_floor(create_pet):
    for case in extras(design_cases(create_pet, llm=StubProvider())):
        assert case.name.startswith("test_")
        assert "llm" in case.name


# --- what the model is given ------------------------------------------------


def test_the_prompt_carries_the_field_descriptions(create_pet):
    provider = StubProvider()
    design_cases(create_pet, llm=provider)

    assert "Display name; must not be blank." in provider.user


def test_the_prompt_carries_the_endpoint_and_request_schema(create_pet):
    provider = StubProvider()
    design_cases(create_pet, llm=provider)

    assert "POST /pets" in provider.user
    assert "minLength" in provider.user


def test_the_system_prompt_asks_for_json_only_and_forbids_restating_the_floor(create_pet):
    provider = StubProvider()
    design_cases(create_pet, llm=provider)

    assert "JSON" in provider.system
    assert "not" in provider.system.lower()
