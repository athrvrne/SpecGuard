import requests
from click.testing import CliRunner

from specguard import demo_api
from specguard.cli import cli
from specguard.demo_api import DemoServer, apply_drift

AUTH = {"Authorization": "Bearer t"}


def get(url, path, **kwargs):
    return requests.get(f"{url}{path}", **kwargs)


# --- the healthy API --------------------------------------------------------


def test_serves_a_pet_conforming_to_the_bundled_spec():
    with DemoServer() as url:
        body = get(url, "/pets/p_1", headers=AUTH).json()

    assert set(body) == {"id", "name", "tag", "status"}


def test_the_server_reports_the_url_it_bound_to():
    with DemoServer() as url:
        assert url.startswith("http://127.0.0.1:")


# --- staged drift -----------------------------------------------------------


def test_rename_makes_the_api_return_the_new_field_name(restore_demo_api):
    apply_drift(rename="name:pet_name")
    with DemoServer() as url:
        body = get(url, "/pets/p_1", headers=AUTH).json()

    assert "name" not in body
    assert body["pet_name"] == "Rex"


def test_rename_affects_the_collection_endpoint_too(restore_demo_api):
    apply_drift(rename="name:pet_name")
    with DemoServer() as url:
        body = get(url, "/pets?status=available").json()

    assert "pet_name" in body[0]


def test_add_introduces_a_new_optional_field(restore_demo_api):
    apply_drift(add="seen_at")
    with DemoServer() as url:
        body = get(url, "/pets/p_1", headers=AUTH).json()

    assert "seen_at" in body
    assert "name" in body


def test_lax_stops_the_api_rejecting_a_bad_payload(restore_demo_api):
    apply_drift(lax=True)
    with DemoServer() as url:
        response = requests.post(f"{url}/pets", json={"name": ""}, headers=AUTH)

    assert response.status_code == 201


def test_an_unrecognised_rename_argument_is_rejected(restore_demo_api):
    try:
        apply_drift(rename="justoneword")
    except ValueError as exc:
        assert "OLD:NEW" in str(exc)
    else:
        raise AssertionError("expected a ValueError")


def test_no_flags_leaves_the_api_healthy(restore_demo_api):
    apply_drift()
    with DemoServer() as url:
        assert "name" in get(url, "/pets/p_1", headers=AUTH).json()


# --- the command ------------------------------------------------------------


def test_demo_is_a_documented_command():
    result = CliRunner().invoke(cli, ["--help"])
    assert "demo" in result.output


def test_demo_help_explains_how_to_stage_drift():
    result = CliRunner().invoke(cli, ["demo", "--help"])
    assert "--rename" in result.output
    assert "--port" in result.output


def test_the_demo_module_is_importable_without_the_test_suite():
    # It ships in the wheel, so `pip install specguard` is enough to run it.
    assert demo_api.__name__ == "specguard.demo_api"
