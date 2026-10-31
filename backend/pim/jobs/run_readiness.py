"""D-15: apply eligibility and brand scope changes to the loaded products (scopes re-derived, readiness and quality recomputed)."""

from __future__ import annotations

import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    from pim.db.session import session_scope
    from pim.services.eligibility import recompute_scopes_and_readiness

    with session_scope() as s:
        result = recompute_scopes_and_readiness(s)
        mark_job_run(s, "succeeded", result)
    print(result)


if __name__ == "__main__":
    main()
