"""Parsing what a model actually returns — not what it was asked to return.

Every case here is a shape a real model produces: prose preambles, markdown
fences, a wrapper object, trailing commentary, truncation. None of these call a
model; that is the point.
"""

from specguard.llm.parsing import parse_cases

CASE = '{"name": "expiry_must_be_future", "kind": "llm_extra", "body": {"exp_year": 2000}, "expected_status": 422, "reason": "description says exp must be a future date"}'


def test_a_bare_json_array_parses():
    assert len(parse_cases(f"[{CASE}]")) == 1


def test_a_prose_preamble_is_stripped():
    raw = f"Here are the additional test cases I'd suggest:\n\n[{CASE}]"
    assert len(parse_cases(raw)) == 1


def test_a_markdown_fence_is_stripped():
    raw = f"```json\n[{CASE}]\n```"
    assert parse_cases(raw)[0]["name"] == "expiry_must_be_future"


def test_a_fence_without_a_language_tag_is_stripped():
    assert len(parse_cases(f"```\n[{CASE}]\n```")) == 1


def test_trailing_commentary_after_the_array_is_ignored():
    raw = f"[{CASE}]\n\nLet me know if you'd like more cases."
    assert len(parse_cases(raw)) == 1


def test_an_object_wrapper_is_unwrapped():
    assert len(parse_cases(f'{{"cases": [{CASE}]}}')) == 1


def test_a_single_object_is_treated_as_one_case():
    assert len(parse_cases(CASE)) == 1


# --- refusing to guess ------------------------------------------------------


def test_malformed_json_yields_nothing_rather_than_raising():
    assert parse_cases("[{'name': 'oops',}]") == []


def test_a_truncated_response_yields_nothing():
    assert parse_cases(f"[{CASE[:40]}") == []


def test_an_empty_response_yields_nothing():
    assert parse_cases("") == []


def test_a_refusal_in_prose_yields_nothing():
    assert parse_cases("I can't propose test cases without seeing the schema.") == []


def test_a_json_array_of_the_wrong_shape_yields_nothing():
    assert parse_cases('["just", "some", "strings"]') == []


# --- per-case validation ----------------------------------------------------


def test_a_case_missing_a_required_field_is_dropped_not_the_whole_batch():
    raw = f'[{CASE}, {{"kind": "llm_extra", "reason": "no name or status"}}]'
    cases = parse_cases(raw)

    assert len(cases) == 1
    assert cases[0]["name"] == "expiry_must_be_future"


def test_a_non_integer_status_is_dropped():
    assert parse_cases('[{"name": "x", "expected_status": "422", "reason": "r"}]') == []


def test_a_case_with_no_reason_is_dropped():
    # The reason is what a human reads to approve or delete the case. Without
    # it the case is unreviewable, which defeats the whole review gate.
    assert parse_cases('[{"name": "x", "expected_status": 422}]') == []


def test_unknown_keys_are_ignored_rather_than_failing_the_case():
    raw = '[{"name": "x", "expected_status": 422, "reason": "r", "confidence": 0.9}]'
    assert len(parse_cases(raw)) == 1


def test_a_body_is_optional():
    assert parse_cases('[{"name": "x", "expected_status": 422, "reason": "r"}]')[0]["body"] is None
