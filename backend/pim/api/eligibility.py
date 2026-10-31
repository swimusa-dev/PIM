"""D-15: channel eligibility rules and brand scopes, edited in the app instead of the seed files."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.api.serializers import channel_out
from pim.models import BrandScope, Channel
from pim.models._common import utcnow
from pim.services import eligibility as svc
from pim.services.metadata import invalidate, load_metadata

router = APIRouter(prefix="/api/metadata", tags=["eligibility"])

CODE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


class EligibilityBody(BaseModel):
    eligibility: dict = {}


class ScopeBody(BaseModel):
    label: str
    enabled: bool = True
    rules: list = []


class RulesBody(BaseModel):
    rules: list = []


def _can_edit_channel(user: CurrentUser, code: str) -> bool:
    return user.can("admin_metadata") or (user.can("manage_channels") and user.channel_right(code, "edit_profile"))


def _scope_out(s: BrandScope, used: dict[str, list[str]]) -> dict:
    return {"code": s.code, "label": s.label, "enabled": s.enabled, "rules": s.rules or [], "used_by": used.get(s.code, [])}


def _validated(meta: Metadata, body: dict) -> dict:
    try:
        return svc.validate_eligibility(body, {s.code for s in meta.brand_scopes}, set(meta.option_codes("brand_classification")))
    except svc.EligibilityError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/eligibility-options")
def options(session: Session = Depends(get_session), meta: Metadata = Depends(get_meta)) -> dict:
    lst = meta.option_lists.get("brand_classification")
    labels = {v.code: v.label for v in (lst.values if lst else [])}
    return {
        "brand_scopes": [{"code": s.code, "label": s.label, "enabled": s.enabled} for s in meta.brand_scopes],
        "classifications": [{"code": c, "label": labels.get(c, c)} for c in meta.option_codes("brand_classification")],
        "lifecycle": list(svc.LIFECYCLES), "entity_types": list(svc.ENTITY_TYPES),
        "fields": list(svc.SCOPE_FIELDS), "ops": list(svc.SCOPE_OPS),
    }


@router.put("/channels/{code}/eligibility")
def save_eligibility(code: str, body: EligibilityBody, session: Session = Depends(get_session),
                     user: CurrentUser = Depends(get_current_user), meta: Metadata = Depends(get_meta)) -> dict:
    if not _can_edit_channel(user, code):
        raise HTTPException(403, "No right to edit this channel profile (RBAC-03)")
    ch = session.get(Channel, code)
    if ch is None:
        raise HTTPException(404, "Unknown channel")
    ch.eligibility = _validated(meta, body.eligibility)
    ch.version += 1
    session.commit()
    invalidate()
    return {"channel": channel_out(ch, load_metadata(session, force=True)), "recompute_needed": True}


@router.post("/channels/{code}/eligibility/preview")
def preview_eligibility(code: str, body: EligibilityBody, session: Session = Depends(get_session),
                        user: CurrentUser = Depends(get_current_user), meta: Metadata = Depends(get_meta)) -> dict:
    if not _can_edit_channel(user, code):
        raise HTTPException(403, "No right to edit this channel profile (RBAC-03)")
    ch = session.get(Channel, code)
    if ch is None:
        raise HTTPException(404, "Unknown channel")
    return svc.eligibility_impact(session, ch.eligibility or {}, _validated(meta, body.eligibility))


@router.get("/brand-scopes")
def list_scopes(session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    used = svc.referenced_scopes(session)
    return [_scope_out(s, used) for s in session.execute(select(BrandScope).order_by(BrandScope.code)).scalars()]


@router.put("/brand-scopes/{code}")
def save_scope(code: str, body: ScopeBody, session: Session = Depends(get_session),
               user: CurrentUser = Depends(get_current_user)) -> dict:
    if not user.can("admin_metadata"):
        raise HTTPException(403, "PIM Admin only")
    if not CODE.match(code):
        raise HTTPException(422, "The code is lower case letters, digits and underscores, starting with a letter")
    if not body.label.strip():
        raise HTTPException(422, "Give the scope a label")
    try:
        rules = svc.validate_scope_rules(body.rules)
    except svc.EligibilityError as exc:
        raise HTTPException(422, str(exc)) from exc
    scope = session.get(BrandScope, code)
    if scope is None:
        scope = BrandScope(code=code, label=body.label.strip(), rules=rules, enabled=body.enabled)
        session.add(scope)
    else:
        scope.label, scope.rules, scope.enabled = body.label.strip(), rules, body.enabled
    session.commit()
    invalidate()
    return {"scope": _scope_out(scope, svc.referenced_scopes(session)), "recompute_needed": True}


@router.delete("/brand-scopes/{code}")
def delete_scope(code: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    if not user.can("admin_metadata"):
        raise HTTPException(403, "PIM Admin only")
    scope = session.get(BrandScope, code)
    if scope is None:
        raise HTTPException(404, "Unknown brand scope")
    used = svc.referenced_scopes(session).get(code, [])
    if used:
        raise HTTPException(409, f"In use by {', '.join(used)}. Remove it there first, or disable it instead.")
    session.delete(scope)
    session.commit()
    invalidate()
    return {"deleted": code, "recompute_needed": True}


@router.post("/brand-scopes/preview")
def preview_scope(body: RulesBody, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    if not user.can("admin_metadata"):
        raise HTTPException(403, "PIM Admin only")
    try:
        rules = svc.validate_scope_rules(body.rules)
    except svc.EligibilityError as exc:
        raise HTTPException(422, str(exc)) from exc
    return svc.scope_matches(session, rules)


@router.post("/eligibility/recompute")
def recompute(session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
              user: CurrentUser = Depends(get_current_user)) -> dict:
    """Apply eligibility and brand scope changes to the products already loaded. A job when one is bound, inline otherwise."""
    if not user.can("admin_metadata"):
        raise HTTPException(403, "PIM Admin only")
    from pim.services.jobs import trigger_job

    job = trigger_job(session, "readiness", user.email, {"user": user.email})
    if job.databricks_run_id:
        session.commit()
        return {"status": "started", "job_run_id": job.id}
    result = svc.recompute_scopes_and_readiness(session)
    job.status, job.finished_at, job.report = "succeeded", utcnow(), result
    session.commit()
    return {"status": "done", **result}
