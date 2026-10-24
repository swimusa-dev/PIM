"""AI-07 evaluation set and acceptance tracking. The set is approved, human-written values for Vitamin A products;
an evaluation run generates each case with the template and scores token overlap against the reference, length
compliance, grounding and brand voice. A run is blocked when the composite drops more than the threshold below the
last passed run for the same template, and the template's eval_gate records it (activation is refused while
blocked). MLflow logging is a seam: when PIM_MLFLOW_EXPERIMENT is set and mlflow imports, metrics are logged
there too (D29)."""

from __future__ import annotations

import logging
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.adapters.base import NotConfigured
from pim.ai.service import AIService, grounding_check
from pim.ai.service import PromptTemplate as RenderTemplate
from pim.ai.tasks import AiTaskError, build_inputs, render_prompt, voice_for
from pim.auth.identity import CurrentUser
from pim.config import get_settings
from pim.models import AiEvalCase, AiEvalRun, ProductEntity, ProductValue
from pim.models import PromptTemplate as TemplateRow
from pim.models._common import utcnow
from pim.services.metadata import Metadata

log = logging.getLogger(__name__)
WEIGHTS = {"overlap": 0.5, "grounded": 0.2, "length_ok": 0.15, "voice_ok": 0.15}


def build_cases(session: Session, meta: Metadata, attribute_code: str, limit: int = 50) -> dict[str, int]:
    """Approved, human-written (not AI, not default) values become the reference set."""
    attr = meta.attributes.get(attribute_code)
    if attr is None or attr.data_type not in ("text", "rich_text"):
        raise AiTaskError("Pick a text attribute for the evaluation set")
    existing = {c.entity_id for c in session.execute(select(AiEvalCase).where(AiEvalCase.attribute_code == attribute_code)).scalars()}
    q = (select(ProductValue).where(ProductValue.attribute_code == attribute_code, ProductValue.channel_code == "",
                                     ProductValue.approval_state == "approved", ProductValue.ai_generated.is_(False),
                                     ProductValue.source_type.in_(["user", "import", "erp"]), ProductValue.value_text.isnot(None))
         .order_by(ProductValue.set_at.desc()).limit(limit * 3))
    created = 0
    for pv in session.execute(q).scalars():
        if created >= limit:
            break
        if pv.entity_id in existing or len(pv.value_text or "") < 20:
            continue
        ent = session.get(ProductEntity, pv.entity_id)
        if ent is None or "vitamin_a" not in (ent.brand_scopes or ["vitamin_a"]):
            continue
        session.add(AiEvalCase(entity_id=pv.entity_id, attribute_code=attribute_code, reference_text=pv.value_text))
        existing.add(pv.entity_id)
        created += 1
    session.flush()
    total = session.execute(select(AiEvalCase).where(AiEvalCase.attribute_code == attribute_code)).scalars().all()
    return {"created": created, "total": len(total)}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9®]+", (text or "").lower())


def token_f1(output: str, reference: str) -> float:
    a, b = Counter(_tokens(output)), Counter(_tokens(reference))
    if not a or not b:
        return 0.0
    common = sum((a & b).values())
    if common == 0:
        return 0.0
    p, r = common / sum(a.values()), common / sum(b.values())
    return round(2 * p * r / (p + r), 4)


def last_passed(session: Session, template_code: str, exclude_id: str | None = None) -> AiEvalRun | None:
    q = select(AiEvalRun).where(AiEvalRun.template_code == template_code, AiEvalRun.status == "passed").order_by(AiEvalRun.created_at.desc())
    for r in session.execute(q).scalars():
        if r.id != exclude_id:
            return r
    return None


