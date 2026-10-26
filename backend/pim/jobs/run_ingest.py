"""IMP-09: Style Master ingest job."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs._common import mark_job_run  # noqa: E402  (adjusts sys.path)


def main() -> None:
    from pim.adapters.bluecherry_source import CsvStyleMasterSource, DeltaStyleMasterSource
    from pim.db.session import session_scope
    from pim.services.ingest import run_style_master_ingest

    p = argparse.ArgumentParser()
    p.add_argument("--source", default="delta", choices=["delta", "csv"])
    p.add_argument("--table")
    p.add_argument("--csv")
    a, _ = p.parse_known_args()
    src = CsvStyleMasterSource(a.csv) if a.source == "csv" else DeltaStyleMasterSource(a.table)
    try:
        with session_scope() as s:
            run = run_style_master_ingest(s, src, requested_by="job")
            mark_job_run(s, "succeeded", {"ingest_run_id": run.id, "rows_read": run.rows_read, "created": run.created,
                                          "updated": run.updated, "defects": run.defects_found})
    except Exception as exc:  # noqa: BLE001
        # The failed transaction above is rolled back by session_scope; record the failure separately.
        with session_scope() as s:
            mark_job_run(s, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    main()
