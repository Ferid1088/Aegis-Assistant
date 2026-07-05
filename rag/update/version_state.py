import json
from pathlib import Path

VERSION_FILE = Path("data/appliance_version.json")


def read_version_state(version_path: Path = VERSION_FILE) -> dict:
    version_path = Path(version_path)
    if not version_path.exists():
        return {"version": 0}
    return json.loads(version_path.read_text())


def write_version_state(state: dict, version_path: Path = VERSION_FILE) -> None:
    version_path = Path(version_path)
    version_path.parent.mkdir(parents=True, exist_ok=True)
    version_path.write_text(json.dumps(state, indent=2))
