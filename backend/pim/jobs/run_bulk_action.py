"""DM-04: run a bulk action as a job."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    from sqlalchemy import select

    from pim.auth.identity import build_user
    from pim.db.session import session_scope
    from pim.models import BulkAction, UserRole
    from pim.services.bulk import run
    from pim.services.metadata import load_metadata

    p = argparse.ArgumentParser()
    p.add_argument("--action-id", required=True)
    a, _ = p.parse_known_args()
    try:
        with session_scope() as s:
            action = s.get(BulkAction, a.action_id)
            if action is None:
                raise SystemExit("action not found")
            roles = [r.role_code for r in s.execute(select(UserRole).where(UserRole.email == action.created_by)).scalars()]
            user = build_user(action.created_by, None, roles, [], s)
            report = run(s, load_metadata(s, force=True), user, action)
            mark_job_run(s, "succeeded", {k: v for k, v in report.items() if k != "items"})
    except Exception as exc:  # noqa: BLE001
        with session_scope() as s:
            action = s.get(BulkAction, a.action_id)
            if action:
                action.status, action.error = "failed", str(exc)[:2000]
            mark_job_run(s, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    main()
