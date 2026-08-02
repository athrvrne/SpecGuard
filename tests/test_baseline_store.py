import json

import pytest

from specguard.baseline_store import build_baseline, load_baseline, write_baseline

CAPTURED = {
    "GET /pets": {
        "statuses": [200, 200],
        "bodies": [[{"id": "p_1", "name": "Rex", "status": "available"}]],
    },
    "DELETE /pets/{petId}": {"statuses": [204], "bodies": []},
}


def test_baseline_records_a_schema_per_endpoint():
    baseline = build_baseline(CAPTURED)
    entry = baseline["endpoints"]["GET /pets"]
    assert entry["inferred_schema"]["type"] == "array"
    assert entry["success_status"] == 200


def test_endpoints_with_no_json_body_are_recorded_without_a_schema():
    entry = build_baseline(CAPTURED)["endpoints"]["DELETE /pets/{petId}"]
    assert entry["success_status"] == 204
    assert entry["inferred_schema"] == {}


def test_sample_size_and_confidence_are_carried_into_the_baseline():
    entry = build_baseline(CAPTURED)["endpoints"]["GET /pets"]
    assert entry["sample_size"] == 1
    assert entry["low_confidence"] is True


def test_baseline_is_versioned_and_timestamped():
    baseline = build_baseline(CAPTURED)
    assert baseline["version"] == 1
    assert baseline["recorded_at"]


def test_baseline_round_trips_through_disk(tmp_path):
    path = tmp_path / "baseline.json"
    write_baseline(build_baseline(CAPTURED), path)

    assert load_baseline(path)["endpoints"].keys() == CAPTURED.keys()


def test_baseline_is_plain_indented_json_so_it_diffs_in_git(tmp_path):
    path = tmp_path / "baseline.json"
    write_baseline(build_baseline(CAPTURED), path)
    text = path.read_text()

    assert text.startswith("{\n")
    assert text.endswith("\n")
    json.loads(text)


def test_loading_a_missing_baseline_fails_with_a_useful_message(tmp_path):
    with pytest.raises(FileNotFoundError, match="baseline"):
        load_baseline(tmp_path / "nope.json")
