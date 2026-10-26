"""GOV-01 nightly rule run and DM-09 notification digest."""

from __future__ import annotations

import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    from pim.db.session import session_scope
    from pim.services.collab import send_digest
    from pim.services.metadata import load_metadata
    from pim.services.rules import run_rules

    with session_scope() as s:
        results = run_rules(s, load_metadata(s, force=True), "nightly")
        digest = send_digest(s)
        mark_job_run(s, "succeeded", {"rules": results, "digest_users": len(digest)})


if __name__ == "__main__":
    main()
