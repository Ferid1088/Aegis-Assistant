FROM python:3.14-slim

# uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Air-gap: HF models cached into a mounted volume (see docker-compose.yml's hf_models)
ENV HF_HOME=/models/hf
ENV DEVICE=cpu

CMD ["uv", "run", "python", "healthcheck.py"]
