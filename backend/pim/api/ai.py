"""Phase 4 AI API: brand voices and templates (AI-02), Ask AI and review (AI-03, AI-05, AI-06), bulk runs with sample
preview (AI-04), metrics and evaluation (AI-07)."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from pim.adapters.base import NotConfigured
from pim.ai import evaluation, tasks
from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.api.schemas import (
    AcceptBody,
    AiRunBody,
    AskBody,
    BrandVoiceBody,
    EvalBuildBody,
    EvalRunBody,
    RegenerateBody,
    RejectBody,
    TemplateBody,
    TemplatePreviewBody,
)
from pim.models import (
    AiEvalCase,
    AiEvalRun,
    AiOutput,
    AiRun,
    BrandVoice,
    ProductEntity,
    PromptTemplate,
    PromptTemplateVersion,
)
from pim.models._common import utcnow
from pim.services.readiness import refresh_snapshots

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["ai"])


def _admin(user: CurrentUser) -> None:
    if not user.can("admin_metadata"):
        raise HTTPException(403, "PIM Admin only")


def _run_ai(user: CurrentUser) -> None:
    if not user.can("run_ai"):
        raise HTTPException(403, "Missing permission: run_ai")


def voice_out(v: BrandVoice) -> dict:
    return {"brand_code": v.brand_code, "label": v.label, "tone": v.tone or "", "do_rules": v.do_rules or [], "dont_rules": v.dont_rules or [],
            "blocked_terms": v.blocked_terms or [], "trademark_terms": v.trademark_terms or {}, "punctuation_rules": v.punctuation_rules or [],
            "examples": v.examples or [], "version": v.version, "updated_at": v.updated_at.isoformat(), "updated_by": v.updated_by}


def template_out(t: PromptTemplate) -> dict:
    return {"code": t.code, "version": t.version, "label": t.label, "task_type": t.task_type, "target_attribute": t.target_attribute,
            "output_attributes": t.output_attributes or [], "channel_code": t.channel_code, "family_code": t.family_code, "brand_code": t.brand_code,
            "body": t.body, "input_attributes": t.input_attributes or [], "input_shot_types": t.input_shot_types or [],
            "accepts_text_input": t.accepts_text_input, "accepts_document": t.accepts_document, "max_length": t.max_length,
            "model_task": t.model_task, "status": t.status, "updated_at": t.updated_at.isoformat(), "updated_by": t.updated_by,
            "eval_gate": {"last_run_id": (t.eval_gate or {}).get("last_run_id"), "last_score": (t.eval_gate or {}).get("last_score"),
                          "blocked": bool((t.eval_gate or {}).get("blocked"))}}


def _labels(session: Session, outs: list[AiOutput]) -> dict[str, str]:
    ids = {o.entity_id for o in outs}
    return {e.id: e.label for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_(ids))).scalars()} if ids else {}


def _outs(session: Session, outs: list[AiOutput]) -> list[dict]:
    labels = _labels(session, outs)
    return [tasks.output_out(o, labels.get(o.entity_id, o.entity_id)) for o in outs]


# ---------------------------------------------------------------------------------------------------
# Brand voice and templates (AI-02)
# ---------------------------------------------------------------------------------------------------
@router.get("/ai/brand-voices")
def list_voices(session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    return [voice_out(v) for v in session.execute(select(BrandVoice).order_by(BrandVoice.brand_code)).scalars()]


@router.get("/ai/brand-voices/{brand_code}")
def get_voice(brand_code: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    v = session.get(BrandVoice, brand_code)
    if v is None:
        raise HTTPException(404, "Brand voice not found")
    return voice_out(v)


@router.put("/ai/brand-voices/{brand_code}")
def put_voice(brand_code: str, body: BrandVoiceBody, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    _admin(user)
    if not re.match(r"^[a-z0-9_]{2,64}$", brand_code):
        raise HTTPException(400, "brand_code must be lower snake case")
    if "—" in " ".join(body.examples + body.do_rules + body.dont_rules + [body.tone]):
        raise HTTPException(400, "Brand voice text must not contain the em dash character")
    v = session.get(BrandVoice, brand_code)
    data = body.model_dump()
    label = data.pop("label") or brand_code.replace("_", " ").title()
    if v is None:
        v = BrandVoice(brand_code=brand_code, label=label, **data, version=1, updated_by=user.email)
        session.add(v)
    else:
        for k, val in data.items():
            setattr(v, k, val)
        v.label, v.version, v.updated_by = label, v.version + 1, user.email
    session.commit()
    return voice_out(v)


@router.get("/ai/templates")
def list_templates(task_type: str | None = None, target: str | None = None, status: str | None = None,
                   session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    q = select(PromptTemplate)
    if task_type:
        q = q.where(PromptTemplate.task_type == task_type)
    if status:
        q = q.where(PromptTemplate.status == status)
    rows = session.execute(q.order_by(PromptTemplate.task_type, PromptTemplate.label)).scalars().all()
    if target:
        rows = [t for t in rows if t.target_attribute == target or target in (t.output_attributes or [])]
    return [template_out(t) for t in rows]


def _validate_template(meta: Metadata, body: TemplateBody) -> None:
    if body.task_type not in tasks.TASK_TYPES:
        raise HTTPException(400, f"task_type must be one of {', '.join(tasks.TASK_TYPES)}")
    if body.model_task not in ("copy", "classify"):
        raise HTTPException(400, "model_task must be copy or classify")
    targets = ([body.target_attribute] if body.target_attribute else []) + list(body.output_attributes)
    if body.task_type in ("extract", "restructure"):
        if not body.output_attributes:
            raise HTTPException(400, f"{body.task_type} templates need output_attributes")
    elif not body.target_attribute:
        raise HTTPException(400, "target_attribute is required")
    for code in targets:
        if code not in meta.attributes:
            raise HTTPException(400, f"Unknown attribute {code}")
    for code in body.input_attributes:
        base = code.split(".", 1)[0]
        if base not in meta.attributes:
            raise HTTPException(400, f"Unknown input attribute {code}")
    for st in body.input_shot_types:
        if st not in meta.shot_types:
            raise HTTPException(400, f"Unknown shot type {st}")
    if body.channel_code and body.channel_code not in meta.channels:
        raise HTTPException(400, "Unknown channel")
    if "—" in body.body:
        raise HTTPException(400, "The template body must not contain the em dash character")
    if body.task_type == "classify" and body.target_attribute and meta.attributes[body.target_attribute].data_type not in ("single_select", "multi_select"):
        raise HTTPException(400, "classify targets a select attribute")


@router.post("/ai/templates")
def create_template(body: TemplateBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                    user: CurrentUser = Depends(get_current_user)) -> dict:
    _admin(user)
    _validate_template(meta, body)
    code = body.code or re.sub(r"[^a-z0-9]+", "_", body.label.lower()).strip("_")[:64]
    if not re.match(r"^[a-z0-9_]{2,64}$", code):
        raise HTTPException(400, "code must be lower snake case")
    if session.get(PromptTemplate, code) is not None:
        raise HTTPException(409, f"Template {code} already exists")
    data = body.model_dump(exclude={"code", "note", "status"})
    t = PromptTemplate(code=code, **data, status="draft", version=1, updated_by=user.email)
    session.add(t)
    session.flush()
    session.add(PromptTemplateVersion(code=code, version=1, body=t.body, snapshot=data, note=body.note, updated_by=user.email))
    session.commit()
    return template_out(t)


@router.get("/ai/templates/{code}")
def get_template(code: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    t = session.get(PromptTemplate, code)
    if t is None:
        raise HTTPException(404, "Template not found")
    versions = session.execute(select(PromptTemplateVersion).where(PromptTemplateVersion.code == code).order_by(PromptTemplateVersion.version.desc())).scalars().all()
    return {**template_out(t), "versions": [{"version": v.version, "body": v.body, "updated_at": v.updated_at.isoformat(), "updated_by": v.updated_by, "note": v.note} for v in versions]}


@router.put("/ai/templates/{code}")
def update_template(code: str, body: TemplateBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                    user: CurrentUser = Depends(get_current_user)) -> dict:
    _admin(user)
    t = session.get(PromptTemplate, code)
    if t is None:
        raise HTTPException(404, "Template not found")
    _validate_template(meta, body)
    data = body.model_dump(exclude={"code", "note", "status"})
    body_changed = t.body.strip() != body.body.strip()
    for k, v in data.items():
        setattr(t, k, v)
    if body.status in ("draft", "active", "retired"):
        if body.status == "active" and (t.eval_gate or {}).get("blocked"):
            raise HTTPException(409, "The last evaluation run blocked this template (AI-07); fix the prompt and re-run the evaluation")
        t.status = body.status
    t.updated_by = user.email
    if body_changed:
        t.version += 1
        t.eval_gate = {}  # a new body needs a new evaluation
        session.add(PromptTemplateVersion(code=code, version=t.version, body=t.body, snapshot=data, note=body.note, updated_by=user.email))
    session.commit()
    return template_out(t)


@router.post("/ai/templates/{code}/activate")
def activate_template(code: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    _admin(user)
    t = session.get(PromptTemplate, code)
    if t is None:
        raise HTTPException(404, "Template not found")
    if (t.eval_gate or {}).get("blocked"):
        raise HTTPException(409, "The last evaluation run blocked this template (AI-07); fix the prompt and re-run the evaluation")
    t.status, t.updated_by = "active", user.email
    session.commit()
    return template_out(t)


@router.post("/ai/templates/{code}/preview")
def preview_template(code: str, body: TemplatePreviewBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                     user: CurrentUser = Depends(get_current_user)) -> dict:
    t = session.get(PromptTemplate, code)
    ent = session.get(ProductEntity, body.entity_id)
    if t is None or ent is None:
        raise HTTPException(404, "Template or product not found")
    try:
        inp = tasks.build_inputs(session, meta, user, ent, t, channel_code=body.channel_code or t.channel_code or "", text=body.text)
    except tasks.AiTaskError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"prompt": tasks.render_prompt(t, inp), "inputs": {**{f"core.{k}": v for k, v in inp.core.items()}, **inp.attrs},
            "missing_inputs": inp.missing, "image_urls": inp.image_urls, "max_length": inp.max_length}


# ---------------------------------------------------------------------------------------------------
# Ask AI (AI-03)
# ---------------------------------------------------------------------------------------------------
@router.get("/products/{entity_id}/ai/templates")
def product_templates(entity_id: str, attribute: str | None = None, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                      user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = session.get(ProductEntity, entity_id)
    if ent is None or not user.in_brand_scope(ent.brand_scopes or []):
        raise HTTPException(404, "Product not found")
    return {"templates": [template_out(t) for t in tasks.templates_for(session, meta, ent, attribute)], "can_run": user.can("run_ai")}


@router.post("/ai/ask")
def ask(body: AskBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    _run_ai(user)
    t = session.get(PromptTemplate, body.template_code)
    ent = session.get(ProductEntity, body.entity_id)
    if t is None or ent is None or not user.in_brand_scope(ent.brand_scopes or []):
        raise HTTPException(404, "Template or product not found")
    if t.status != "active" and not user.can("admin_metadata"):
        raise HTTPException(409, "This template is not active")
    for code in ([t.target_attribute] if t.target_attribute else []) + list(t.output_attributes or []):
        attr = meta.attributes.get(code)
        if attr is not None and t.task_type != "check" and not user.can_edit_group(attr.group_code):
            raise HTTPException(403, f"No edit rights on {attr.label}'s group")
    if body.channel_code and body.channel_code not in meta.channels:
        raise HTTPException(400, "Unknown channel")
    try:
        outs = tasks.run_task(session, meta, user, ent, t, channel_code=body.channel_code or "", text=body.text, document=body.document,
                              image_asset_ids=body.image_asset_ids)
    except tasks.AiTaskError as exc:
        raise HTTPException(400, str(exc)) from exc
    except NotConfigured as exc:
        raise HTTPException(409, f"AI endpoint not configured: {exc}") from exc
    session.commit()
    return {"outputs": _outs(session, outs)}


@router.get("/ai/outputs")
def list_outputs(entity_id: str | None = None, run_id: str | None = None, status: str | None = None, template_code: str | None = None,
                 page: int = 1, page_size: int = 50, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                 user: CurrentUser = Depends(get_current_user)) -> dict:
    q = select(AiOutput)
    if entity_id:
        q = q.where(AiOutput.entity_id == entity_id)
    if run_id:
        q = q.where(AiOutput.run_id == run_id)
    if status:
        q = q.where(AiOutput.status == status)
    if template_code:
        q = q.where(AiOutput.template_code == template_code)
    # RBAC in SQL, like the grid: view rights on the attribute's group, brand scope on the product
    from sqlalchemy import String, cast, or_

    hidden = [a.code for a in meta.attributes.values() if not user.can_view_group(a.group_code)]
    if hidden:
        q = q.where(AiOutput.attribute_code.notin_(hidden))
    q = q.join(ProductEntity, ProductEntity.id == AiOutput.entity_id)
    if user.brand_scopes:
        q = q.where(or_(*[cast(ProductEntity.brand_scopes, String).like(f'%"{sc}"%') for sc in user.brand_scopes]))
    total = session.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = session.execute(q.order_by(AiOutput.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"rows": _outs(session, rows), "total": total}


def _output(session: Session, output_id: str, user: CurrentUser | None = None) -> AiOutput:
    o = session.get(AiOutput, output_id)
    if o is None:
        raise HTTPException(404, "Output not found")
    if user is not None:
        ent = session.get(ProductEntity, o.entity_id)
        if ent is None or not user.in_brand_scope(ent.brand_scopes or []):
            raise HTTPException(404, "Output not found")  # RBAC-04: outside the user's brand scope reads as absent
    return o


@router.post("/ai/outputs/{output_id}/accept")
def accept(output_id: str, body: AcceptBody | None = None, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
           user: CurrentUser = Depends(get_current_user)) -> dict:
    o = _output(session, output_id, user)
    attr = meta.attributes.get(o.attribute_code)
    if attr is None or not user.can_edit_group(attr.group_code):
        raise HTTPException(403, "No edit rights on this attribute's group")
    try:
        tasks.accept_output(session, meta, user, o, body.value if body else None)
    except tasks.AiTaskError as exc:
        raise HTTPException(409, str(exc)) from exc
    ent = session.get(ProductEntity, o.entity_id)
    if ent is not None:
        refresh_snapshots(session, meta, [ent])
    session.commit()
    return _outs(session, [o])[0]


@router.post("/ai/outputs/{output_id}/reject")
def reject(output_id: str, body: RejectBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
           user: CurrentUser = Depends(get_current_user)) -> dict:
    o = _output(session, output_id, user)
    attr = meta.attributes.get(o.attribute_code)
    if attr is not None and not user.can_edit_group(attr.group_code):
        raise HTTPException(403, "No edit rights on this attribute's group")
    if not body.reason.strip():
        raise HTTPException(400, "A rejection reason is required (AI-07)")
    try:
        tasks.reject_output(session, user, o, body.reason)
    except tasks.AiTaskError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return _outs(session, [o])[0]


@router.post("/ai/outputs/{output_id}/regenerate")
def regenerate(output_id: str, body: RegenerateBody | None = None, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
               user: CurrentUser = Depends(get_current_user)) -> dict:
    _run_ai(user)
    o = _output(session, output_id, user)
    t = session.get(PromptTemplate, o.template_code)
    ent = session.get(ProductEntity, o.entity_id)
    if t is None or ent is None:
        raise HTTPException(404, "Template or product no longer exists")
    attr = meta.attributes.get(o.attribute_code)
    if attr is not None and t.task_type != "check" and not user.can_edit_group(attr.group_code):
        raise HTTPException(403, "No edit rights on this attribute's group")
    if o.status in ("proposed", "edited", "needs_input", "failed", "info"):
        try:
            tasks.reject_output(session, user, o, "regenerated")
        except tasks.AiTaskError:
            pass
    inputs = o.inputs or {}
    try:
        outs = tasks.run_task(session, meta, user, ent, t, channel_code=o.channel_code or "", text=inputs.get("text"),
                              image_asset_ids=inputs.get("image_asset_ids") or None, run_id=o.run_id)
    except tasks.AiTaskError as exc:
        raise HTTPException(400, str(exc)) from exc
    except NotConfigured as exc:
        raise HTTPException(409, f"AI endpoint not configured: {exc}") from exc
    session.commit()
    rendered = _outs(session, outs)
    return {**rendered[0], "outputs": rendered, "note": body.note if body else None}


# ---------------------------------------------------------------------------------------------------
# Bulk (AI-04)
# ---------------------------------------------------------------------------------------------------
@router.post("/ai/runs")
def create_run(body: AiRunBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    _run_ai(user)
    t = session.get(PromptTemplate, body.template_code)
    if t is None or t.status != "active":
        raise HTTPException(404, "Active template not found")
    from pim.services.bulk import resolve_entities

    sel = dict(body.selection or {})
    targets = ([t.target_attribute] if t.target_attribute else []) + list(t.output_attributes or [])
    level = meta.attributes[targets[0]].level if targets and targets[0] in meta.attributes else "style_color"
    sel.setdefault("level", level)
    ents = resolve_entities(session, meta, user, sel)
    if not ents and sel.get("level") != "style_color" and (sel.get("entity_ids") or sel.get("view_id")):
        # A style-level template run from a style-color selection: one run per owning style, never per color.
        picked = resolve_entities(session, meta, user, {**sel, "level": "style_color"})
        owners: dict[str, ProductEntity] = {}
        for e in picked:
            o = tasks._owner_for(session, e, meta.attributes[targets[0]]) if targets and targets[0] in meta.attributes else None
            if o is not None:
                owners[o.id] = o
        ents = list(owners.values())
    if not ents:
        raise HTTPException(400, "The selection resolves to no products at the template's level")
    for code in targets:
        attr = meta.attributes.get(code)
        if attr is not None and not user.can_edit_group(attr.group_code):
            raise HTTPException(403, f"No edit rights on {attr.label}'s group")
    try:
        run, outs = tasks.start_bulk(session, meta, user, t, ents, sel, body.channel_code or "")
    except tasks.AiTaskError as exc:
        raise HTTPException(400, str(exc)) from exc
    except NotConfigured as exc:
        session.rollback()
        raise HTTPException(409, f"AI endpoint not configured: {exc}") from exc
    session.commit()
    return {**tasks.run_out(run), "outputs": _outs(session, outs)}


@router.get("/ai/runs")
def list_runs(status: str | None = None, page: int = 1, page_size: int = 50, session: Session = Depends(get_session),
              user: CurrentUser = Depends(get_current_user)) -> dict:
    q = select(AiRun).where(AiRun.kind != "eval")
    if status:
        q = q.where(AiRun.status == status)
    total = session.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = session.execute(q.order_by(AiRun.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"rows": [tasks.run_out(r) for r in rows], "total": total}


def _run(session: Session, run_id: str) -> AiRun:
    r = session.get(AiRun, run_id)
    if r is None:
        raise HTTPException(404, "Run not found")
    return r


@router.get("/ai/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    r = _run(session, run_id)
    outs = session.execute(select(AiOutput).where(AiOutput.run_id == r.id).order_by(AiOutput.created_at).limit(200)).scalars().all()
    return {**tasks.run_out(r), "outputs": _outs(session, outs)}


@router.post("/ai/runs/{run_id}/approve-samples")
def approve_samples(run_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    _run_ai(user)
    r = _run(session, run_id)
    if r.status != "sample_pending":
        raise HTTPException(409, f"Run is {r.status}")
    from pim.services.jobs import trigger_job

    r.status = "sample_approved"
    job = trigger_job(session, "ai_bulk", user.email, {"run_id": r.id, "user": user.email})
    r.job_run_id = job.id
    session.commit()
    if not job.databricks_run_id:
        tasks.continue_bulk(session, meta, user, r)
        job.status, job.finished_at, job.report = ("succeeded" if r.status == "completed" else r.status), utcnow(), tasks.run_out(r)
        session.commit()
    return tasks.run_out(r)


@router.post("/ai/runs/{run_id}/cancel")
def cancel_run(run_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    r = _run(session, run_id)
    if r.created_by != user.email and not user.can("admin_metadata"):
        raise HTTPException(403, "Only the run's owner or an admin can cancel it")
    if r.status in ("completed", "failed", "cancelled"):
        raise HTTPException(409, f"Run is already {r.status}")
    r.status, r.finished_at = "cancelled", utcnow()
    session.commit()
    return tasks.run_out(r)


@router.post("/ai/runs/{run_id}/accept-all")
def accept_all(run_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    r = _run(session, run_id)
    t = session.get(PromptTemplate, r.template_code)
    targets = ([t.target_attribute] if t and t.target_attribute else []) + list((t.output_attributes if t else []) or [])
    if not any(user.can_approve_group(meta.attributes[c].group_code) for c in targets if c in meta.attributes):
        raise HTTPException(403, "Accept all needs Approve rights on the target attribute group (AI-04)")
    result = tasks.accept_all(session, meta, user, r)
    ids = {o.entity_id for o in session.execute(select(AiOutput).where(AiOutput.run_id == r.id, AiOutput.status.in_(["accepted", "edited"]))).scalars()}
    ents = session.execute(select(ProductEntity).where(ProductEntity.id.in_(ids))).scalars().all() if ids else []
    if ents:
        refresh_snapshots(session, meta, ents)
    session.commit()
    return result


# ---------------------------------------------------------------------------------------------------
# Metrics and evaluation (AI-07)
# ---------------------------------------------------------------------------------------------------
@router.get("/ai/metrics")
def ai_metrics(template_code: str | None = None, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    return tasks.metrics(session, template_code)


@router.get("/ai/eval/cases")
def eval_cases(attribute: str | None = None, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    q = select(AiEvalCase)
    if attribute:
        q = q.where(AiEvalCase.attribute_code == attribute)
    rows = session.execute(q.order_by(AiEvalCase.created_at.desc())).scalars().all()
    labels = {e.id: e.label for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_({c.entity_id for c in rows}))).scalars()} if rows else {}
    return [{"id": c.id, "entity_id": c.entity_id, "label": labels.get(c.entity_id, c.entity_id), "attribute_code": c.attribute_code,
             "reference_text": c.reference_text, "created_at": c.created_at.isoformat()} for c in rows]


@router.post("/ai/eval/cases/build")
def build_eval_cases(body: EvalBuildBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                     user: CurrentUser = Depends(get_current_user)) -> dict:
    _admin(user)
    try:
        result = evaluation.build_cases(session, meta, body.attribute_code, max(1, min(body.limit, 200)))
    except tasks.AiTaskError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return result


@router.delete("/ai/eval/cases/{case_id}")
def delete_eval_case(case_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    _admin(user)
    c = session.get(AiEvalCase, case_id)
    if c is None:
        raise HTTPException(404, "Case not found")
    session.delete(c)
    session.commit()
    return {"deleted": True}


@router.get("/ai/eval/runs")
def eval_runs(template_code: str | None = None, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    q = select(AiEvalRun)
    if template_code:
        q = q.where(AiEvalRun.template_code == template_code)
    return [evaluation.eval_run_out(r) for r in session.execute(q.order_by(AiEvalRun.created_at.desc()).limit(200)).scalars()]


@router.post("/ai/eval/runs")
def start_eval_run(body: EvalRunBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                   user: CurrentUser = Depends(get_current_user)) -> dict:
    _admin(user)
    t = session.get(PromptTemplate, body.template_code)
    if t is None:
        raise HTTPException(404, "Template not found")
    from pim.services.jobs import trigger_job

    job = trigger_job(session, "ai_eval", user.email, {"template_code": t.code, "user": user.email})
    if job.databricks_run_id:
        session.commit()
        return {"status": "started", "job_run_id": job.id}
    run = evaluation.run_eval(session, meta, user, t)
    job.status, job.finished_at, job.report = ("succeeded" if run.status != "failed" else "failed"), utcnow(), {"eval_run_id": run.id, "status": run.status}
    session.commit()
    return evaluation.eval_run_out(run)
