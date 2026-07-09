"""@traced decorator — emits span timing + writes to TraceStore.

Span taxonomy (fixed names, both pipelines use the same):
  search.dense.embed | search.dense.query | search.sparse.query | search.graph.traverse
  | search.fusion.rrf | rerank.cross_encoder | extract.entities | extract.relations
  | extract.rules | generate.llm
"""

import functools
import threading
import time
from typing import Any

from rag.crosscutting.observability.trace_store import get_trace_store

_span_local = threading.local()


def set_span_attribute(key: str, value: Any) -> None:
    """Call from inside a @traced function to attach extra attrs to its span."""
    if not hasattr(_span_local, "attrs"):
        _span_local.attrs = {}
    _span_local.attrs[key] = value


def _get_store():
    return get_trace_store()


def traced(span_name: str):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            _span_local.attrs = {}
            start = time.perf_counter()
            start_ts = time.time()
            try:
                result = fn(*args, **kwargs)
                return result
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                ctx = kwargs.get("ctx") or (
                    args[0] if args and hasattr(args[0], "request_id") else None
                )
                rid = ctx.request_id if ctx and hasattr(ctx, "request_id") else "-"
                print(f"  ⏱ {span_name}: {duration_ms / 1000:.3f}s [rid={rid[:8]}]")

                extra = dict(getattr(_span_local, "attrs", {}))
                _span_local.attrs = {}

                try:
                    _get_store().write_span(
                        request_id=rid,
                        span_name=span_name,
                        parent_span=None,
                        started_at=start_ts,
                        duration_ms=duration_ms,
                        attributes=extra,
                    )
                except Exception:
                    pass
        return wrapper
    return decorator
