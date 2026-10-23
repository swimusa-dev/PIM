from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Make `pim` importable when Databricks runs the file directly from the workspace path.
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _apply_connection_args() -> None:
    """Jobs do not receive the app's resource env vars, so the bundle passes them as task parameters:
    --pg-host, --pg-user, --pg-database, --lakebase-instance, --sql-warehouse-id, --job-run-id."""
    import argparse

    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--pg-host")
    p.add_argument("--pg-user")
    p.add_argument("--pg-database")
    p.add_argument("--lakebase-instance")
    p.add_argument("--sql-warehouse-id")
    p.add_argument("--job-run-id")
    a, _ = p.parse_known_args()
    mapping = {"PGHOST": a.pg_host, "PGUSER": a.pg_user, "PGDATABASE": a.pg_database, "PGSSLMODE": "require" if a.pg_host else None,
               "PIM_LAKEBASE_INSTANCE": a.lakebase_instance, "PIM_SQL_WAREHOUSE_ID": a.sql_warehouse_id, "JOB_RUN_ID": a.job_run_id,
               "PIM_ENV": "databricks" if a.pg_host else None}
    for k, v in mapping.items():
        if v:
            os.environ[k] = v


_apply_connection_args()


def mark_job_run(session, status: str, report: dict | None = None, error: str | None = None) -> None:  # noqa: ANN001
    """Update the app's job_run row when the job was triggered from the UI (job parameter job_run_id)."""
    from pim.models import JobRun
    from pim.models._common import utcnow

    rid = os.environ.get("JOB_RUN_ID") or _param("job_run_id")
    if not rid:
        return
    run = session.get(JobRun, rid)
    if run:
        run.status, run.finished_at, run.report, run.error = status, utcnow(), report or {}, error


def _param(name: str) -> str | None:
    try:
        import IPython  # type: ignore
        from dbruntime.dbutils import DBUtils  # type: ignore  # noqa: F401

        dbutils = IPython.get_ipython().user_ns["dbutils"]
        return dbutils.widgets.get(name)
    except Exception:  # noqa: BLE001
        return None
