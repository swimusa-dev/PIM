"""IMG-01: poll Air boards and refresh the asset snapshot."""

from __future__ import annotations

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
        mark_job_run(session, "succeeded", totals)


if __name__ == "__main__":
    main()
