import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from rag.api.errors import http_exception_handler, unhandled_exception_handler, validation_exception_handler
from rag.api.routers import admin_audit, admin_rbac, admin_users, auth as auth_router, conversations, documents
from rag.observability.logging_config import configure_logging


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(title="RAG Appliance API", version="1.0", openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs")

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request.state.request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request.state.request_id
            structlog.get_logger("rag.api").info(
                "request completed", method=request.method, path=request.url.path, status_code=response.status_code,
            )
            return response
        finally:
            structlog.contextvars.clear_contextvars()

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(admin_rbac.router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(admin_users.router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(admin_audit.router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["conversations"])
    app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])

    return app
