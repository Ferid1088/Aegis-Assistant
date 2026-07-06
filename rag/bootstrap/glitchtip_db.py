"""Ensures the 'glitchtip' Postgres database exists in the shared postgres
container, idempotently -- a repeated install.py run must not error on
'database already exists'.
"""

import subprocess


def ensure_glitchtip_database() -> None:
    check = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "-tAc",
         "SELECT 1 FROM pg_database WHERE datname='glitchtip'"],
        capture_output=True, text=True, check=True,
    )
    if check.stdout.strip() != "1":
        subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "-c",
             "CREATE DATABASE glitchtip"],
            check=True,
        )
