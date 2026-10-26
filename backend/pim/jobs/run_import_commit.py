"""IMP-07: commit an import batch as a job."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    from pim.auth.identity import build_user
    from pim.db.session import session_scope
    from pim.imports.survivorship import commit_batch
    from pim.models import ImportBatch
    from pim.services.metadata import load_metadata

    p = argparse.ArgumentParser()
    p.add_argument("--batch-id", required=True)
    p.add_argument("--user", default="job")
    a, _ = p.parse_known_args()
    try:
        with session_scope() as s:
            batch = s.get(ImportBatch, a.batch_id)
            if batch is None:
                raise SystemExit("batch not found")
            user = build_user(a.user, None, ["pim_admin"], [], s)
            report = commit_batch(s, load_metadata(s, force=True), user, batch)
            mark_job_run(s, "succeeded", report)
    except Exception as exc:  # noqa: BLE001
        with session_scope() as s:
            batch = s.get(ImportBatch, a.batch_id)
            if batch:
                batch.status, batch.error = "failed", str(exc)[:2000]
            mark_job_run(s, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    main()
