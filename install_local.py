"""No-Docker installer for running Aegis directly on a laptop.

Prerequisites (install once, e.g. via Homebrew on macOS):
    brew install postgresql@16 redis
    brew services start postgresql@16
    brew services start redis
    createdb appliance

Neo4j is skipped by default (BUILD_GRAPH=false) so the knowledge-graph feature
is disabled and no Neo4j install is required. Qdrant runs as a real local server
process (this script downloads a standalone binary into ./.local-bin/qdrant on
first run) rather than in embedded/local-file mode -- embedded mode opens an
exclusive file lock on ./data/qdrant, and the API process and Celery worker
process both need concurrent access to it, which crashes every query/upload
with "Storage folder is already accessed by another instance" the moment both
processes are up at once.

This script writes/updates .env, runs Alembic migrations and the non-SQL store
migration step, then seeds three fixed local accounts (admin, User_1, User_2).
Re-running it is idempotent: existing .env values and existing users are left
untouched.

This script also installs dependencies (`uv sync`, `npm install`) and then
starts the API, Celery worker, and Next.js UI dev server itself, streaming
their logs to ./logs/*.log. It blocks until you press Ctrl+C, at which point
all three processes are stopped.
"""

import os
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

from rag.bootstrap.env_writer import read_env_value, write_missing_env_vars
from rag.bootstrap.secrets_gen import generate_jwt_secret, generate_keystore_master_key
from rag.config import settings
from rag.infra.stores.sql.base import SessionLocal, reset_engine

import run_store_migrate
from seed_local_users import LOCAL_USERS, seed_local_users

QDRANT_VERSION = "v1.18.2"
QDRANT_BIN = Path(".local-bin/qdrant")


def _require(cmd: str) -> None:
    if shutil.which(cmd) is None:
        print(f"Error: `{cmd}` not found on PATH. Install it before running this script.")
        sys.exit(1)


def _qdrant_release_asset() -> str:
    machine = platform.machine()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    return f"qdrant-{arch}-apple-darwin.tar.gz"


def _ensure_qdrant_binary() -> None:
    if QDRANT_BIN.exists():
        return
    QDRANT_BIN.parent.mkdir(exist_ok=True)
    asset = _qdrant_release_asset()
    url = f"https://github.com/qdrant/qdrant/releases/download/{QDRANT_VERSION}/{asset}"
    print(f"== Downloading Qdrant server binary ({asset}) ==")
    archive_path = QDRANT_BIN.parent / asset
    urllib.request.urlretrieve(url, archive_path)
    with tarfile.open(archive_path) as tar:
        tar.extract("qdrant", path=QDRANT_BIN.parent)
    archive_path.unlink()
    QDRANT_BIN.chmod(0o755)
    # Downloaded binaries carry the macOS quarantine flag, which blocks execution
    # without an interactive Gatekeeper prompt; this script runs non-interactively.
    subprocess.run(["xattr", "-d", "com.apple.quarantine", str(QDRANT_BIN)], check=False)


def _ensure_local_postgres_db() -> None:
    result = subprocess.run(["psql", "-lqt"], capture_output=True, text=True)
    if result.returncode != 0:
        print("Warning: could not reach local `psql` -- make sure Postgres is installed and running "
              "(e.g. `brew install postgresql@16 && brew services start postgresql@16`).")
        return
    if any(line.split("|")[0].strip() == "appliance" for line in result.stdout.splitlines()):
        return
    print("Creating local 'appliance' database...")
    subprocess.run(["createdb", "appliance"], check=False)


def _install_dependencies() -> None:
    print("== Installing backend dependencies (uv sync) ==")
    subprocess.run(["uv", "sync", "--frozen"], check=True)

    print("== Installing frontend dependencies (npm install) ==")
    subprocess.run(["npm", "install"], cwd="ui", check=True)


