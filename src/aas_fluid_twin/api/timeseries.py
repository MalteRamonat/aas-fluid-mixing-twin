"""The endpoint the AAS ``LinkedSegment``s point at, plus run listing.

``LinkedSegment.Endpoint`` is ``…/api/timeseries`` and ``LinkedSegment.Query`` is
``run_id=<id>``; the two concatenate into a plain GET here. ``channels``, ``from`` and ``to``
narrow the result, exactly as the segment's description says.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from aas_fluid_twin.api.schemas import RunOut, SeriesOut, run_out, series_out
from aas_fluid_twin.store.models import Origin, TimeSeriesStore

__all__ = ["get_store", "router"]

router = APIRouter(prefix="/api", tags=["timeseries"])


def get_store(request: Request) -> TimeSeriesStore:
    store: TimeSeriesStore = request.app.state.store
    return store


Store = Annotated[TimeSeriesStore, Depends(get_store)]


def _parse_channels(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        raise HTTPException(status_code=422, detail="channels must name at least one channel")
    return names


@router.get("/runs", response_model=list[RunOut])
def list_runs(store: Store, origin: Origin | None = None) -> list[RunOut]:
    return [run_out(r) for r in store.list_runs(origin)]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(store: Store, run_id: str) -> RunOut:
    record = store.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    return run_out(record)


@router.get("/runs/{run_id}/channels", response_model=list[str])
def list_channels(store: Store, run_id: str) -> list[str]:
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    return store.channels(run_id)


@router.get("/timeseries", response_model=SeriesOut)
def timeseries(
    store: Store,
    run_id: str,
    channels: str | None = Query(default=None, description="comma-separated channel names"),
    from_s: float | None = Query(default=None, alias="from", description="window start, s"),
    to_s: float | None = Query(default=None, alias="to", description="window end, s"),
) -> SeriesOut:
    if from_s is not None and to_s is not None and from_s > to_s:
        raise HTTPException(status_code=422, detail="from must not exceed to")
    result = store.query(run_id, _parse_channels(channels), from_s=from_s, to_s=to_s)
    if result is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    return series_out(result)
