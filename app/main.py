"""FakeDetect API — application assembly.

Thin entry point: wires config, middleware, exception handling, startup hooks
and includes versioned routers (/api/v1). Legacy unversioned paths are kept
during a grace period for backwards compatibility.

Block A additions: request-id middleware with latency metrics (A.5), structured
JSON logging, deep /health + /metrics + /queue endpoints and the background
retry-queue worker (A.6).
"""

import asyncio
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app import observability
from app.core.config import settings
from app.core.metrics import HTTP_ERRORS_TOTAL, REQUEST_LATENCY
from app.database import cleanup_old_batch_tasks, init_db
from app.routers import (
    analysis_router,
    batch_router,
    data_router,
    system_router,
    watches_router,
)
from app.routers.billing import router as billing_router
from app.routers.cases import router as cases_router
from app.routers.partner import router as partner_router
from app.routers.analytics import router as analytics_router

load_dotenv()

observability.setup_logging(
    level=logging.getLevelName(logging.INFO),
    json_mode=settings.log_format.strip().lower() == "json",
)
logger = logging.getLogger(__name__)

API_V1_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(
        title="FakeDetect API",
        version="3.1.0",
        description=(
            "AI-детектор подделок с интеграцией Gemini / Grok Vision. "
            "Block A production reliability: circuit breakers, idempotency, "
            "deadline budget, retry queue, Prometheus observability."
        ),
    )

    # CORS: explicit origins only, credentials are never used.
    allowed_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    # --- Observability middleware (A.5) ---------------------------------------
    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        # F/demo: per-IP budget for API calls in public demo deployments.
        if settings.demo_mode and request.url.path.startswith(API_V1_PREFIX):
            from app.services import tenancy

            path = request.url.path
            is_webhook = "/billing/webhook/" in path
            is_partner = "/partner/" in path
            if not is_webhook and not is_partner:
                try:
                    if "/analyze" in path:
                        await tenancy.ip_rate_limit(
                            request, "analyze",
                            settings.ip_rate_limit_analyze_per_min,
                        )
                    else:
                        await tenancy.ip_rate_limit(
                            request, "general", settings.ip_rate_limit_per_min
                        )
                except HTTPException as e:
                    return JSONResponse(status_code=e.status_code,
                                        content={"detail": e.detail},
                                        headers=e.headers or {})

        rid_token = observability.set_request_id(request.headers.get("x-request-id", ""))
        start = asyncio.get_event_loop().time()
        try:
            response = await call_next(request)
        except Exception:
            HTTP_ERRORS_TOTAL.labels(
                endpoint=request.url.path, method=request.method
            ).inc()
            raise
        finally:
            observability.reset_request_id(rid_token)
        elapsed = asyncio.get_event_loop().time() - start
        REQUEST_LATENCY.labels(endpoint=request.url.path, method=request.method).observe(elapsed)
        response.headers["X-Request-ID"] = request.headers.get("x-request-id", "") or \
            response.headers.get("x-request-id", "")
        return response

    # Unified error handling: never leak internals to the client.
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Внутренняя ошибка сервера, попробуйте позже"},
        )

    @app.on_event("startup")
    async def startup():
        await init_db()
        await cleanup_old_batch_tasks(days=7)
        # F: default tenant + legacy master key row in api_keys.
        from app.services import tenancy

        await tenancy.bootstrap()
        # A.6: background replay of analyses queued during provider outages.
        from app.services.retry_worker import run_forever

        app.state.retry_worker_task = asyncio.create_task(run_forever())
        # C.1: discovery scheduler (cron-driven brand watches).
        from app.services import scheduler_service

        scheduler_service.start()
        app.state.scheduler = scheduler_service

    @app.on_event("shutdown")
    async def shutdown():
        task = getattr(app.state, "retry_worker_task", None)
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler:
            scheduler.stop()

    # --- Unversioned utility endpoints ---------------------------------------
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def get_index():
        with open("legacy/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    # --- Versioned API --------------------------------------------------------
    app.include_router(analysis_router, prefix=API_V1_PREFIX)
    app.include_router(batch_router, prefix=API_V1_PREFIX)
    app.include_router(data_router, prefix=API_V1_PREFIX)
    app.include_router(watches_router, prefix=API_V1_PREFIX)
    app.include_router(cases_router, prefix=API_V1_PREFIX)
    app.include_router(analytics_router, prefix=API_V1_PREFIX)
    app.include_router(partner_router, prefix=API_V1_PREFIX)
    app.include_router(billing_router, prefix=API_V1_PREFIX)
    app.include_router(system_router)              # /health, /metrics, /queue/{id}
    app.include_router(system_router, prefix=API_V1_PREFIX)  # v1 aliases

    # --- Legacy paths (deprecated, kept for grace period) ----------------------
    app.include_router(analysis_router)
    app.include_router(batch_router)
    app.include_router(data_router)
    app.include_router(watches_router)
    app.include_router(cases_router)

    return app


app = create_app()