def _start_services() -> None:
    Path("logs").mkdir(exist_ok=True)
    procs: list[tuple[str, subprocess.Popen]] = []

    def spawn(name: str, cmd: list[str], cwd: str | None = None) -> None:
        log_file = open(Path("logs") / f"{name}.log", "w")
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=log_file, stderr=subprocess.STDOUT)
        procs.append((name, proc))
        print(f"Started {name} (pid {proc.pid}), logging to logs/{name}.log")

    env = {**os.environ, "QDRANT__STORAGE__STORAGE_PATH": settings.qdrant_path}
    qdrant_proc = subprocess.Popen(
        [str(QDRANT_BIN.resolve())], env=env,
        stdout=open(Path("logs") / "qdrant.log", "w"), stderr=subprocess.STDOUT,
    )
    procs.append(("qdrant", qdrant_proc))
    print(f"Started qdrant (pid {qdrant_proc.pid}), logging to logs/qdrant.log")
    for _ in range(30):
        try:
            urllib.request.urlopen("http://localhost:6333/healthz", timeout=1)
            break
        except Exception:
            time.sleep(1)
    else:
        print("Warning: qdrant did not report healthy within 30s -- check logs/qdrant.log")

    spawn("api", ["uv", "run", "uvicorn", "rag.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"])
    # --pool=solo: Celery's default prefork pool os.fork()s a worker process after
    # native libraries (ONNXRuntime, Apple's Accelerate/vecLib via torch/docling)
    # have already initialized in the parent -- reliably segfaults (signal 11) on
    # macOS during PDF ingestion. solo runs single-process/single-threaded, no
    # fork, no crash; fine for a single-user local dev setup.
    spawn("worker", ["uv", "run", "celery", "-A", "rag.worker.celery_app", "worker", "--loglevel=info", "--pool=solo"])
    spawn("ui", ["npm", "run", "dev"], cwd="ui")

    print("\nAll services started:")
    print("  API:      http://localhost:8000")
    print("  UI:       http://localhost:3000")
    print("  Logs:     ./logs/{api,worker,ui}.log")
    print("\nPress Ctrl+C to stop everything.")

    def _shutdown(signum, frame) -> None:
        print("\nStopping services...")
        for name, proc in procs:
            proc.terminate()
        for name, proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        for name, proc in procs:
            if proc.poll() is not None:
                print(f"\n{name} exited unexpectedly (code {proc.returncode}) -- see logs/{name}.log")
                _shutdown(None, None)
        time.sleep(2)


def run_install() -> None:
    _require("uv")
    _require("npm")
    _require("psql")

    print("== Writing local .env ==")
    env_path = Path(".env")
    env_vars = {
        "JWT_SECRET_KEY": generate_jwt_secret(),
        "KEYSTORE_MASTER_KEY": generate_keystore_master_key(),
        "DATABASE_URL": "postgresql+psycopg://postgres:password@localhost:5432/appliance",
        "REDIS_URL": "redis://localhost:6379",
        # Real local Qdrant server (started by this script) -- NOT embedded/local-file
        # mode, which can't be opened by both the API and worker processes at once.
        "QDRANT_URL": "http://localhost:6333",
        # Knowledge graph disabled by default so Neo4j isn't required for a
        # minimal local run. Install Neo4j and flip this to true if you want it.
        "BUILD_GRAPH": "false",
        "LLM_BACKEND": "ollama",
    }
    written = write_missing_env_vars(env_path, env_vars)
    if written:
        print(f"Generated: {', '.join(written)}")
    else:
        print("All settings already present in .env, nothing generated.")

    # UI dev server (`npm run dev`) reads its own env file, not the root .env.
    # Point it at the plain-HTTP backend started by this script (no nginx/TLS
    # in this flow), matching cookieOptions.secure's COOKIE_SECURE=false opt-out
    # in ui/lib/auth-cookies.ts -- otherwise Secure cookies get silently dropped
    # over HTTP and every request after login looks session-less.
    ui_env_path = Path("ui/.env.local")
    ui_env_vars = {
        "API_BASE_URL": "http://localhost:8000",
        "COOKIE_SECURE": "false",
    }
    ui_written = write_missing_env_vars(ui_env_path, ui_env_vars)
    if ui_written:
        print(f"Generated in ui/.env.local: {', '.join(ui_written)}")

    # Sync the in-process settings singleton, same reasoning as install.py:
    # `settings` was built at import time, before .env necessarily had these keys.
    settings.database_url = read_env_value(env_path, "DATABASE_URL") or settings.database_url
    settings.redis_url = read_env_value(env_path, "REDIS_URL") or settings.redis_url
    settings.qdrant_url = read_env_value(env_path, "QDRANT_URL") or settings.qdrant_url
    reset_engine()

    print("== Checking local Postgres ==")
    _ensure_local_postgres_db()

    print("== Checking local Qdrant binary ==")
    _ensure_qdrant_binary()

    _install_dependencies()

    print("== Running migrations ==")
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True)
    run_store_migrate.main()

    print("== Seeding local users ==")
    db = SessionLocal()
    try:
        created = seed_local_users(db)
    finally:
        db.close()

    if created:
        print("Created accounts:")
        for username, password, role in LOCAL_USERS:
            print(f"  username: {username:<10} password: {password:<20} role: {role}")
    else:
        print("Local accounts already exist, skipping.")

    print("\nInstall complete. Starting services...")
    _start_services()


if __name__ == "__main__":
    run_install()