def run_eval(session: Session, meta: Metadata, user: CurrentUser, tpl: TemplateRow, service: AIService | None = None) -> AiEvalRun:
    s = get_settings()
    cases = session.execute(select(AiEvalCase).where(AiEvalCase.attribute_code == (tpl.target_attribute or ""))).scalars().all()
    run = AiEvalRun(template_code=tpl.code, template_version=tpl.version, model="", status="running", cases=len(cases),
                    threshold=s.ai_eval_threshold, created_by=user.email)
    session.add(run)
    session.flush()
    if len(cases) < s.ai_eval_min_cases:
        run.status, run.error, run.finished_at = "failed", f"Need at least {s.ai_eval_min_cases} cases for {tpl.target_attribute}; build the set first", utcnow()
        return run
    svc = service or AIService()
    voice = voice_for(session, tpl.brand_code)
    sums = {k: 0.0 for k in WEIGHTS}
    sample: list[dict] = []
    done = 0
    try:
        for c in cases:
            ent = session.get(ProductEntity, c.entity_id)
            if ent is None:
                continue
            inp = build_inputs(session, meta, user, ent, tpl)
            # the reference must not leak into the prompt
            inp.attrs.pop(c.attribute_code, None)
            prompt = render_prompt(tpl, inp)
            rt = RenderTemplate(code=tpl.code, version=str(tpl.version), task_type=tpl.task_type, target_attribute=tpl.target_attribute or "",
                                body=prompt, max_length=inp.max_length)
            facts = {**{f"core.{k}": v for k, v in inp.core.items() if v not in (None, "")}, **inp.attrs}
            res = svc.run(rt, voice, facts, product_id=ent.id, has_certificate=inp.has_certificate, user_email=user.email,
                          endpoint=svc.endpoints.get(tpl.model_task))
            run.model = res.model
            overlap = token_f1(res.text, c.reference_text)
            length_ok = 1.0 if not inp.max_length or len(res.text) <= inp.max_length else 0.0
            grounded = 1.0 if not grounding_check(res.text, facts, has_certificate=inp.has_certificate) and not res.needs_input else 0.0
            voice_ok = 1.0 if not any(e.startswith("blocked term") or "em dash" in e for e in res.grounding_errors) else 0.0
            for k, v in (("overlap", overlap), ("length_ok", length_ok), ("grounded", grounded), ("voice_ok", voice_ok)):
                sums[k] += v
            done += 1
            if len(sample) < 10:
                sample.append({"entity_id": ent.id, "label": ent.label, "reference": c.reference_text[:600], "output": res.text[:600], "overlap": overlap})
    except NotConfigured as exc:
        run.status, run.error, run.finished_at = "failed", str(exc), utcnow()
        return run
    except Exception as exc:  # noqa: BLE001
        log.exception("eval run failed")
        run.status, run.error, run.finished_at = "failed", str(exc)[:500], utcnow()
        return run
    if done == 0:
        run.status, run.error, run.finished_at = "failed", "No cases could be run", utcnow()
        return run
    scores = {k: round(v / done, 4) for k, v in sums.items()}
    scores["composite"] = round(sum(WEIGHTS[k] * scores[k] for k in WEIGHTS), 4)
    run.scores, run.sample, run.cases = scores, sample, done
    base = last_passed(session, tpl.code, exclude_id=run.id)
    if base is not None:
        run.baseline_run_id = base.id
        run.baseline_composite = (base.scores or {}).get("composite")
        run.delta = round(scores["composite"] - (run.baseline_composite or 0), 4)
    blocked = base is not None and run.delta is not None and run.delta < -run.threshold
    run.status, run.finished_at = ("blocked" if blocked else "passed"), utcnow()
    tpl.eval_gate = {"last_run_id": run.id, "last_score": scores["composite"], "blocked": blocked, "at": run.finished_at.isoformat()}
    run.mlflow_run_id = _log_mlflow(tpl, run)
    return run


def _log_mlflow(tpl: TemplateRow, run: AiEvalRun) -> str | None:
    exp = get_settings().mlflow_experiment
    if not exp:
        return None
    try:
        import mlflow

        mlflow.set_experiment(exp)
        with mlflow.start_run(run_name=f"{tpl.code}-v{tpl.version}") as mr:
            mlflow.log_params({"template": tpl.code, "version": tpl.version, "model": run.model, "cases": run.cases})
            mlflow.log_metrics({k: float(v) for k, v in run.scores.items()})
            mlflow.set_tag("status", run.status)
            return mr.info.run_id
    except Exception as exc:  # noqa: BLE001
        log.warning("MLflow logging skipped: %s", exc)
        return None


def eval_run_out(r: AiEvalRun) -> dict:
    return {"id": r.id, "template_code": r.template_code, "template_version": r.template_version, "model": r.model, "status": r.status,
            "cases": r.cases, "scores": r.scores or {}, "baseline_run_id": r.baseline_run_id, "baseline_composite": r.baseline_composite,
            "delta": r.delta, "threshold": r.threshold, "mlflow_run_id": r.mlflow_run_id, "created_by": r.created_by,
            "created_at": r.created_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "error": r.error, "sample": r.sample or []}
