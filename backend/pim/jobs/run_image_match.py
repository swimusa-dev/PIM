"""IMG-03 tiers 1 and 2 over pending assets. Tier 3 (AI candidates) is wired in once PLT-00 step 8 passes."""

from __future__ import annotations

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
