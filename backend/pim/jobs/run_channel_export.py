"""EXP-06 scheduled channel exports. Runs every channel whose schedule is due (or one channel with --channel-code
--force); a channel with a run in progress is skipped, never queued. Also polls adapter feedback for submitted
publishes that have a batch id (EXP-05)."""

from __future__ import annotations

import argparse
import logging

from pim.jobs._common import mark_job_run  # noqa: E402

log = logging.getLogger(__name__)


def main() -> None:
    from sqlalchemy import select

    from pim.adapters.base import NotConfigured
    from pim.db.session import session_scope
    from pim.export import publishing
    from pim.models import Channel, PublishRecord
    from pim.services.metadata import load_metadata
    from pim.services.telemetry import record_adapter_error

    p = argparse.ArgumentParser()
    p.add_argument("--channel-code", default="")
    p.add_argument("--force", default="false")
    a, _ = p.parse_known_args()
    force = a.force.lower() == "true"
    report: dict = {"runs": {}, "feedback": {}}
    with session_scope() as s:
        meta = load_metadata(s, force=True)
        channels = [c for c in s.execute(select(Channel)).scalars() if c.enabled and (not a.channel_code or c.code == a.channel_code)]
        for ch in channels:
            sched = publishing.schedule_out(ch)
            if not force and not sched.get("enabled"):
                continue
            report["runs"][ch.code] = publishing.run_scheduled(s, meta, ch, requested_by="scheduler", force=force)
            s.commit()
        # A Walmart publish reads partial or rejected after its first poll while later items still process, so the
        # candidate set is wider than status == submitted; feedback_pending decides per record.
        pending = s.execute(select(PublishRecord).where(PublishRecord.status.in_(["submitted", "partial", "rejected", "accepted"]),
                                                        PublishRecord.external_batch_id.isnot(None))).scalars()
        for rec in pending:
            ch = next((c for c in channels if c.code == rec.channel_code), None)
            if ch is None or not publishing.feedback_pending(rec):
                continue
            try:
                report["feedback"][rec.id] = publishing.poll_feedback(s, meta, ch, rec, force=False)  # Walmart: 15 min, 1 h, 2 h, then 4 h
            except (NotConfigured, NotImplementedError) as exc:
                report["feedback"][rec.id] = {"skipped": str(exc)[:200]}
            except Exception as exc:  # noqa: BLE001
                log.exception("feedback poll for %s failed", rec.id)
                record_adapter_error(s, ch.code, exc, {"publish_id": rec.id, "adapter": ch.adapter, "op": "poll"})
                report["feedback"][rec.id] = {"error": str(exc)[:200]}
            s.commit()
        mark_job_run(s, "succeeded", report)


if __name__ == "__main__":
    main()
