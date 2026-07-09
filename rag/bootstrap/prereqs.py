import shutil
import subprocess

import psutil

_MIN_RAM_BYTES = 8 * 1024**3  # 8 GB


def check_docker() -> None:
    try:
        subprocess.run(["docker", "--version"], check=True, capture_output=True)
        subprocess.run(["docker", "compose", "version"], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "Docker and Docker Compose are required but were not found or not working. "
            "Install Docker and ensure `docker` and `docker compose` run successfully."
        ) from exc
    print("✅ Docker OK")


def check_ram() -> None:
    total_bytes = psutil.virtual_memory().total
    total_gb = total_bytes / 1024**3
    if total_bytes < _MIN_RAM_BYTES:
        print(f"⚠️  Warning: {total_gb:.1f} GB RAM detected, below the recommended 8 GB minimum.")
    else:
        print(f"✅ RAM OK ({total_gb:.1f} GB)")


def check_gpu() -> bool:
    has_gpu = shutil.which("nvidia-smi") is not None
    if has_gpu:
        print("✅ GPU detected")
    else:
        print("ℹ️  No GPU detected — CPU-only mode")
    return has_gpu
