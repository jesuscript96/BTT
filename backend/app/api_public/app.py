"""ASGI app for the Edgecute Backtest API.

Separate from the engine's `app.main:app` (IP isolation). Run with:
    uvicorn app.api_public.app:app --port 8100
"""
from __future__ import annotations

import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api_public import config
from app.api_public.core.errors import install_error_handlers
from app.api_public.modules import load_module

logger = logging.getLogger("edgecute.api")


def create_app() -> FastAPI:
    app = FastAPI(
        title=config.API_TITLE,
        version=config.API_VERSION,
        description=(
            "API comercial para ejecutar backtests de gaps/short-selling contra el motor "
            "y los datos intradía de Edgecute. Síncrona con cap; auth por API-key."
        ),
    )

    # CORS: the trader's locally-built app (browser) may call the API. Permissive by
    # default but env-overridable; server-to-server clients ignore CORS anyway.
    origins = config.__dict__.get("CORS_ORIGINS")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        rid = "req_" + secrets.token_hex(8)
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response

    install_error_handlers(app)

    # Health & root (no auth).
    @app.get(f"{config.API_PREFIX}/health", tags=["meta"])
    def health():
        return {"status": "ok", "service": config.API_TITLE, "version": config.API_VERSION}

    # OpenAPI also under the versioned prefix (contract: GET /v1/openapi.json).
    @app.get(f"{config.API_PREFIX}/openapi.json", include_in_schema=False)
    def versioned_openapi():
        return app.openapi()

    # Mount enabled modules generically.
    mounted = []
    for name in config.ENABLED_MODULES:
        try:
            descriptor = load_module(name)
            app.include_router(descriptor["router"], prefix=config.API_PREFIX)
            mounted.append(descriptor["name"])
        except Exception as exc:  # noqa: BLE001 — a broken module must not kill the app
            logger.error("Failed to mount module '%s': %s", name, exc)
    logger.info("Edgecute API mounted modules: %s", mounted)

    @app.get(f"{config.API_PREFIX}/modules", tags=["meta"])
    def list_mounted_modules():
        return {"modules": mounted}

    return app


app = create_app()
