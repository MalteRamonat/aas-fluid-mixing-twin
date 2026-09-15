"""Container entry point: ``python -m aas_fluid_twin.api``."""

from __future__ import annotations

import os

import uvicorn

from aas_fluid_twin.api.app import create_app


def main() -> None:
    uvicorn.run(
        create_app(),
        host=os.environ.get("AAS_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("AAS_API_PORT", "8000")),
        log_level=os.environ.get("AAS_API_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
