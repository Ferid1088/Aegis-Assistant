import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from rag.api.errors import http_exception_handler, unhandled_exception_handler, validation_exception_handler
from rag.api.routers import auth as auth_router


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Appliance API", version="1.0", openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs")

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["auth"])

    return app
