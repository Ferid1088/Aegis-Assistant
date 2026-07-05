from pathlib import Path


def write_missing_env_vars(env_path: Path, values: dict[str, str]) -> list[str]:
    env_path = Path(env_path)
    existing_keys = set()
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                existing_keys.add(stripped.split("=", 1)[0])

    to_write = {k: v for k, v in values.items() if k not in existing_keys}
    if to_write:
        with open(env_path, "a") as f:
            for key, value in to_write.items():
                f.write(f"{key}={value}\n")

    return list(to_write.keys())
