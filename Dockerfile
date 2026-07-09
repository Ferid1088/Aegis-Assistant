FROM python:3.14-slim

# uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# opencv-python (a docling dependency, used for table/layout detection) links against
# libGL/X11 shared libraries that python:3.14-slim doesn't ship -- observed for real:
# `import cv2` crashed every ingestion job with "libxcb.so.1: cannot open shared
# object file", permanently failing the pipeline before it ever reached the model.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 appuser

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# uv sync (above) creates .venv while still running as root -- COPY --chown only
# covers files copied in the layer above, not .venv from the earlier RUN step, so
# chown the whole tree once everything exists. Without this, `uv run` at container
# startup tries to reconcile/touch files inside .venv as appuser and fails with
# "Permission denied" on the root-owned files (observed for real: a crash trying to
# remove a stale package file during a startup re-sync check).
RUN chown -R appuser:appuser /app

# Air-gap: HF models cached into a mounted volume (see docker-compose.yml's hf_models)
ENV HF_HOME=/models/hf
ENV DEVICE=cpu

USER appuser

CMD ["uv", "run", "python", "healthcheck.py"]
