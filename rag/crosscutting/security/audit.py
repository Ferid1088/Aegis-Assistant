"""Hash-chained immutable audit log.

Each entry hashes the previous → any edit/delete of a past row breaks the chain.
Append-only: no update/delete operations exposed.
Detects tampering by re-walking the chain.

Events captured: authorization denials, break-glass access, delegation,
state transitions, erasure requests/refusals, CRUD + permission changes.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class AuditEntry:
    actor_user: str
    action: str
    resource: str
    tenant_id: str = "default"
    prev_value: dict | None = None
    new_value: dict | None = None
    request_id: str = ""
    ip: str = ""
    metadata: dict = field(default_factory=dict)
    ts: str = ""
    prev_hash: str = ""
    entry_hash: str = ""


def _canonical(entry: AuditEntry) -> str:
    d = asdict(entry)
    d.pop("entry_hash", None)
    return json.dumps(d, sort_keys=True, ensure_ascii=False, default=str)


def _compute_hash(prev_hash: str, canonical: str) -> str:
    return hashlib.sha256(f"{prev_hash}||{canonical}".encode()).hexdigest()


class AuditLog:
    def __init__(self, log_dir: str = "data/audit") -> None:
        self._path = Path(log_dir) / "immutable_audit.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash = self._read_last_hash()

    def _read_last_hash(self) -> str:
        if not self._path.exists():
            return "GENESIS"
        last_line = ""
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if line:
                    last_line = line
        if not last_line:
            return "GENESIS"
        try:
            return json.loads(last_line).get("entry_hash", "GENESIS")
        except json.JSONDecodeError:
            return "GENESIS"

    def append(self, entry: AuditEntry) -> AuditEntry:
        entry.ts = datetime.now(timezone.utc).isoformat()
        entry.prev_hash = self._last_hash
        canonical = _canonical(entry)
        entry.entry_hash = _compute_hash(self._last_hash, canonical)
        self._last_hash = entry.entry_hash

        with open(self._path, "a") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False, default=str) + "\n")

        return entry

    def verify_chain(self) -> tuple[bool, int, str]:
        """Re-walk the chain. Returns (valid, num_entries, error_msg)."""
        if not self._path.exists():
            return True, 0, ""

        prev_hash = "GENESIS"
        count = 0

        with open(self._path) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    return False, count, f"line {line_num}: invalid JSON"

                stored_hash = data.get("entry_hash", "")
                stored_prev = data.get("prev_hash", "")

                if stored_prev != prev_hash:
                    return False, count, f"line {line_num}: prev_hash mismatch (expected {prev_hash[:16]}..., got {stored_prev[:16]}...)"

                entry = AuditEntry(**{k: data[k] for k in AuditEntry.__dataclass_fields__ if k in data})
                entry.entry_hash = ""
                canonical = _canonical(entry)
                expected_hash = _compute_hash(prev_hash, canonical)

                if stored_hash != expected_hash:
                    return False, count, f"line {line_num}: entry_hash mismatch (tampering detected)"

                prev_hash = stored_hash
                count += 1

        return True, count, ""

    def count(self) -> int:
        if not self._path.exists():
            return 0
        with open(self._path) as f:
            return sum(1 for line in f if line.strip())
