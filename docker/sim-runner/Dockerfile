# Simulation runner: FMPy over the exported FMU (default path), plus the client for the
# OpenModelica worker (compose profile `om`). Same layout as docker/api/Dockerfile.
FROM python:3.11.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
RUN mkdir -p src/aas_fluid_twin && touch src/aas_fluid_twin/__init__.py \
    && pip install ".[sim,store,api]" \
    && pip uninstall -y aas-fluid-twin

COPY src ./src
COPY scripts ./scripts
COPY data/fault_annotations.yaml ./data/fault_annotations.yaml
RUN pip install --no-deps .

ENV AAS_DATA_DIR=/app/data \
    AAS_BENCHMARK_DIR=/data/benchmark \
    AAS_ARTIFACT_DIR=/artifacts

EXPOSE 8000
CMD ["python", "-m", "aas_fluid_twin.simulation.service"]
