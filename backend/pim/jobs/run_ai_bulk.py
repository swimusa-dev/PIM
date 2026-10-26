"""AI-04: continue a bulk AI run after its samples were approved. Parameters: --run-id, --user."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    from pim.ai import tasks
    from pim.db.session import session_scope
    from pim.models import AiRun
    from pim.services.metadata import load_metadata

    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--user", default="system")
    a, _ = p.parse_known_args()
    with session_scope() as s:
        run = s.get(AiRun, a.run_id)
        if run is None:
            raise SystemExit(f"run {a.run_id} not found")
        meta = load_metadata(s, force=True)
        rep = run.report or {}
        user = tasks.user_for_job(s, a.user or run.created_by, roles=rep.get("requester_roles"), scopes=rep.get("requester_scopes"))
        tasks.continue_bulk(s, meta, user, run)
        mark_job_run(s, "succeeded" if run.status == "completed" else run.status, tasks.run_out(run))


if __name__ == "__main__":
    main()
