"""ACL enforcement — filter, live recheck, audit.

Three invariants (enforced only when settings.acl_enforce=True):
  INV-1: Default deny — acl_levels=[] is invisible to everyone.
  INV-2: Any-of semantics — access iff acl_levels ∩ user_levels ≠ ∅.
  INV-3: Graph narrowing recomputes from scratch (handled at sync, not here).

document_type is FAIL-OPEN: unclassified (None) docs are always searchable.
Live recheck validates ACL only, never document_type.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from rag.config import settings
from rag.crosscutting.context import Context
from rag.domain.models import RetrievedChunk


def acl_filter(user_levels: list[str] | None) -> dict | None:
    """Build a Qdrant-compatible ACL filter dict.

    When acl_enforce=False, returns None (no filter).
    When acl_enforce=True:
      - user_levels=None or [] → impossible filter (deny all, INV-1)
      - user_levels=[...] → any-of match on acl_levels field (INV-2)
    """
    if not settings.acl_enforce:
        return None
    if not user_levels:
        return {"_acl_deny_all": True}
    return {"acl_levels_any": user_levels}


def type_filter(intended_types: list[str] | None) -> dict | None:
    """Build an optional document_type filter. Fail-open: None = no filter."""
    if not intended_types:
        return None
    return {"document_type_any": intended_types}


def check_acl_access(chunk: RetrievedChunk, user_levels: list[str] | None) -> bool:
    """INV-2: any-of intersection. Returns True if access allowed."""
    if not settings.acl_enforce:
        return True
    if not user_levels:
        return False
    chunk_levels = chunk.metadata.get("acl_levels", [])
    if not chunk_levels:
        return False  # INV-1: empty = deny
    return bool(set(chunk_levels) & set(user_levels))


def live_recheck(chunks: list[RetrievedChunk],
                 user_levels: list[str] | None,
                 ctx: Context | None = None) -> tuple[list[RetrievedChunk], list[str]]:
    """Post-retrieval ACL recheck. Returns (allowed, denied_ids).

    Validates ACL only, never document_type (type is relevance, not security).
    This closes the sync-lag window: even if the vector store payload is stale,
    the recheck catches revoked access.
    """
    if not settings.acl_enforce:
        return chunks, []

    allowed = []
    denied_ids = []
    for c in chunks:
        if check_acl_access(c, user_levels):
            allowed.append(c)
        else:
            denied_ids.append(c.chunk_id)

    if denied_ids:
        print(f"  🔒 ACL recheck: {len(denied_ids)} chunks denied")

    return allowed, denied_ids


def log_retrieval_audit(
    user_id: str,
    query: str,
    returned_ids: list[str],
    denied_ids: list[str],
    user_levels: list[str] | None,
    ctx: Context | None = None,
) -> None:
    """Write audit log entry. Async in production; synchronous locally."""
    if not settings.acl_enforce:
        return

    audit_dir = Path("data/audit")
    audit_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": ctx.request_id if ctx else "",
        "tenant_id": ctx.tenant_id if ctx else "default",
        "user_id": user_id,
        "query_hash": hashlib.sha256(query.encode()).hexdigest(),
        "chunk_ids_returned": returned_ids,
        "chunk_ids_denied": denied_ids,
        "access_levels_used": user_levels or [],
    }

    log_path = audit_dir / "retrieval_audit.jsonl"
    with open(log_path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
