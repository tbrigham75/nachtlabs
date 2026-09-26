import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from nachtlabs.errors import DomainError
from nachtlabs.settings import get_settings
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from nachtlabs_api import (
    admin_routes,
    agent_routes,
    auth_routes,
    integration_routes,
    monitoring_routes,
    observation_routes,
    project_routes,
    webhook_routes,
    workflow_routes,
)

logger = logging.getLogger("nachtlabs.api")


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    app = FastAPI(
        title="NachtLabs", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=[s.strip() for s in settings.allowed_hosts.split(",")]
    )
    for router in (
        auth_routes.router,
        admin_routes.router,
        project_routes.router,
        observation_routes.router,
        integration_routes.router,
        agent_routes.router,
        workflow_routes.router,
        monitoring_routes.router,
        webhook_routes.router,
    ):
        app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def boundary(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = str(uuid4())
        started = time.monotonic()
        length = request.headers.get("content-length")
        try:
            oversized = length is not None and int(length) > 131072
        except ValueError:
            oversized = True
        if oversized:
            response = JSONResponse(
                {
                    "error": {
                        "code": "body_too_large",
                        "message": "Request exceeds 128 KiB",
                        "request_id": request.state.request_id,
                    }
                },
                status_code=413,
            )
        else:
            if request.method in {"POST", "PUT", "PATCH"}:
                chunks: list[bytes] = []
                received = 0
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > 131072:
                        return JSONResponse(
                            {
                                "error": {
                                    "code": "body_too_large",
                                    "message": "Request exceeds 128 KiB",
                                    "request_id": request.state.request_id,
                                }
                            },
                            status_code=413,
                            headers={"Cache-Control": "no-store"},
                        )
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # No raw URL, query, headers, request body, or exception text in telemetry.
        route = request.scope.get("route")
        logger.info(
            json.dumps(
                {
                    "service": "api",
                    "request_id": request.state.request_id,
                    "route": getattr(route, "path", "unmatched"),
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                }
            )
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": request.state.request_id,
                }
            },
            status_code=exc.status,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's raw errors include input values; never serialize them.
        fields = [".".join(str(part) for part in e["loc"]) for e in exc.errors()]
        return JSONResponse(
            {
                "error": {
                    "code": "validation",
                    "message": "Check the indicated fields",
                    "fields": fields,
                    "request_id": request.state.request_id,
                }
            },
            status_code=422,
        )

    @app.exception_handler(IntegrityError)
    async def conflict(request: Request, exc: IntegrityError) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "conflict",
                    "message": "A conflicting record exists; refresh and retry",
                    "request_id": request.state.request_id,
                }
            },
            status_code=409,
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "database_unavailable",
                    "message": "Database operation unavailable",
                    "request_id": request.state.request_id,
                }
            },
            status_code=503,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            json.dumps(
                {
                    "event": "unhandled_error",
                    "request_id": request.state.request_id,
                    "exception_type": type(exc).__name__,
                }
            )
        )
        return JSONResponse(
            {
                "error": {
                    "code": "internal_error",
                    "message": "The operation could not be completed",
                    "request_id": request.state.request_id,
                }
            },
            status_code=500,
        )

    from nachtlabs_api.dependencies import Actor

    @app.get("/api/v1/openapi.json", include_in_schema=False)
    def schema(actor: Actor) -> dict:  # type: ignore[type-arg]
        actor.human_admin()
        return app.openapi()

    @app.get("/api/v1/docs", include_in_schema=False)
    def docs(actor: Actor):  # type: ignore[no-untyped-def]
        actor.human_admin()
        from fastapi.openapi.docs import get_swagger_ui_html

        return get_swagger_ui_html(
            openapi_url="/api/v1/openapi.json",
            title="NachtLabs API",
            swagger_js_url="/docs-assets/swagger-ui-bundle.js",
            swagger_css_url="/docs-assets/swagger-ui.css",
            swagger_favicon_url="/docs-assets/favicon-32x32.png",
        )

    original_schema = app.openapi

    def documented_schema() -> dict:  # type: ignore[type-arg]
        schema_data = original_schema()
        schema_data.setdefault("components", {})["securitySchemes"] = {
            "SessionCookie": {
                "type": "apiKey",
                "in": "cookie",
                "name": "nachtlabs_session",
                "description": "Mutations also require Origin and X-CSRF-Token.",
            },
            "ScopedAPIKey": {
                "type": "http",
                "scheme": "bearer",
                "description": "Project-restricted service-account key.",
            },
        }
        schema_data["security"] = [{"SessionCookie": []}, {"ScopedAPIKey": []}]
        public = {
            "/auth/setup-status",
            "/auth/setup",
            "/auth/login",
            "/auth/mfa/verify",
            "/auth/forgot-password",
            "/auth/reset-password",
            "/auth/accept-invitation",
            "/health/live",
            "/health/ready",
        }
        for path, operations in schema_data.get("paths", {}).items():
            if path.removeprefix("/api/v1") in public or path.startswith("/api/v1/hooks/"):
                for operation in operations.values():
                    if isinstance(operation, dict):
                        operation["security"] = []
        return schema_data

    app.openapi = documented_schema  # type: ignore[method-assign]
    return app
