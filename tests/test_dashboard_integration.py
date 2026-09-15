"""The dashboard against the live stack: assets served, metadata coming from the real AAS.

Needs ``docker compose up -d``. These are the checks a browser would otherwise have to make:
that the page and its vendored chart library are served, that channel metadata arrives from
the AAS repository (not from the local signal dictionary), and that the simulation form is
backed by the runner that will execute it.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.benchmark_data]

API = "http://localhost:8000"


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    client = httpx.Client(base_url=API, timeout=30.0)
    try:
        client.get("/api/health")
    except httpx.HTTPError:
        pytest.skip("API not reachable — docker compose up -d")
    return client


def test_dashboard_and_its_assets_are_served(client: httpx.Client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "<title>ModVA digital twin</title>" in page.text
    for asset in ("app.css", "js/app.js", "js/charts.js", "vendor/echarts.min.js"):
        response = client.get(f"/{asset}")
        assert response.status_code == 200, asset
    # The chart library is vendored, not pulled from a CDN at runtime.
    assert "cdn." not in page.text


def test_channel_metadata_comes_from_the_live_aas(client: httpx.Client) -> None:
    channels = client.get("/api/channels").json()
    assert len(channels) == 47
    by_name = {c["channel"]: c for c in channels}
    volume = by_name["Tank_B204_Volume"]
    assert volume["unit"] == "ml" and volume["title"] == "Tank B204 Volume"
    assert volume["semantic_id"] and volume["semantic_id"].startswith("http")
    # The channel the plant author called unreliable must reach the dashboard flagged.
    assert by_name["Pressure_below_B201"]["quality"] == "unreliable"
    assert by_name["Pressure_below_B201"]["quality_reason"]
    assert by_name["Valve_V201_opening"]["role"] == "actuator"


def test_the_links_the_dashboard_offers_actually_resolve(client: httpx.Client) -> None:
    links = client.get("/api/aas").json()
    repository = links["repository"].replace("aas-env", "localhost")
    for submodel_id in links["submodels"].values():
        encoded = httpx.URL(
            f"{repository}/submodels/"
            + __import__("base64").urlsafe_b64encode(submodel_id.encode()).decode().rstrip("=")
        )
        assert httpx.get(encoded, timeout=30).status_code == 200, submodel_id


def test_the_run_form_is_backed_by_the_runner_that_executes_it(client: httpx.Client) -> None:
    config = client.get("/api/simulation/config").json()
    assert "ModVA_faultcapable" in config["models"]
    assert config["backend"] == "openmodelica"
    handles = {p["id_short"]: p for p in config["parameters"] if p["fault_role"]}
    assert "V211_opening" in handles and handles["V211_opening"]["default"] == 0.0
    assert "EmbeddedDefault" in config["runnable_schedules"]


def test_an_impossible_run_is_refused_before_anything_starts(client: httpx.Client) -> None:
    before = len(client.get("/api/simulations").json())
    response = client.post(
        "/api/simulations",
        json={
            "stop_time": 10,
            "model": "ModVA_online_stable",
            "parameter_overrides": {"V211_opening": 0.5},
        },
    )
    assert response.status_code == 422 and "V211_opening" in response.text
    assert len(client.get("/api/simulations").json()) == before
