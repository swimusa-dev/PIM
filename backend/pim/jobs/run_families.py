"""Re-assign product families from the Style Master without a full load (reads two columns, updates in bulk)."""

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
    from pim.services.ingest import refresh_families

    p = argparse.ArgumentParser()
    p.add_argument("--source", default="delta", choices=["delta", "csv"])
    p.add_argument("--table")
    p.add_argument("--csv")
    a, _ = p.parse_known_args()
    src = CsvStyleMasterSource(a.csv) if a.source == "csv" else DeltaStyleMasterSource(a.table)
    try:
        with session_scope() as s:
            result = refresh_families(s, src)
            mark_job_run(s, "succeeded", result)
        print(result)
    except Exception as exc:  # noqa: BLE001
        with session_scope() as s:
            mark_job_run(s, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    main()
