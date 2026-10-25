"""Integration test setup. Uses a real Postgres (Lakebase is Postgres) at PIM_TEST_DATABASE_URL, default the
local instance started by scripts/dev_postgres.sh on port 5499."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("PIM_ENV", "test")
os.environ.setdefault("PIM_TEST_DATABASE_URL", "postgresql+psycopg://pim@localhost:5499/pim_test")
os.environ["PIM_DATABASE_URL"] = os.environ["PIM_TEST_DATABASE_URL"]
os.environ["PIM_DEV_USER_EMAIL"] = "admin@swimusa.com"
os.environ["PIM_DEV_USER_ROLES"] = "pim_admin"
os.environ["PIM_PACKAGE_VOLUME"] = str(Path(__file__).parent / "_tmp" / "packages")
os.environ["PIM_IMPORT_VOLUME"] = str(Path(__file__).parent / "_tmp" / "imports")

from pim.config import get_settings  # noqa: E402

get_settings.cache_clear()

import pim.models  # noqa: E402,F401
from pim.auth.identity import CurrentUser, build_user, reset_role_mapper  # noqa: E402
from pim.db.seed import seed_all  # noqa: E402
from pim.db.session import Base, set_engine  # noqa: E402
from pim.services.metadata import invalidate, load_metadata  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

MUTABLE_TABLES = [
    "import_conflict", "import_row", "import_batch", "mapping_template", "worksheet_export", "bulk_action", "rule_run", "rule",
    "comment", "notification", "user_setting", "product_relationship",
    "ai_output", "ai_run", "ai_eval_run", "ai_eval_case", "quality_snapshot",
    "publish_item", "eligibility_override", "image_rendition",
    "update_package_row", "update_package", "publish_record", "asset_link", "asset", "value_history", "value_draft",
    "product_value", "readiness_snapshot", "prepack_component", "identifier_alias", "workflow_item", "erp_defect",
    "ingest_run", "job_run", "app_event", "saved_view", "reference_entity", "change_set", "product_entity",
]


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(os.environ["PIM_TEST_DATABASE_URL"], future=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    set_engine(eng)
    Session = sessionmaker(bind=eng, expire_on_commit=False)
    with Session() as s:
        seed_all(s)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    yield s
    s.rollback()
    s.close()
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(MUTABLE_TABLES) + " RESTART IDENTITY CASCADE"))
    invalidate()
    reset_role_mapper()


@pytest.fixture
def meta(session):
    return load_metadata(session, force=True)


def make_user(session, email: str, roles: list[str], scopes: list[str] | None = None) -> CurrentUser:
    return build_user(email, None, roles, scopes or [], session)


@pytest.fixture
def admin(session):
    return make_user(session, "admin@swimusa.com", ["pim_admin"])


@pytest.fixture
def merch(session):
    return make_user(session, "merch@swimusa.com", ["product_merch"])


@pytest.fixture
def ecommerce(session):
    return make_user(session, "ecom@swimusa.com", ["ecommerce"])


@pytest.fixture
def viewer(session):
    return make_user(session, "viewer@swimusa.com", ["viewer"])


@pytest.fixture
def ingested(session):
    """Runs the Style Master ingest from the fixture CSV and returns the IngestRun."""
    from pim.adapters.bluecherry_source import CsvStyleMasterSource
    from pim.services.ingest import run_style_master_ingest

    run = run_style_master_ingest(session, CsvStyleMasterSource(FIXTURES / "style_master_sample.csv"), requested_by="test")
    session.commit()
    invalidate()
    return run
