"""Metadata endpoints: what the AAS says about channels, and where to see it in the AAS.

Every response here is read from the BaSyx repository (see :mod:`aas_fluid_twin.api.aas_metadata`).
If the repository is down these endpoints return 503 — the dashboard then tells the reader that
the AAS is unreachable instead of silently drawing unlabelled lines.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from aas_fluid_twin.api.aas_metadata import AasMetadata, AasUnavailableError
from aas_fluid_twin.api.schemas import AasOut, ChannelOut, channel_out

__all__ = ["get_metadata", "router"]

router = APIRouter(prefix="/api", tags=["metadata"])


def get_metadata(request: Request) -> AasMetadata:
    metadata: AasMetadata | None = getattr(request.app.state, "metadata", None)
    if metadata is None:
        raise HTTPException(status_code=503, detail="no AAS repository configured")
    return metadata


Metadata = Annotated[AasMetadata, Depends(get_metadata)]


@router.get("/channels", response_model=list[ChannelOut])
def list_channels(metadata: Metadata) -> list[ChannelOut]:
    """Channel metadata from the AssetInterfacesDescription and its ConceptDescriptions."""
    try:
        return [channel_out(c) for c in metadata.channels()]
    except AasUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/aas", response_model=AasOut)
def aas_links(metadata: Metadata) -> AasOut:
    """Where the same information lives in the AAS, for the dashboard's provenance links."""
    links = metadata.links()
    return AasOut(repository=links.repository, web_ui=links.web_ui, submodels=links.submodels)


@router.post("/aas/refresh", status_code=204)
def refresh(metadata: Metadata) -> None:
    """Drop the metadata cache — after a rebuild and push of the environment."""
    metadata.refresh()
