"""@traced decorator — emits span timing for capability methods.

Span taxonomy (fixed names, both pipelines use the same):
  search.dense.embed | search.dense.query | search.sparse.query | search.graph.traverse
  | search.fusion.rrf | rerank.cross_encoder | extract.entities | extract.relations
  | extract.rules | generate.llm
"""

import functools
import time


def traced(span_name: str):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                return result
            finally:
                elapsed = time.perf_counter() - start
                ctx = kwargs.get("ctx") or (args[0] if args and hasattr(args[0], "request_id") else None)
                rid = ctx.request_id if ctx and hasattr(ctx, "request_id") else "-"
                print(f"  ⏱ {span_name}: {elapsed:.3f}s [rid={rid[:8]}]")
        return wrapper
    return decorator
