"""GOV-03: recompute the data quality score for every style-color (nightly, and on demand from Admin > Quality)."""

from __future__ import annotations

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
