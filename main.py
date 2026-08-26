"""FakeDetect API — application assembly.

Thin entry point: wires config, middleware, exception handling, startup hooks
and includes versioned routers (/api/v1). Legacy unversioned paths are kept
during a grace period for backwards compatibility.
"""

import logging

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from core.config import settings
from database import cleanup_old_batch_tasks, init_db
from routers import analysis_router, batch_router, data_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

API_V1_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(
        title="FakeDetect API",
        version="3.0.0",
        description="AI-детектор подделок с интеграцией Gemini / Grok Vision",
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

    # --- Unversioned utility endpoints ---------------------------------------
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def get_index():
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    @app.get("/health")
    async def health_check():
        from core.config import get_api_key_for_provider
        return JSONResponse(content={
            "status": "ok",
            "provider": settings.provider,
            "api_key_configured": bool(get_api_key_for_provider(settings.provider)),
        })

    # --- Versioned API --------------------------------------------------------
    app.include_router(analysis_router, prefix=API_V1_PREFIX)
    app.include_router(batch_router, prefix=API_V1_PREFIX)
    app.include_router(data_router, prefix=API_V1_PREFIX)

    # --- Legacy paths (deprecated, kept for grace period) ----------------------
    app.include_router(analysis_router)
    app.include_router(batch_router)
    app.include_router(data_router)

    return app


app = create_app()
