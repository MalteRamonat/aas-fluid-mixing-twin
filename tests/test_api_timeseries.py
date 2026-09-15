"""The HTTP contract of the LinkedSegment endpoint, against an in-memory store.

``LinkedSegment.Endpoint`` + ``?`` + ``LinkedSegment.Query`` must be a valid GET here — that
is what makes the AAS reference resolvable. The database round trip is
``tests/test_store_integration.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from aas_fluid_twin.api import create_app
from aas_fluid_twin.store import FaultWindow, Origin, RunRecord, SeriesResult


class FakeStore:
    def __init__(self) -> None:
        start = datetime(2024, 1, 22, 0, 24, 59)
        self.runs = {
            "dataset_10_leakage": RunRecord(
                run_id="dataset_10_leakage",
                origin=Origin.MEASURED,
                scenario="leakage",
                anomaly_label=1,
                started_at=start,
                ended_at=start + timedelta(seconds=600),
                duration_s=600.0,
                record_count=3,
                schema_variant="full",
                source_file="dataset_10_leakage.csv",
                fault_windows=(FaultWindow(1, 66.0, None, "operator_log"),),
            ),
            "sim_abc": RunRecord(
                run_id="sim_abc",
                origin=Origin.SIMULATED,
                scenario="normal_behaviour",
                anomaly_label=0,
                started_at=start,
                ended_at=start + timedelta(seconds=600),
                duration_s=600.0,
                record_count=3,
                schema_variant="simulated",
                params={"stopTime": 600},
            ),
        }
        self.t = [0.6, 65.0, 70.0]
        self.ts = [start + timedelta(seconds=s) for s in self.t]
        self.data: dict[str, dict[str, list[float | None]]] = {
            "dataset_10_leakage": {"a": [1.0, 2.0, 3.0], "b": [None, 5.0, 6.0]},
            "sim_abc": {"a": [1.1, 2.1, 3.1]},
        }
        self.calls: list[tuple[str, Sequence[str] | None, float | None, float | None]] = []

    def list_runs(self, origin: Origin | None = None) -> list[RunRecord]:
        return [r for r in self.runs.values() if origin is None or r.origin is origin]

    def get_run(self, run_id: str) -> RunRecord | None:
        return self.runs.get(run_id)

    def channels(self, run_id: str) -> list[str]:
        return sorted(self.data[run_id])

    def query(
        self,
        run_id: str,
        channels: Sequence[str] | None = None,
        *,
        from_s: float | None = None,
        to_s: float | None = None,
    ) -> SeriesResult | None:
        self.calls.append((run_id, channels, from_s, to_s))
        record = self.runs.get(run_id)
        if record is None:
            return None
        keep = [
            i
            for i, t in enumerate(self.t)
            if (from_s is None or t >= from_s) and (to_s is None or t <= to_s)
        ]
        wanted = list(channels) if channels is not None else sorted(self.data[run_id])
        return SeriesResult(
            run_id=run_id,
            origin=record.origin,
            t_rel_s=[self.t[i] for i in keep],
            timestamps=[self.ts[i] for i in keep],
            labels=[1 if self.t[i] >= 66.0 and record.anomaly_label else 0 for i in keep],
            channels={c: [self.data[run_id].get(c, [None] * 3)[i] for i in keep] for c in wanted},
        )


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def client(store: FakeStore) -> TestClient:
    return TestClient(create_app(store))


def test_linked_segment_endpoint_and_query_concatenate_into_a_valid_get(
    client: TestClient,
) -> None:
    endpoint, query = "/api/timeseries", "run_id=dataset_10_leakage"  # as in the AAS
    response = client.get(f"{endpoint}?{query}")
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "dataset_10_leakage"
    assert body["origin"] == "measured"
    assert body["t_rel_s"] == [0.6, 65.0, 70.0]
    assert body["labels"] == [0, 0, 1]  # onset at 66 s
    assert body["channels"] == {"a": [1.0, 2.0, 3.0], "b": [None, 5.0, 6.0]}
    assert body["timestamps"][0] == "2024-01-22T00:24:59.600000"


def test_channels_and_window_are_passed_through(client: TestClient, store: FakeStore) -> None:
    response = client.get("/api/timeseries?run_id=dataset_10_leakage&channels=b,a&from=60&to=66")
    assert response.status_code == 200
    assert store.calls[-1] == ("dataset_10_leakage", ["b", "a"], 60.0, 66.0)
    body = response.json()
    assert body["t_rel_s"] == [65.0]
    assert list(body["channels"]) == ["b", "a"]


def test_unknown_run_is_404_and_bad_window_is_422(client: TestClient) -> None:
    assert client.get("/api/timeseries?run_id=nope").status_code == 404
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/nope/channels").status_code == 404
    assert client.get("/api/timeseries?run_id=sim_abc&from=10&to=5").status_code == 422
    assert client.get("/api/timeseries?run_id=sim_abc&channels=,").status_code == 422
    assert client.get("/api/timeseries").status_code == 422  # run_id is required


def test_runs_listing_filters_by_origin(client: TestClient) -> None:
    everything = client.get("/api/runs").json()
    assert [r["run_id"] for r in everything] == ["dataset_10_leakage", "sim_abc"]
    measured = client.get("/api/runs?origin=measured").json()
    assert [r["run_id"] for r in measured] == ["dataset_10_leakage"]
    assert measured[0]["fault_windows"] == [
        {"label": 1, "onset_s": 66.0, "end_s": None, "source": "operator_log"}
    ]
    simulated = client.get("/api/runs?origin=simulated").json()
    assert simulated[0]["params"] == {"stopTime": 600}
    assert client.get("/api/runs?origin=guessed").status_code == 422


def test_run_detail_and_channels(client: TestClient) -> None:
    detail = client.get("/api/runs/dataset_10_leakage").json()
    assert detail["record_count"] == 3
    assert detail["source_file"] == "dataset_10_leakage.csv"
    assert client.get("/api/runs/dataset_10_leakage/channels").json() == ["a", "b"]


def test_health_reports_up_with_a_fake_store(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "UP"}
