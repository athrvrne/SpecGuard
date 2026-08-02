from dataclasses import asdict

from specguard.models import Finding, TestCase


def test_finding_serialises_to_the_drift_report_shape():
    finding = Finding(
        endpoint="GET /v1/orders/{id}",
        severity="breaking",
        kind="field_removed",
        field="currency",
        detail="was required in baseline, absent in current response",
    )

    assert asdict(finding) == {
        "endpoint": "GET /v1/orders/{id}",
        "severity": "breaking",
        "kind": "field_removed",
        "field": "currency",
        "detail": "was required in baseline, absent in current response",
    }


def test_finding_field_is_a_dotted_path_so_nested_drift_is_addressable():
    finding = Finding(
        endpoint="GET /v1/orders/{id}",
        severity="breaking",
        kind="type_changed",
        field="customer.address.postcode",
    )

    assert finding.field.split(".") == ["customer", "address", "postcode"]
    assert finding.detail == ""


def test_test_case_defaults_to_no_body_and_no_assertions():
    case = TestCase(
        name="test_list_pets_happy_path",
        kind="happy",
        method="GET",
        path="/pets",
        expected_status=200,
    )

    assert case.body is None
    assert case.headers == {}
    assert case.assertions == []
