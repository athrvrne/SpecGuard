import json

import requests

from specguard.demo_api import DemoServer

from specguard.runner import Recorder, endpoint_key


# --- endpoint keys ----------------------------------------------------------


def test_a_concrete_url_is_folded_back_onto_its_templated_route():
    routes = ["/pets", "/pets/{petId}"]
    assert endpoint_key("GET", "/pets/p_1", routes) == "GET /pets/{petId}"
    assert endpoint_key("GET", "/pets", routes) == "GET /pets"


def test_an_unknown_url_keeps_its_literal_path():
    assert endpoint_key("GET", "/health", ["/pets"]) == "GET /health"


def test_query_strings_are_not_part_of_the_key():
    assert endpoint_key("GET", "/pets?status=available", ["/pets"]) == "GET /pets"


def test_a_multi_segment_route_is_matched_positionally():
    routes = ["/users/{userId}/orders/{orderId}"]
    key = endpoint_key("GET", "/users/u_1/orders/o_9", routes)
    assert key == "GET /users/{userId}/orders/{orderId}"


# --- recording --------------------------------------------------------------


def test_recording_captures_responses_grouped_by_endpoint():
    with DemoServer() as base_url, Recorder(["/pets", "/pets/{petId}"]) as recorder:
        requests.get(f"{base_url}/pets?status=available")
        requests.get(f"{base_url}/pets/p_1", headers={"Authorization": "Bearer t"})

    assert set(recorder.captured) == {"GET /pets", "GET /pets/{petId}"}


def test_repeated_calls_accumulate_into_one_endpoint():
    with DemoServer() as base_url, Recorder(["/pets"]) as recorder:
        for _ in range(3):
            requests.get(f"{base_url}/pets?status=available")

    assert len(recorder.captured["GET /pets"]["bodies"]) == 3


def test_the_observed_status_is_recorded():
    with DemoServer() as base_url, Recorder(["/pets"]) as recorder:
        requests.get(f"{base_url}/pets?status=available")

    assert recorder.captured["GET /pets"]["statuses"] == [200]


def test_error_responses_are_captured_but_kept_separate_from_success():
    with DemoServer() as base_url, Recorder(["/pets"]) as recorder:
        requests.get(f"{base_url}/pets?status=available")
        requests.get(f"{base_url}/pets?status=bogus")  # 422

    captured = recorder.captured["GET /pets"]
    assert captured["statuses"] == [200, 422]
    # Only 2xx bodies describe the contract; a 422 body is a different shape.
    assert len(captured["bodies"]) == 1


def test_non_json_responses_are_ignored():
    with DemoServer() as base_url, Recorder(["/pets/{petId}"]) as recorder:
        requests.delete(f"{base_url}/pets/p_1", headers={"Authorization": "Bearer t"})

    assert recorder.captured["DELETE /pets/{petId}"]["bodies"] == []


def test_recording_stops_when_the_recorder_exits():
    with DemoServer() as base_url:
        with Recorder(["/pets"]) as recorder:
            requests.get(f"{base_url}/pets?status=available")
        requests.get(f"{base_url}/pets?status=available")

    assert len(recorder.captured["GET /pets"]["bodies"]) == 1


def test_responses_still_reach_the_caller_untouched():
    with DemoServer() as base_url, Recorder(["/pets"]):
        response = requests.get(f"{base_url}/pets?status=available")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Rex"


def test_captured_payload_is_json_serialisable():
    with DemoServer() as base_url, Recorder(["/pets"]) as recorder:
        requests.get(f"{base_url}/pets?status=available")

    json.dumps(recorder.captured)
