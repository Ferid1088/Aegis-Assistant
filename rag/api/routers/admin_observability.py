from fastapi import APIRouter, Depends

from rag.api.deps import AuthenticatedUser, require_any_admin
from rag.api.schemas.admin import (
    ComponentStatusResponse, EvalRunResponse, LatencyPointResponse, SystemStatusResponse,
)
from rag.config import settings
from rag.crosscutting.observability.trace_store import get_trace_store
from rag.healthcheck import check_postgres, check_redis

router = APIRouter()


@router.get("/eval-runs", response_model=list[EvalRunResponse])
def list_eval_runs(
    current: AuthenticatedUser = Depends(require_any_admin),
) -> list[EvalRunResponse]:
    return [EvalRunResponse(**run) for run in get_trace_store().list_eval_runs()]


@router.get("/latency", response_model=list[LatencyPointResponse])
def latency_summary(
    current: AuthenticatedUser = Depends(require_any_admin),
) -> list[LatencyPointResponse]:
    return [LatencyPointResponse(**point) for point in get_trace_store().latency_summary()]


def _check_qdrant() -> None:
    from rag.infra.stores.vector_store import get_shared_vector_store
    get_shared_vector_store().client.get_collections()


@router.get("/system", response_model=SystemStatusResponse)
def system_status(
    current: AuthenticatedUser = Depends(require_any_admin),
) -> SystemStatusResponse:
    checks = [
        ("Postgres", check_postgres),
        ("Redis", check_redis),
        ("Qdrant", _check_qdrant),
    ]
    components = []
    for name, check in checks:
        try:
            check()
            components.append(ComponentStatusResponse(name=name, status="online"))
        except Exception as exc:
            components.append(ComponentStatusResponse(name=name, status="offline", detail=str(exc)[:200]))

    components.append(
        ComponentStatusResponse(name="Knowledge graph", status="online" if settings.build_graph else "offline",
                                 detail=None if settings.build_graph else "BUILD_GRAPH is disabled")
    )
    components.append(ComponentStatusResponse(name="LLM backend", status="online", detail=settings.llm_backend))

    return SystemStatusResponse(components=components)
