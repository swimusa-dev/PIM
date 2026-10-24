"""DM-04 bulk actions and GOV-01 rules API."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.auth.identity import require_permission
from pim.models import BulkAction, Rule, RuleRun
from pim.models._common import utcnow
from pim.services import bulk as bulk_service
from pim.services.collab import notify
from pim.services.jobs import trigger_job
from pim.services.rules import preview_rule, run_rules

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["bulk", "rules"])


class PreviewBody(BaseModel):
    kind: str
    selection: dict
    params: dict = {}


class RuleBody(BaseModel):
    code: str
    label: str
    priority: int = 100
    enabled: bool = True
    trigger: str = "all"
    level: str = "style_color"
    condition: dict = {}
    actions: list[dict] = []
    brand_scopes: list[str] = []


class ActivateBody(BaseModel):
    force: bool = False
    reason: str | None = None


def _action_out(a: BulkAction) -> dict:
    return {"id": a.id, "kind": a.kind, "selection": a.selection or {}, "params": a.params or {}, "status": a.status, "preview": a.preview or {},
            "report": a.report or {}, "change_set_id": a.change_set_id, "created_by": a.created_by, "created_at": a.created_at.isoformat(), "error": a.error}


@router.post("/bulk/preview")
def preview(body: PreviewBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
            user: CurrentUser = Depends(require_permission("bulk_edit"))) -> dict:
    try:
        action = bulk_service.preview(session, meta, user, body.kind, body.selection, body.params)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return _action_out(action)


@router.post("/bulk/{action_id}/run")
def run(action_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
        user: CurrentUser = Depends(require_permission("bulk_edit"))) -> dict:
    action = session.get(BulkAction, action_id)
    if action is None:
        raise HTTPException(404, "Bulk action not found")
    if action.status != "preview":
        raise HTTPException(409, "This action already ran")
    if action.created_by != user.email and not user.can("admin_metadata"):
        raise HTTPException(403, "Only the creator runs a previewed action")
    job = trigger_job(session, "bulk", user.email, {"action_id": action.id})
    action.job_run_id = job.id
    if not os.environ.get("DATABRICKS_JOB_ID_BULK"):
        try:
            bulk_service.run(session, meta, user, action)
            job.status = "succeeded"
        except Exception as exc:  # noqa: BLE001
            log.exception("bulk run failed")
            session.rollback()
            action = session.get(BulkAction, action_id)
            action.status, action.error = "failed", str(exc)[:2000]
    else:
        action.status = "queued"
    session.commit()
    if action.status in ("succeeded", "failed"):
        r = action.report or {}
        notify(session, user.email, "bulk", f"Bulk {action.kind} {action.status}", f"{r.get('changed', 0)} changed, {r.get('skipped', 0)} skipped, {r.get('failed', 0)} failed", f"/bulk/{action.id}")
        session.commit()
    return _action_out(action)


@router.get("/bulk")
def list_actions(page: int = 1, page_size: int = 50, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    q = select(BulkAction).where(BulkAction.status != "preview")
    total = session.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = session.execute(q.order_by(BulkAction.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"rows": [_action_out(a) for a in rows], "total": total}


@router.get("/bulk/{action_id}")
def get_action(action_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    a = session.get(BulkAction, action_id)
    if a is None:
        raise HTTPException(404, "Bulk action not found")
    return _action_out(a)


@router.post("/bulk/{action_id}/rollback")
def rollback(action_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
             user: CurrentUser = Depends(require_permission("bulk_edit"))) -> dict:
    a = session.get(BulkAction, action_id)
    if a is None:
        raise HTTPException(404, "Bulk action not found")
    try:
        res = bulk_service.rollback(session, meta, user, a)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return res


# ---- rules (GOV-01) ---------------------------------------------------------------------------------------
def _rule_out(r: Rule) -> dict:
    return {"id": r.id, "code": r.code, "label": r.label, "priority": r.priority, "enabled": r.enabled, "status": r.status, "trigger": r.trigger,
            "level": r.level, "condition": r.condition or {}, "actions": r.actions or [], "brand_scopes": r.brand_scopes or [],
            "last_preview": r.last_preview, "activated_at": r.activated_at.isoformat() if r.activated_at else None, "activated_by": r.activated_by,
            "activation_reason": r.activation_reason}


@router.get("/rules")
def list_rules(session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    return [_rule_out(r) for r in session.execute(select(Rule).order_by(Rule.priority, Rule.code)).scalars()]


@router.post("/rules")
def create_rule(body: RuleBody, session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    if session.execute(select(Rule).where(Rule.code == body.code)).first():
        raise HTTPException(409, "A rule with this code exists")
    r = Rule(**body.model_dump(), created_by=user.email)
    session.add(r)
    session.commit()
    return _rule_out(r)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, body: RuleBody, session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    r = session.get(Rule, rule_id)
    if r is None:
        raise HTTPException(404, "Rule not found")
    changed_logic = (r.condition != body.condition) or (r.actions != body.actions) or (r.level != body.level)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    if changed_logic and r.status == "active":
        r.status, r.last_preview = "draft", None  # GOV-06: a changed calculation needs a new preview
    session.commit()
    return _rule_out(r)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    r = session.get(Rule, rule_id)
    if r:
        session.delete(r)
        session.commit()
    return {"deleted": rule_id}


@router.post("/rules/{rule_id}/preview")
def preview_endpoint(rule_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                     user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    r = session.get(Rule, rule_id)
    if r is None:
        raise HTTPException(404, "Rule not found")
    out = preview_rule(session, meta, r)
    session.commit()
    return out


@router.post("/rules/{rule_id}/activate")
def activate(rule_id: str, body: ActivateBody, session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    r = session.get(Rule, rule_id)
    if r is None:
        raise HTTPException(404, "Rule not found")
    ok = bool(r.last_preview and r.last_preview.get("ok_to_activate"))
    if not ok and not body.force:
        raise HTTPException(409, "Run a preview first; it must pass the GOV-06 checks (or force with a reason)")
    if not ok and not body.reason:
        raise HTTPException(400, "A reason is required to force activation")
    r.status, r.activated_at, r.activated_by, r.activation_reason = "active", utcnow(), user.email, (body.reason if not ok else None)
    session.commit()
    return _rule_out(r)


@router.post("/rules/{rule_id}/run")
def run_rule(rule_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
             user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    r = session.get(Rule, rule_id)
    if r is None:
        raise HTTPException(404, "Rule not found")
    if r.status != "active":
        raise HTTPException(409, "Activate the rule first")
    res = run_rules(session, meta, "manual", only_rule=r, user_email=user.email)
    session.commit()
    return {"affected": res[0]["affected"] if res else 0, "report": res[0]["report"] if res else {}}


@router.get("/rules/runs")
def rule_runs(rule_id: str | None = None, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    q = select(RuleRun).order_by(RuleRun.run_at.desc()).limit(200)
    if rule_id:
        q = q.where(RuleRun.rule_id == rule_id)
    return [{"id": x.id, "rule_id": x.rule_id, "run_at": x.run_at.isoformat(), "trigger": x.trigger, "affected": x.affected, "report": x.report,
             "change_set_id": x.change_set_id} for x in session.execute(q).scalars()]
