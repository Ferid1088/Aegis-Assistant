"""Requires a running Docker daemon. Measures real crash-recovery behavior
for app and worker in the 8.10d setup.
"""

import subprocess
import socket
import time
import uuid

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rag.config import settings
from rag.domain import ingestion_job_service
from rag.infra.stores.sql import models  # noqa: F401
from rag.infra.stores.sql.base import Base
from rag.infra.stores.sql.models import User
from rag.worker.celery_app import celery_app
from rag.worker.tasks import run_ingestion

PDF_PATH = "docs/TV_L.pdf"
_FIND_PID_BY_COMM = (
    "import os, sys\n"
    "target = sys.argv[1]\n"
    "for pid in sorted(int(p) for p in os.listdir('/proc') if p.isdigit()):\n"
    "    try:\n"
    "        with open(f'/proc/{pid}/comm') as f:\n"
    "            if f.read().strip() == target:\n"
    "                print(pid)\n"
    "                break\n"
    "    except OSError:\n"
    "        pass\n"
)
_KILL_PID = "import os, signal, sys; os.kill(int(sys.argv[1]), signal.SIGKILL)"


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _wait_for_healthz(timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get("https://localhost/healthz", timeout=3, verify=False)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("app never became reachable via nginx before the test began")


def _crash_real_server_process(container_id: str, comm_name: str) -> None:
    result = subprocess.run(
        ["docker", "exec", container_id, "python3", "-c", _FIND_PID_BY_COMM, comm_name],
        capture_output=True, text=True, check=True,
    )
    target_pid = result.stdout.strip()
    assert target_pid, f"could not find a {comm_name!r} process inside container {container_id}"
    subprocess.run(
        ["docker", "exec", container_id, "python3", "-c", _KILL_PID, target_pid],
        check=True,
    )


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_app_recovers_after_a_hard_crash():
    required_ports = [5432, 6333, 6379, 80, 443]
    busy = [port for port in required_ports if not _port_available(port)]
    if busy:
        pytest.skip(f"required compose ports already in use locally: {busy}")
    subprocess.run(["docker", "compose", "up", "-d", "nginx", "redis", "postgres", "pgbouncer", "qdrant"], check=True)
    try:
        _wait_for_healthz()
        container_id = subprocess.run(["docker", "compose", "ps", "-q", "app"], capture_output=True, text=True, check=True).stdout.strip()
        assert container_id, "no running app container found"
        kill_time = time.monotonic()
        _crash_real_server_process(container_id, "uvicorn")
        deadline = kill_time + 90.0
        recovered_at = None
        while time.monotonic() < deadline:
            try:
                r = httpx.get("https://localhost/healthz", timeout=3, verify=False)
                if r.status_code == 200:
                    recovered_at = time.monotonic()
                    break
            except Exception:
                pass
            time.sleep(1)
        assert recovered_at is not None, "app did not recover within 90s of being killed"
        print(f"\nMeasured app crash-recovery RTO: {recovered_at - kill_time:.1f}s")
    finally:
        subprocess.run(["docker", "compose", "down"], check=True)


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_worker_recovers_and_completes_a_queued_job_after_a_hard_crash():
    required_ports = [5432, 6333, 6379]
    busy = [port for port in required_ports if not _port_available(port)]
    if busy:
        pytest.skip(f"required compose ports already in use locally: {busy}")
    subprocess.run(["docker", "compose", "up", "-d", "worker", "redis", "postgres", "pgbouncer", "qdrant"], check=True)
    try:
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            ping = subprocess.run(
                ["docker", "compose", "exec", "-T", "worker", "uv", "run", "celery", "-A", "rag.worker.celery_app", "inspect", "ping"],
                capture_output=True, text=True,
            )
            if ping.returncode == 0:
                break
            time.sleep(2)
        else:
            raise RuntimeError("worker never became reachable via celery inspect ping")

        celery_app.conf.broker_url = "redis://localhost:6379/0"
        celery_app.conf.result_backend = "redis://localhost:6379/0"

        engine = create_engine(settings.database_url)
        Base.metadata.create_all(engine)
        TestSessionLocal = sessionmaker(bind=engine)
        db = TestSessionLocal()
        try:
            user = User(username=f"chaos-test-{uuid.uuid4().hex[:8]}")
            db.add(user)
            db.commit()
            job = ingestion_job_service.create_job(db, uploaded_by=user.id, filename="TV_L.pdf", staged_path=PDF_PATH, doc_version=None)
            job_id = job.id
        finally:
            db.close()

        run_ingestion.delay(str(job_id))

        pickup_deadline = time.monotonic() + 15.0
        while time.monotonic() < pickup_deadline:
            db = TestSessionLocal()
            try:
                current = ingestion_job_service.get_job(db, job_id)
                if current.status in ("running", "done", "failed"):
                    break
            finally:
                db.close()
            time.sleep(1)

        container_id = subprocess.run(["docker", "compose", "ps", "-q", "worker"], capture_output=True, text=True, check=True).stdout.strip()
        assert container_id, "no running worker container found"
        kill_time = time.monotonic()
        _crash_real_server_process(container_id, "celery")

        deadline = kill_time + 90.0
        recovered_at = None
        while time.monotonic() < deadline:
            ping = subprocess.run(
                ["docker", "compose", "exec", "-T", "worker", "uv", "run", "celery", "-A", "rag.worker.celery_app", "inspect", "ping"],
                capture_output=True, text=True,
            )
            if ping.returncode == 0:
                recovered_at = time.monotonic()
                break
            time.sleep(2)

        assert recovered_at is not None, "worker did not recover within 90s of being killed"
        print(f"\nMeasured worker crash-recovery RTO: {recovered_at - kill_time:.1f}s")
    finally:
        subprocess.run(["docker", "compose", "down"], check=True)