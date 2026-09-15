"""HTTP client for the AAS Part-2 repository API (Eclipse BaSyx)."""

from aas_fluid_twin.client.basyx import (
    BasyxClient,
    BasyxError,
    OperationResult,
    encode_id,
    encode_path,
)

__all__ = ["BasyxClient", "BasyxError", "OperationResult", "encode_id", "encode_path"]
