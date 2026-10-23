"""Lakebase connection management (ARC-02, PLT-00 step 5).

Lakebase is managed Postgres. The app's service principal authenticates with an OAuth token that expires
hourly [D12], so we never bake a password into the URL. Instead a SQLAlchemy `do_connect` hook asks the
Databricks SDK for a fresh credential whenever the cached one is older than `lakebase_token_ttl_seconds`.
Connections that already exist keep working until the pool recycles them (`pool_recycle`), which is what
the 2-hour soak in PLT-00 step 5 verifies.

Locally, set PIM_DATABASE_URL to a plain Postgres URL and the token hook is skipped.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from pim.config import Settings, get_settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class _TokenCache:
    """Thread-safe cache of the Lakebase OAuth token (one per process)."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._token: str | None = None
        self._fetched_at = 0.0

    def get(self, instance_name: str) -> str:
        with self._lock:
            if self._token and time.monotonic() - self._fetched_at < self._ttl:
                return self._token
            from databricks.sdk import WorkspaceClient

            w = WorkspaceClient()
            cred = w.database.generate_database_credential(instance_names=[instance_name])
            self._token = cred.token
            self._fetched_at = time.monotonic()
            log.info("Refreshed Lakebase credential for %s", instance_name)
            return self._token


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_engine_lock = threading.Lock()


def _build_url(settings: Settings) -> str:
    if settings.database_url:
        return settings.database_url
    host = os.environ.get("PGHOST")
    if not host:
        raise RuntimeError("Set PIM_DATABASE_URL or bind a Lakebase resource (PGHOST etc.) to the app")
    port = os.environ.get("PGPORT", "5432")
    db = os.environ.get("PGDATABASE", "pim")
    user = os.environ.get("PGUSER", "")
    sslmode = os.environ.get("PGSSLMODE", "require")
    return f"postgresql+psycopg://{user}@{host}:{port}/{db}?sslmode={sslmode}"


def build_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    url = _build_url(settings)
    engine = create_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=settings.lakebase_token_ttl_seconds,
        future=True,
    )
    if not settings.database_url:
        instance = settings.lakebase_instance or os.environ.get("PGHOST", "").split(".")[0]
        cache = _TokenCache(settings.lakebase_token_ttl_seconds)

        @event.listens_for(engine, "do_connect")
        def _inject_token(dialect, conn_rec, cargs, cparams):  # noqa: ANN001
            cparams["password"] = cache.get(instance)

    return engine


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = build_engine()
                _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def set_engine(engine: Engine) -> None:
    """Used by tests to point the app at a throwaway database."""
    global _engine, _SessionLocal
    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
