"""ARC-04: enqueue Lakeflow Jobs bound to the app as resources. Locally (no job id configured) the work runs
inline in a thread so the developer loop still works."""

from __future__ import annotations

import logging
import os
import threading

from sqlalchemy.orm import Session

from pim.models import JobRun
from pim.models._common import utcnow

log = logging.getLogger(__name__)

JOB_ENV = {"ingest": "DATABRICKS_JOB_ID_INGEST", "air_poll": "DATABRICKS_JOB_ID_AIR_POLL",
           "package": "DATABRICKS_JOB_ID_PACKAGE", "history": "DATABRICKS_JOB_ID_HISTORY",
           "import_commit": "DATABRICKS_JOB_ID_IMPORT_COMMIT", "bulk": "DATABRICKS_JOB_ID_BULK", "rules": "DATABRICKS_JOB_ID_RULES",
           "channel_export": "DATABRICKS_JOB_ID_CHANNEL_EXPORT", "renditions": "DATABRICKS_JOB_ID_RENDITIONS",
           "ai_bulk": "DATABRICKS_JOB_ID_AI_BULK", "ai_eval": "DATABRICKS_JOB_ID_AI_EVAL", "quality": "DATABRICKS_JOB_ID_QUALITY"}


def trigger_job(session: Session, kind: str, requested_by: str, params: dict) -> JobRun:
    run = JobRun(kind=kind, requested_by=requested_by, params=params, status="queued")
    session.add(run)
    session.flush()
    job_id = os.environ.get(JOB_ENV.get(kind, ""), "")
    if job_id:
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        resp = w.jobs.run_now(job_id=int(job_id), job_parameters={**{k: str(v) for k, v in params.items()}, "job_run_id": run.id})
        run.databricks_run_id = str(resp.run_id)
        run.status = "running"
        run.started_at = utcnow()
        return run
    if kind == "ingest":
        threading.Thread(target=_inline_ingest, args=(run.id,), daemon=True).start()
        run.status = "running"
        run.started_at = utcnow()
    elif kind in ("import_commit", "bulk", "rules", "channel_export", "renditions", "ai_bulk", "ai_eval", "quality"):
        # Locally (no job bound) the work runs inline in the request thread after commit; see the API layer.
        run.status = "running"
        run.started_at = utcnow()
    else:
        run.status = "skipped"
        run.error = "No Databricks job bound for this kind in this environment"
    return run


def _inline_ingest(run_id: str) -> None:
    from pim.adapters.bluecherry_source import CsvStyleMasterSource, DeltaStyleMasterSource
    from pim.config import get_settings
    from pim.db.session import session_scope
    from pim.services.ingest import run_style_master_ingest

    s = get_settings()
    with session_scope() as session:
        run = session.get(JobRun, run_id)
        try:
            csv_path = os.environ.get("PIM_LOCAL_STYLE_MASTER_CSV")
            src = CsvStyleMasterSource(csv_path) if csv_path else DeltaStyleMasterSource(s.style_master_table)
            ing = run_style_master_ingest(session, src, requested_by=run.requested_by if run else "job")
            if run:
                run.status, run.finished_at = "succeeded", utcnow()
                run.report = {"ingest_run_id": ing.id, "rows_read": ing.rows_read, "created": ing.created, "updated": ing.updated}
        except Exception as exc:  # noqa: BLE001
            log.exception("inline ingest failed")
            session.rollback()  # the ingest left the session in a failed state; start clean before recording
            run = session.get(JobRun, run_id)
            if run:
                run.status, run.finished_at, run.error = "failed", utcnow(), str(exc)[:2000]
