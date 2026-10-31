"""FastAPI application (ARC-01). Serves the API under /api and the React build from backend/pim/static.

GOV-04: every request logs a structured line with request id (X-Request-Id from the Databricks proxy [D7]) and
user; unhandled errors are also stored as app_event rows so they survive compute restarts when telemetry is off.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pim import __version__
from pim.api import (
    admin,
    ai,
    approvals,
    bulk,
    dashboard,
    eligibility,
    exports,
    health,
    images,
    imports,
    metadata,
    packages,
    products,
    quality,
    reference,
    relationships,
    views,
    workflows,
)
from pim.config import get_settings

log = logging.getLogger("pim.request")
STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(title="The Fitting Room PIM", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def request_log(request: Request, call_next):  # noqa: ANN001
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            _record_error(request, rid, exc)
            log.exception(json.dumps({"request_id": rid, "path": request.url.path, "error": str(exc)}))
            return JSONResponse({"detail": "Internal error", "request_id": rid}, status_code=500)
        elapsed = int((time.monotonic() - started) * 1000)
        user = getattr(request.state, "user", None)
        if request.url.path.startswith("/api"):
            log.info(json.dumps({"request_id": rid, "method": request.method, "path": request.url.path,
                                 "status": response.status_code, "ms": elapsed, "user": user.email if user else None}))
        response.headers["X-Request-Id"] = rid
        return response

    for r in (health, metadata, workflows, products, views, approvals, packages, reference, dashboard, admin, imports, bulk,
              exports, images, ai, quality, relationships, eligibility):
        app.include_router(r.router)

    @app.on_event("startup")
    def _startup() -> None:
        if settings.env != "test":
            try:
                import pim.models  # noqa: F401
                from pim.db.session import Base, get_engine

                Base.metadata.create_all(get_engine())  # idempotent bootstrap; Alembic handles upgrades
                _seed_if_empty()
            except Exception as exc:  # noqa: BLE001
                log.error("Database bootstrap failed: %s", exc)

    if (STATIC_DIR / "index.html").exists():
        if (STATIC_DIR / "assets").exists():
            app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):  # noqa: ANN001
            candidate = resolve_static(full_path)
            if candidate is not None:
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def root() -> dict:
            return {"app": "The Fitting Room PIM", "version": __version__, "docs": "/api/docs",
                    "note": "Frontend build missing. Run `npm run build` in frontend/."}
    return app


def resolve_static(full_path: str, root: Path | None = None) -> Path | None:
    """Return the static file for a request path only when it resolves inside the static directory.
    Percent-encoded dot segments (`/..%2Fconfig.py`) must never escape it."""
    base = (root or STATIC_DIR).resolve()
    if not full_path:
        return None
    candidate = (base / full_path).resolve()
    if candidate.is_file() and candidate.is_relative_to(base):
        return candidate
    return None


def _seed_if_empty() -> None:
    """First start on a fresh Lakebase database: load seeds/*.yml so the app is usable immediately."""
    from sqlalchemy import func, select

    from pim.db.seed import seed_all
    from pim.db.session import session_scope
    from pim.models import AttributeDefinition

    with session_scope() as s:
        if s.execute(select(func.count()).select_from(AttributeDefinition)).scalar_one() == 0:
            log.info("Empty metadata layer detected; loading seeds")
            seed_all(s)


def _record_error(request: Request, rid: str, exc: Exception) -> None:
    try:
        from pim.db.session import session_scope
        from pim.models import AppEvent

        user = getattr(request.state, "user", None)
        with session_scope() as s:
            s.add(AppEvent(kind="request_error", source="api", request_id=rid, user_email=user.email if user else None,
                           payload={"path": request.url.path, "error": str(exc)[:1000]}))
    except Exception:  # noqa: BLE001
        pass


app = create_app()
