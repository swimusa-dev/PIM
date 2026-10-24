"""DM-07 workflows, DM-12 carryover, DM-09 comments and notifications, DM-06 compare."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.api.serializers import attribute_out
from pim.auth.identity import require_permission
from pim.models import Comment, Notification, ProductEntity, WorkflowDefinition, WorkflowItem, WorkflowStep
from pim.models._common import utcnow
from pim.services import workflow as wf_service
from pim.services.collab import add_comment, comments_for, mark_read, notify
from pim.services.grid import row_dict
from pim.services.readiness import refresh_snapshots
from pim.services.values import NA_SENTINEL, new_change_set, resolve_cells, set_value

router = APIRouter(prefix="/api", tags=["workflows", "comments"])


class WorkflowBody(BaseModel):
    label: str
    enabled: bool = True
    entry_rule: dict = {}
    steps: list[dict]


class AdvanceBody(BaseModel):
    comment: str | None = None


class RejectBody(BaseModel):
    to_step_id: str
    comment: str
    attribute_comments: list[dict] | None = None


class AssignBody(BaseModel):
    email: str


class StartBody(BaseModel):
    workflow_code: str
    entity_ids: list[str]


class CarryoverBody(BaseModel):
    from_entity_id: str
    attribute_codes: list[str] | None = None


class CommentBody(BaseModel):
    body: str
    attribute_code: str | None = None


class ReadBody(BaseModel):
    ids: list[str] | None = None


class CopyFromBody(BaseModel):
    from_entity_id: str
    attribute_codes: list[str]
    channel_code: str | None = None


def _wf_out(w: WorkflowDefinition) -> dict:
    return {"code": w.code, "label": w.label, "enabled": w.enabled, "entry_rule": w.entry_rule or {},
            "steps": [{"id": s.id, "position": s.position, "label": s.label, "kind": s.kind, "role_code": s.role_code, "group_codes": s.group_codes or [],
                       "channel_codes": s.channel_codes or [], "due_in_days": s.due_in_days} for s in sorted(w.steps, key=lambda s: s.position)]}


def _item_or_404(session: Session, item_id: str) -> WorkflowItem:
    it = session.get(WorkflowItem, item_id)
    if it is None:
        raise HTTPException(404, "Workflow item not found")
    return it


def _ent_or_404(session: Session, entity_id: str, user: CurrentUser) -> ProductEntity:
    e = session.get(ProductEntity, entity_id)
    if e is None or not user.in_brand_scope(e.brand_scopes or []):
        raise HTTPException(404, "Product not found")
    return e


# ---- definitions ----------------------------------------------------------------------------------------------
@router.get("/workflows")
def list_workflows(session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    return [_wf_out(w) for w in session.execute(select(WorkflowDefinition).order_by(WorkflowDefinition.label)).scalars()]


@router.put("/workflows/{code}")
def upsert_workflow(code: str, body: WorkflowBody, session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    if len(body.steps) > wf_service.MAX_STEPS:
        raise HTTPException(400, f"At most {wf_service.MAX_STEPS} steps")
    w = session.execute(select(WorkflowDefinition).where(WorkflowDefinition.code == code)).scalar_one_or_none()
    if w is None:
        w = WorkflowDefinition(code=code, label=body.label, enabled=body.enabled, entry_rule=body.entry_rule)
        session.add(w)
        session.flush()
    else:
        w.label, w.enabled, w.entry_rule = body.label, body.enabled, body.entry_rule
    existing = {s.id: s for s in w.steps}
    keep = []
    for i, st in enumerate(body.steps, start=1):
        s = existing.get(st.get("id") or "")
        data = {"position": int(st.get("position", i)), "label": st["label"], "kind": st.get("kind", "enrich"), "role_code": st["role_code"],
                "group_codes": st.get("group_codes", []), "channel_codes": st.get("channel_codes", []), "due_in_days": int(st.get("due_in_days", 5))}
        if s is None:
            s = WorkflowStep(workflow_id=w.id, **data)
            w.steps.append(s)
        else:
            for k, v in data.items():
                setattr(s, k, v)
        keep.append(s)
    for s in list(w.steps):
        if s not in keep:
            w.steps.remove(s)
    session.commit()
    return _wf_out(w)


# ---- inbox and items --------------------------------------------------------------------------------------
@router.get("/workflows/inbox")
def inbox(scope: str = "mine", overdue: bool = False, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    items = wf_service.inbox(session, user, scope, overdue)
    return {"rows": [wf_service.item_out(session, it) for it in items], "total": len(items)}


@router.get("/workflows/manager")
def manager(session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    return wf_service.manager_summary(session)


@router.post("/workflows/items/{item_id}/advance")
def advance(item_id: str, body: AdvanceBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
            user: CurrentUser = Depends(get_current_user)) -> dict:
    it = _item_or_404(session, item_id)
    try:
        wf_service.advance(session, meta, user, it, body.comment)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return wf_service.item_out(session, it)


@router.post("/workflows/items/{item_id}/reject")
def reject(item_id: str, body: RejectBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
           user: CurrentUser = Depends(get_current_user)) -> dict:
    it = _item_or_404(session, item_id)
    try:
        wf_service.reject(session, meta, user, it, body.to_step_id, body.comment, body.attribute_comments)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return wf_service.item_out(session, it)


@router.post("/workflows/items/{item_id}/assign")
def assign(item_id: str, body: AssignBody, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    it = _item_or_404(session, item_id)
    it.assigned_email = body.email.lower()
    it.history = [*it.history, {"at": utcnow().isoformat(), "event": "assigned", "by": user.email, "comment": body.email}]

    ent = session.get(ProductEntity, it.entity_id)
    notify(session, body.email, "workflow", f"You were assigned {ent.label if ent else 'a product'}", None, f"/products/{it.entity_id}")
    session.commit()
    return wf_service.item_out(session, it)


@router.post("/workflows/items/{item_id}/cancel")
def cancel(item_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    it = _item_or_404(session, item_id)
    it.state = "cancelled"
    session.commit()
    return wf_service.item_out(session, it)


@router.post("/workflows/start")
def start(body: StartBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(require_permission("bulk_edit"))) -> dict:
    wf = session.execute(select(WorkflowDefinition).where(WorkflowDefinition.code == body.workflow_code)).scalar_one_or_none()
    if wf is None:
        raise HTTPException(404, "Workflow not found")
    started = 0
    for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_(body.entity_ids))).scalars():
        if wf_service.start_workflow(session, meta, wf, e, by=user.email):
            started += 1
    session.commit()
    return {"started": started}


@router.get("/products/{entity_id}/workflow")
def product_workflow(entity_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    _ent_or_404(session, entity_id, user)
    items = session.execute(select(WorkflowItem).where(WorkflowItem.entity_id == entity_id).order_by(WorkflowItem.created_at.desc())).scalars().all()
    return [wf_service.item_out(session, it) for it in items]


# ---- carryover (DM-12) -------------------------------------------------------------------------------------
@router.get("/products/{entity_id}/carryover")
def carryover_info(entity_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = _ent_or_404(session, entity_id, user)
    sibs = wf_service.siblings(session, meta, ent)
    skippable = []
    for wf in session.execute(select(WorkflowDefinition)).scalars():
        for st in wf.steps:
            if st.kind == "enrich" and wf_service._groups_approved(session, meta, ent, st.group_codes or []):  # noqa: SLF001
                skippable.append(st.label)
    return {"siblings": sibs, "steps_skippable": skippable}


@router.post("/products/{entity_id}/carryover")
def carryover(entity_id: str, body: CarryoverBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
              user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = _ent_or_404(session, entity_id, user)
    src = _ent_or_404(session, body.from_entity_id, user)
    try:
        n = wf_service.carryover(session, meta, user, ent, src, body.attribute_codes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return {"drafts": n}


# ---- comments and notifications (DM-09) ----------------------------------------------------------------------
def _comment_out(c: Comment) -> dict:
    return {"id": c.id, "entity_id": c.entity_id, "attribute_code": c.attribute_code, "author": c.author, "body": c.body, "mentions": c.mentions or [],
            "created_at": c.created_at.isoformat(), "resolved": c.resolved, "context": c.context or {}}


@router.get("/products/{entity_id}/comments")
def list_comments(entity_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    ent = _ent_or_404(session, entity_id, user)
    return [_comment_out(c) for c in comments_for(session, ent)]


@router.post("/products/{entity_id}/comments")
def post_comment(entity_id: str, body: CommentBody, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = _ent_or_404(session, entity_id, user)
    if not body.body.strip():
        raise HTTPException(400, "Empty comment")
    c = add_comment(session, user.email, ent, body.body.strip(), body.attribute_code)
    session.commit()
    return _comment_out(c)


@router.post("/comments/{comment_id}/resolve")
def resolve_comment(comment_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    c = session.get(Comment, comment_id)
    if c is None:
        raise HTTPException(404, "Comment not found")
    c.resolved = not c.resolved
    session.commit()
    return _comment_out(c)


@router.get("/notifications")
def notifications(unread: bool = False, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    q = select(Notification).where(Notification.user_email == user.email)
    if unread:
        q = q.where(Notification.read_at.is_(None))
    rows = session.execute(q.order_by(Notification.created_at.desc()).limit(100)).scalars().all()
    unread_n = session.execute(select(func.count()).select_from(Notification).where(Notification.user_email == user.email, Notification.read_at.is_(None))).scalar_one()
    return {"rows": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "created_at": n.created_at.isoformat(),
                      "read_at": n.read_at.isoformat() if n.read_at else None} for n in rows], "unread": unread_n}


@router.post("/notifications/read")
def read_notifications(body: ReadBody, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    n = mark_read(session, user.email, body.ids)
    session.commit()
    return {"marked": n}


# ---- compare (DM-06) ----------------------------------------------------------------------------------------
@router.get("/products/compare")
def compare(a: str, b: str, channel: str | None = None, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
            user: CurrentUser = Depends(get_current_user)) -> dict:
    ea, eb = _ent_or_404(session, a, user), _ent_or_404(session, b, user)
    attrs = [x for x in meta.attributes_for_family(ea.family_code) if x.level in ("style", "style_color", "sku")]
    codes = [x.code for x in attrs]
    cells = resolve_cells(session, meta, user, [ea, eb], codes, channel)
    return {"attributes": [attribute_out(x) for x in attrs], "a": row_dict(session, meta, ea, cells.get(ea.id, {})), "b": row_dict(session, meta, eb, cells.get(eb.id, {}))}


@router.post("/products/{entity_id}/copy-from")
def copy_from(entity_id: str, body: CopyFromBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
              user: CurrentUser = Depends(get_current_user)) -> dict:
    target, src = _ent_or_404(session, entity_id, user), _ent_or_404(session, body.from_entity_id, user)
    cells = resolve_cells(session, meta, user, [src], body.attribute_codes, include_drafts=False).get(src.id, {})
    cs = new_change_set(session, "edit", user.email, f"copy from {src.label}")
    results = []
    for code in body.attribute_codes:
        attr = meta.attributes.get(code)
        cell = cells.get(code)
        if attr is None or cell is None:
            continue
        raw = NA_SENTINEL if cell.get("not_applicable") else cell.get("value")
        res = set_value(session, meta, user, target, attr, raw, channel_code=body.channel_code, change_set=cs)
        results.append({"attribute_code": code, "outcome": res.outcome, "message": res.message})
    refresh_snapshots(session, meta, [target])
    session.commit()
    return {"results": results}
