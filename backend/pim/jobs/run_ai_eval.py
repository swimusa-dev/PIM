"""AI-07: run the evaluation set for one template (or every active template with --all)."""

from __future__ import annotations

import argparse

from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    from sqlalchemy import select

    from pim.ai import evaluation
    from pim.auth.identity import build_user
    from pim.db.session import session_scope
    from pim.models import PromptTemplate
    from pim.services.metadata import load_metadata

    p = argparse.ArgumentParser()
    p.add_argument("--template-code", default="")
    p.add_argument("--user", default="system")
    a, _ = p.parse_known_args()
    report = {}
    with session_scope() as s:
        meta = load_metadata(s, force=True)
        user = build_user(a.user, None, ["pim_admin"], [], s)
        if a.template_code:
            tpls = [s.get(PromptTemplate, a.template_code)]
        else:
            tpls = s.execute(select(PromptTemplate).where(PromptTemplate.status == "active", PromptTemplate.task_type.in_(["generate", "adapt", "expand"]))).scalars().all()
        for t in tpls:
            if t is None:
                continue
            run = evaluation.run_eval(s, meta, user, t)
            report[t.code] = {"status": run.status, "composite": (run.scores or {}).get("composite"), "delta": run.delta}
            s.commit()
        mark_job_run(s, "succeeded", report)


if __name__ == "__main__":
    main()
