"""Per-user (falling back to per-IP for unauthenticated requests) rate limiting,
backed by the appliance's existing Redis instance so limits stay consistent even if
this ever scales beyond one app process.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from rag.config import settings
from rag.crosscutting.security.tokens import decode_token


def user_or_ip_key(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ")
        try:
            payload = decode_token(token)
            user_id = payload.get("sub")
            if user_id:
                return f"user:{user_id}"
        except Exception:
            pass
    return f"ip:{get_remote_address(request)}"


# swallow_errors=True: if the Redis backend is unreachable, slowapi logs a warning
# and lets the request through rather than raising -- a rate limiter briefly failing
# open during a Redis outage is a minor, recoverable security posture dip; an
# appliance-wide 500 on every LLM/upload request because an auxiliary service is
# down is a worse outcome for a real deployment, and matches this project's
# established "degrade gracefully" convention (redis_url, glitchtip_dsn) elsewhere.
limiter = Limiter(
    key_func=user_or_ip_key, storage_uri=settings.redis_url or "memory://", swallow_errors=True,
)
