"""GOV-01 nightly rule run and DM-09 notification digest."""

from __future__ import annotations

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
