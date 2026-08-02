from specguard.schema_inferer import infer, infer_schema


def responses(n, **overrides):
    """n near-identical order payloads, for exercising the sample-size gates."""
    return [
        {"id": f"o_{i}", "amount": 10.0 + i, "status": ["created", "paid", "void"][i % 3], **overrides}
        for i in range(n)
    ]


# --- required vs optional ---------------------------------------------------


def test_a_field_present_in_every_response_is_required():
    schema = infer_schema([{"id": "a", "name": "x"}, {"id": "b", "name": "y"}])
    assert schema["required"] == ["id", "name"]


def test_a_field_missing_from_one_response_is_optional():
    schema = infer_schema([{"id": "a", "nickname": "x"}, {"id": "b"}])
    assert schema["required"] == ["id"]
    assert "nickname" in schema["properties"]


# --- types ------------------------------------------------------------------


def test_a_consistent_type_is_recorded_as_a_plain_string():
    schema = infer_schema([{"amount": 1.5}, {"amount": 2.5}])
    assert schema["properties"]["amount"]["type"] == "number"


def test_a_field_seen_with_two_types_records_both():
    schema = infer_schema([{"amount": 1.5}, {"amount": "1.50"}])
    assert schema["properties"]["amount"]["type"] == ["number", "string"]


def test_null_does_not_become_a_type_but_is_recorded_as_nullable():
    result = infer([{"tag": "x"}, {"tag": None}])
    assert result["inferred_schema"]["properties"]["tag"]["type"] == "string"
    assert result["value_stats"]["tag"]["nullable"] is True


def test_a_field_never_null_is_not_marked_nullable():
    result = infer([{"tag": "x"}, {"tag": "y"}])
    assert result["value_stats"]["tag"]["nullable"] is False


# --- enum inference ---------------------------------------------------------


def test_a_small_stable_string_set_becomes_an_enum():
    schema = infer_schema(responses(30))
    assert schema["properties"]["status"]["enum"] == ["created", "paid", "void"]


def test_free_text_never_becomes_an_enum():
    payloads = [{"note": f"customer said {i}"} for i in range(30)]
    assert "enum" not in infer_schema(payloads)["properties"]["note"]


def test_no_enum_is_inferred_from_too_few_samples():
    # Three responses that happen to agree are not evidence of a closed set.
    schema = infer_schema([{"status": "paid"}, {"status": "paid"}, {"status": "paid"}])
    assert "enum" not in schema["properties"]["status"]


def test_enum_is_not_inferred_for_non_string_fields():
    schema = infer_schema([{"amount": 1} for _ in range(30)])
    assert "enum" not in schema["properties"]["amount"]


# --- nesting ----------------------------------------------------------------


def test_nested_objects_are_inferred_recursively():
    schema = infer_schema(
        [
            {"customer": {"id": "c1", "address": {"postcode": "SW1"}}},
            {"customer": {"id": "c2", "address": {"postcode": "EC2"}}},
        ]
    )
    address = schema["properties"]["customer"]["properties"]["address"]
    assert address["properties"]["postcode"]["type"] == "string"
    assert address["required"] == ["postcode"]


def test_an_optional_field_deep_in_a_nested_object_is_detected():
    schema = infer_schema(
        [
            {"customer": {"id": "c1", "vip": True}},
            {"customer": {"id": "c2"}},
        ]
    )
    assert schema["properties"]["customer"]["required"] == ["id"]


def test_value_stats_for_nested_fields_use_dotted_paths():
    stats = infer(
        [
            {"customer": {"address": {"postcode": "SW1"}}},
            {"customer": {"address": {"postcode": "EC2"}}},
        ]
    )["value_stats"]
    assert "customer.address.postcode" in stats


# --- arrays -----------------------------------------------------------------


def test_a_list_response_is_inferred_as_an_array():
    schema = infer_schema([[{"id": "a"}], [{"id": "b"}]])
    assert schema["type"] == "array"
    assert schema["items"]["properties"]["id"]["type"] == "string"


def test_items_across_every_list_response_are_pooled_into_one_sample():
    # One call returning 30 items is 30 observations, not one. This is what
    # makes collection endpoints cheap to baseline.
    schema = infer_schema([responses(30)])
    assert schema["items"]["properties"]["status"]["enum"] == ["created", "paid", "void"]


def test_an_optional_field_inside_a_list_is_detected():
    schema = infer_schema([[{"id": "a", "tag": "t"}, {"id": "b"}]])
    assert schema["items"]["required"] == ["id"]


def test_an_array_of_scalars_is_inferred():
    schema = infer_schema([{"tags": ["a", "b"]}, {"tags": ["c"]}])
    assert schema["properties"]["tags"]["type"] == "array"
    assert schema["properties"]["tags"]["items"]["type"] == "string"


# --- value stats ------------------------------------------------------------


def test_numeric_range_is_recorded():
    stats = infer([{"amount": 5}, {"amount": 1}, {"amount": 99}])["value_stats"]
    assert stats["amount"]["min"] == 1
    assert stats["amount"]["max"] == 99


def test_observed_values_are_recorded_for_an_inferred_enum():
    stats = infer(responses(30))["value_stats"]
    assert stats["status"]["observed_values"] == ["created", "paid", "void"]


# --- sample size ------------------------------------------------------------


def test_sample_size_counts_the_observations_the_schema_rests_on():
    assert infer(responses(30))["sample_size"] == 30


def test_sample_size_counts_items_not_calls_for_a_list_response():
    assert infer([responses(30)])["sample_size"] == 30


def test_a_low_sample_is_flagged_as_low_confidence():
    assert infer(responses(3))["low_confidence"] is True
    assert infer(responses(30))["low_confidence"] is False


def test_no_responses_yields_an_empty_schema_rather_than_an_error():
    result = infer([])
    assert result["sample_size"] == 0
    assert result["inferred_schema"] == {}
