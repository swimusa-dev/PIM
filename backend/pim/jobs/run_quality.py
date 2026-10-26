"""GOV-03: recompute the data quality score for every style-color (nightly, and on demand from Admin > Quality)."""

from __future__ import annotations

import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    from pim.db.session import session_scope
    from pim.services.metadata import load_metadata
    from pim.services.quality import recompute_all

    with session_scope() as s:
        n = recompute_all(s, load_metadata(s, force=True))
        mark_job_run(s, "succeeded", {"computed": n})


if __name__ == "__main__":
    main()
