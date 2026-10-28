"""Schema upgrade (Alembic) and seed load against Lakebase. Run after each deploy that changes models or seeds."""

from __future__ import annotations

import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs import _common  # noqa: E402
from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    from alembic import command
    from alembic.config import Config

    # In-process on purpose: the Databricks SDK's runtime auth (Lakebase tokens) does not exist in a subprocess.
    root = Path(_common.__file__).resolve().parents[3]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(cfg, "head")
    from pim.db.seed import seed_all
    from pim.db.session import session_scope
    from pim.services.ingest import close_baseline_launch_items
    from pim.services.sizes import reevaluate_sizes

    with session_scope() as s:
        counts = seed_all(s)
        s.flush()
        counts.update(reevaluate_sizes(s))  # a scale that gained a value clears its SKUs' size flags and defects
        counts["launch_tasks_closed"] = close_baseline_launch_items(s)  # tasks the first load opened for the whole catalog
        mark_job_run(s, "succeeded", counts)
    print(counts)


if __name__ == "__main__":
    main()
