"""IMG-01: poll Air boards and refresh the asset snapshot."""

from __future__ import annotations

import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    from pim.adapters.air_dam import AirClient, normalize_asset
    from pim.config import get_settings
    from pim.db.session import session_scope
    from pim.services.images import upsert_assets

    s = get_settings()
    client = AirClient()
    boards = [b.strip() for b in s.air_boards.split(",") if b.strip()] or [None]
    totals = {"new": 0, "changed": 0, "unchanged": 0}
    with session_scope() as session:
        try:
            for board in boards:
                batch = []
                for item in client.list_assets(board_id=board):
                    batch.append(normalize_asset(item))
                    if len(batch) >= 500:
                        for k, v in upsert_assets(session, batch).items():
                            totals[k] += v
                        batch = []
                if batch:
                    for k, v in upsert_assets(session, batch).items():
                        totals[k] += v
        except Exception as exc:  # GOV-04: the Air failure is recorded as an adapter error before the job fails
            from pim.services.telemetry import record_adapter_error

            record_adapter_error(session, "air_dam", exc, {"op": "poll", "boards": ",".join(b or "" for b in boards)})
            mark_job_run(session, "failed", totals, error=str(exc)[:2000])
            session.commit()  # session_scope rolls back on the re-raise; the event and the failed status must survive it
            raise
        mark_job_run(session, "succeeded", totals)


if __name__ == "__main__":
    main()
