from specguard.drift_engine import BREAKING, INFO, WARNING, diff

ENDPOINT = "GET /v1/orders/{id}"


def schema(required=(), **properties):
    return {"type": "object", "required": sorted(required), "properties": dict(properties)}


def kinds(findings):
    return {(f.kind, f.field): f.severity for f in findings}


# --- breaking ---------------------------------------------------------------


def test_a_removed_required_field_is_breaking():
    baseline = schema(["id", "currency"], id={"type": "string"}, currency={"type": "string"})
    current = schema(["id"], id={"type": "string"})

    assert kinds(diff(baseline, current, ENDPOINT)) == {
        ("field_removed", "currency"): BREAKING
    }


def test_a_type_change_is_breaking():
    baseline = schema(["amount"], amount={"type": "number"})
    current = schema(["amount"], amount={"type": "string"})

    assert kinds(diff(baseline, current, ENDPOINT)) == {("type_changed", "amount"): BREAKING}


def test_a_rename_is_reported_as_a_removal_and_an_addition():
    baseline = schema(["postcode"], postcode={"type": "string"})
    current = schema([], post_code={"type": "string"})
    result = kinds(diff(baseline, current, ENDPOINT))

    assert result[("field_removed", "postcode")] == BREAKING
    assert result[("field_added", "post_code")] == INFO


def test_a_field_that_becomes_optional_is_breaking():
    baseline = schema(["currency"], currency={"type": "string"})
    current = schema([], currency={"type": "string"})

    assert kinds(diff(baseline, current, ENDPOINT)) == {
        ("field_no_longer_required", "currency"): BREAKING
    }


def test_a_removed_enum_value_is_breaking():
    baseline = schema([], status={"type": "string", "enum": ["created", "paid", "void"]})
    current = schema([], status={"type": "string", "enum": ["created", "paid"]})

    assert kinds(diff(baseline, current, ENDPOINT)) == {("enum_removed", "status"): BREAKING}


# --- warning / info ---------------------------------------------------------


def test_a_new_enum_value_is_a_warning():
    baseline = schema([], status={"type": "string", "enum": ["created", "paid"]})
    current = schema([], status={"type": "string", "enum": ["created", "paid", "refunded"]})

    assert kinds(diff(baseline, current, ENDPOINT)) == {("enum_added", "status"): WARNING}


def test_a_widened_type_is_a_warning_not_breaking():
    baseline = schema(["amount"], amount={"type": "number"})
    current = schema(["amount"], amount={"type": ["number", "string"]})

    assert kinds(diff(baseline, current, ENDPOINT)) == {("type_widened", "amount"): WARNING}


def test_a_new_optional_field_is_info():
    baseline = schema(["id"], id={"type": "string"})
    current = schema(["id"], id={"type": "string"}, updated_at={"type": "string"})

    assert kinds(diff(baseline, current, ENDPOINT)) == {("field_added", "updated_at"): INFO}


def test_an_identical_schema_produces_no_findings():
    both = schema(["id"], id={"type": "string"})
    assert diff(both, both, ENDPOINT) == []


# --- nesting ----------------------------------------------------------------


def test_drift_inside_a_nested_object_is_reported_with_a_dotted_path():
    baseline = schema(
        ["customer"],
        customer=schema(["postcode"], postcode={"type": "string"}),
    )
    current = schema(["customer"], customer=schema([], postcode={"type": "integer"}))
    result = kinds(diff(baseline, current, ENDPOINT))

    assert result[("type_changed", "customer.postcode")] == BREAKING
    assert result[("field_no_longer_required", "customer.postcode")] == BREAKING


def test_drift_inside_an_array_item_is_reported():
    baseline = {"type": "array", "items": schema(["id"], id={"type": "string"})}
    current = {"type": "array", "items": schema(["id"], id={"type": "integer"})}

    assert kinds(diff(baseline, current, ENDPOINT)) == {("type_changed", "[].id"): BREAKING}


def test_a_container_type_change_is_breaking():
    baseline = {"type": "array", "items": schema(["id"], id={"type": "string"})}
    current = schema(["id"], id={"type": "string"})

    assert kinds(diff(baseline, current, ENDPOINT)) == {("type_changed", ""): BREAKING}


# --- reporting detail -------------------------------------------------------


def test_every_finding_carries_the_endpoint_and_a_readable_detail():
    baseline = schema(["currency"], currency={"type": "string"})
    current = schema([], id={"type": "string"})

    for finding in diff(baseline, current, ENDPOINT):
        assert finding.endpoint == ENDPOINT
        assert finding.detail


def test_findings_are_ordered_most_severe_first():
    baseline = schema(["currency"], currency={"type": "string"}, amount={"type": "number"})
    current = schema([], amount={"type": "string"}, extra={"type": "string"})

    severities = [f.severity for f in diff(baseline, current, ENDPOINT)]
    assert severities == sorted(severities, key=[BREAKING, WARNING, INFO].index)


def test_an_empty_baseline_produces_no_findings():
    # Nothing was ever recorded, so nothing can have drifted.
    assert diff({}, schema(["id"], id={"type": "string"}), ENDPOINT) == []
