"""Schema upgrade (Alembic) and seed load against Lakebase. Run after each deploy that changes models or seeds."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs import _common  # noqa: E402
from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    root = Path(_common.__file__).resolve().parents[3]
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True)
    from pim.db.seed import seed_all
    from pim.db.session import session_scope

    with session_scope() as s:
        counts = seed_all(s)
        mark_job_run(s, "succeeded", counts)
    print(counts)


if __name__ == "__main__":
    main()
