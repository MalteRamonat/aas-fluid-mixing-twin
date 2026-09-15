# The twin's Python services share one image: the API (default command) and the one-shot
# ingest (compose overrides the command). Slim base, no compiler — every dependency ships wheels.
FROM python:3.11.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependency layer first so source edits do not reinstall everything.
COPY pyproject.toml README.md ./
RUN mkdir -p src/aas_fluid_twin && touch src/aas_fluid_twin/__init__.py \
    && pip install ".[store,api]" \
    && pip uninstall -y aas-fluid-twin

COPY src ./src
COPY scripts ./scripts
COPY data/fault_annotations.yaml ./data/fault_annotations.yaml
RUN pip install --no-deps .

# Version-controlled inputs live in /app/data; the benchmark is mounted at /data/benchmark.
ENV AAS_DATA_DIR=/app/data \
    AAS_BENCHMARK_DIR=/data/benchmark

EXPOSE 8000
CMD ["python", "-m", "aas_fluid_twin.api"]
