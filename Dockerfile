FROM python:3.14-slim

# uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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
