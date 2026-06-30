"""Immutable request context — correlation spine for trace/log/metric/ACL."""

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class Context:
    request_id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: str = "default"
    user_levels: list[str] | None = None
    entitlements: dict = field(default_factory=dict)
