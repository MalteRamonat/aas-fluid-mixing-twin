"""FastAPI application: the time-series endpoint, the AAS metadata it is labelled with,
the simulation control, and the dashboard that uses all three.

``create_app`` takes its collaborators explicitly so tests can hand in fakes; the container
entry point (``python -m aas_fluid_twin.api``) builds them from the environment
(``AAS_TIMESERIES_DSN``, ``AAS_BASYX_URL``, ``AAS_SIM_RUNNER_URL``).

The dashboard is static files under ``web/`` — no build step, no CDN — mounted last so that
``/api/*`` always wins.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from aas_fluid_twin.api.aas_metadata import AasMetadata, default_metadata
from aas_fluid_twin.api.metadata import router as metadata_router
from aas_fluid_twin.api.simulations import SimRunner, default_runner
from aas_fluid_twin.api.simulations import router as simulation_router
from aas_fluid_twin.api.timeseries import router as timeseries_router
from aas_fluid_twin.store.models import TimeSeriesStore
from aas_fluid_twin.store.timescale import TimescaleStore

__all__ = ["WEB_ROOT", "create_app"]

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


def create_app(
    store: TimeSeriesStore | None = None,
    metadata: AasMetadata | None = None,
    sim_runner: SimRunner | None = None,
    *,
    serve_dashboard: bool = True,
) -> FastAPI:
    app = FastAPI(
        title="ModVA twin API",
        summary="Recorded and simulated runs, labelled from the AAS, plus the dashboard",
        version="0.2.0",
    )
    app.state.store = store if store is not None else TimescaleStore()
    app.state.metadata = metadata if metadata is not None else default_metadata()
    app.state.sim_runner = sim_runner if sim_runner is not None else default_runner()

    # The BaSyx Web UI and the dashboard may be served from other origins.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"]
    )
    app.include_router(timeseries_router)
    app.include_router(metadata_router)
    app.include_router(simulation_router)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        active = app.state.store
        detail: dict[str, Any] = {"status": "UP"}
        if isinstance(active, TimescaleStore):
            if not active.is_up():
                return {"status": "DOWN", "store": "unreachable"}
            detail["store"] = active.summary()
        return detail

    if serve_dashboard and WEB_ROOT.is_dir():

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(WEB_ROOT / "index.html")

        app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="dashboard")

    return app
