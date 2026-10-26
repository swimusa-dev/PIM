"""IMG-03 tiers 1 and 2 over pending assets. Tier 3 (AI candidates) is wired in once PLT-00 step 8 passes."""

from __future__ import annotations

import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    from pim.db.session import session_scope
    from pim.services.images import run_matching
    from pim.services.metadata import load_metadata

    with session_scope() as session:
        stats = run_matching(session, load_metadata(session, force=True))
        mark_job_run(session, "succeeded", stats)


if __name__ == "__main__":
    main()
