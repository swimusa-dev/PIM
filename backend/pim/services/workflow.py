"""DM-07 workflows (enrich and review steps, due dates, inbox, manager view, reject to an earlier step) and DM-12
carryover for repeat bodies and new colors."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.auth.identity import CurrentUser
from pim.models import (
    Comment,
    ProductEntity,
    ProductValue,
    ValueDraft,
    WorkflowDefinition,
    WorkflowItem,
    WorkflowStep,
)
from pim.models._common import utcnow
from pim.services.collab import notify
from pim.services.metadata import Metadata
from pim.services.values import typed_from_row

MAX_STEPS = 20


def _groups_approved(session: Session, meta: Metadata, ent: ProductEntity, group_codes: list[str]) -> bool:
    """DM-12: a step is skippable when every attribute of its groups that applies to this entity's level and family
    already holds an approved value (or Not applicable)."""
    if not group_codes:
        return False
    codes = [a.code for g in group_codes for a in (meta.groups[g].attributes if g in meta.groups else [])
             if a.level == ent.level and a.status != "deprecated" and not a.is_erp]
    if not codes:
        return False
    pvs = {pv.attribute_code: pv for pv in session.execute(select(ProductValue).where(ProductValue.entity_id == ent.id, ProductValue.channel_code == "",
                                                                                         ProductValue.attribute_code.in_(codes))).scalars()}
    for c in codes:
        pv = pvs.get(c)
        if pv is None or pv.approval_state != "approved" or (typed_from_row(pv).is_empty() and not pv.not_applicable):
            return False
    return True


def first_open_step(session: Session, meta: Metadata, wf: WorkflowDefinition, ent: ProductEntity, start_after: int = 0) -> WorkflowStep | None:
    for step in sorted(wf.steps, key=lambda s: s.position):
        if step.position <= start_after:
            continue
        if step.kind == "enrich" and _groups_approved(session, meta, ent, step.group_codes or []):
            continue
        return step
    return None


def start_workflow(session: Session, meta: Metadata, wf: WorkflowDefinition, ent: ProductEntity, by: str = "system") -> WorkflowItem | None:
    if not wf.steps:
        return None
    exists = session.execute(select(WorkflowItem).where(WorkflowItem.workflow_id == wf.id, WorkflowItem.entity_id == ent.id,
                                                        WorkflowItem.state == "open")).scalar_one_or_none()
    if exists:
        return None
    now = utcnow()
    step = first_open_step(session, meta, wf, ent)
    history = [{"at": now.isoformat(), "event": "started", "by": by}]
    if step is None:
        item = WorkflowItem(workflow_id=wf.id, entity_id=ent.id, current_step_id=None, state="done", history=history + [{"at": now.isoformat(), "event": "all steps already satisfied"}])
        session.add(item)
        return item
    skipped = [s.label for s in wf.steps if s.position < step.position]
    if skipped:
        history.append({"at": now.isoformat(), "event": "skipped already approved steps", "step": ", ".join(skipped)})
    item = WorkflowItem(workflow_id=wf.id, entity_id=ent.id, current_step_id=step.id, state="open",
                        due_at=now + timedelta(days=step.due_in_days), assigned_role=step.role_code, history=history)
    session.add(item)
    session.flush()
    return item


def _step(session: Session, item: WorkflowItem) -> WorkflowStep | None:
    return session.get(WorkflowStep, item.current_step_id) if item.current_step_id else None


def can_act(user: CurrentUser, item: WorkflowItem, step: WorkflowStep | None) -> bool:
    if user.can("admin_metadata"):
        return True
    if item.assigned_email and item.assigned_email == user.email:
        return True
    return bool(step and step.role_code in user.roles)


def advance(session: Session, meta: Metadata, user: CurrentUser, item: WorkflowItem, comment: str | None = None) -> WorkflowItem:
    step = _step(session, item)
    if item.state != "open" or step is None:
        raise ValueError("Item is not open")
    if not can_act(user, item, step):
        raise PermissionError("You are not assigned to this step")
    wf = session.get(WorkflowDefinition, item.workflow_id)
    ent = session.get(ProductEntity, item.entity_id)
    now = utcnow()
    item.history = [*item.history, {"at": now.isoformat(), "event": "completed", "step": step.label, "by": user.email, "comment": comment}]
    nxt = first_open_step(session, meta, wf, ent, start_after=step.position)
    if nxt is None:
        item.state, item.current_step_id, item.due_at, item.assigned_role, item.assigned_email = "done", None, None, None, None
        item.history = [*item.history, {"at": now.isoformat(), "event": "done"}]
    else:
        item.current_step_id, item.due_at, item.assigned_role, item.assigned_email = nxt.id, now + timedelta(days=nxt.due_in_days), nxt.role_code, None
    return item


def reject(session: Session, meta: Metadata, user: CurrentUser, item: WorkflowItem, to_step_id: str, comment: str,
           attribute_comments: list[dict] | None = None) -> WorkflowItem:
    step = _step(session, item)
    if item.state != "open" or step is None:
        raise ValueError("Item is not open")
    if not can_act(user, item, step):
        raise PermissionError("You are not assigned to this step")
    target = session.get(WorkflowStep, to_step_id)
    if target is None or target.workflow_id != item.workflow_id or target.position >= step.position:
        raise ValueError("Reject target must be an earlier step of the same workflow")
    now = utcnow()
    item.history = [*item.history, {"at": now.isoformat(), "event": "rejected", "step": step.label, "by": user.email, "comment": comment,
                                    "to_step": target.label}]
    prev_assignee = next((h.get("by") for h in reversed(item.history) if h.get("event") == "completed" and h.get("step") == target.label), None)
    item.current_step_id, item.due_at, item.assigned_role, item.assigned_email = target.id, now + timedelta(days=target.due_in_days), target.role_code, prev_assignee
    ent = session.get(ProductEntity, item.entity_id)
    session.add(Comment(entity_id=item.entity_id, author=user.email, body=f"Rejected back to {target.label}: {comment}",
                        context={"workflow_item_id": item.id, "from_step": step.label, "to_step": target.label}))
    for ac in attribute_comments or []:
        session.add(Comment(entity_id=item.entity_id, attribute_code=ac.get("attribute_code"), author=user.email, body=ac.get("comment", ""),
                            context={"workflow_item_id": item.id}))
    if prev_assignee:
        notify(session, prev_assignee, "workflow", f"{ent.label if ent else 'Product'} was sent back to {target.label}", comment, f"/products/{item.entity_id}")
    return item


def inbox(session: Session, user: CurrentUser, scope: str = "mine", overdue_only: bool = False) -> list[WorkflowItem]:
    q = select(WorkflowItem).where(WorkflowItem.state == "open")
    if scope == "mine":
        q = q.where((WorkflowItem.assigned_email == user.email) | ((WorkflowItem.assigned_email.is_(None)) & (WorkflowItem.assigned_role.in_(user.roles or ["-"]))))
    elif scope == "role":
        q = q.where(WorkflowItem.assigned_role.in_(user.roles or ["-"]))
    if overdue_only:
        q = q.where(WorkflowItem.due_at < utcnow())
    return session.execute(q.order_by(WorkflowItem.due_at.asc().nullslast())).scalars().all()


def manager_summary(session: Session) -> dict:
    now = utcnow()
    items = session.execute(select(WorkflowItem).where(WorkflowItem.state == "open")).scalars().all()
    steps = {s.id: s for s in session.execute(select(WorkflowStep)).scalars()}
    wfs = {w.id: w for w in session.execute(select(WorkflowDefinition)).scalars()}
    by_step: dict[tuple[str, str], dict] = {}
    buckets = {"0-2": 0, "3-7": 0, "8-14": 0, "15+": 0}
    for it in items:
        st = steps.get(it.current_step_id or "")
        wf = wfs.get(it.workflow_id)
        key = (wf.code if wf else "?", st.label if st else "?")
        row = by_step.setdefault(key, {"workflow_code": key[0], "step_label": key[1], "open": 0, "overdue": 0, "oldest_days": 0})
        row["open"] += 1
        if it.due_at and it.due_at < now:
            row["overdue"] += 1
        age = (now - it.created_at).days if it.created_at else 0
        row["oldest_days"] = max(row["oldest_days"], age)
        buckets["0-2" if age <= 2 else "3-7" if age <= 7 else "8-14" if age <= 14 else "15+"] += 1
    return {"by_step": sorted(by_step.values(), key=lambda r: (-r["overdue"], -r["open"])),
            "by_age": [{"bucket": k, "count": v} for k, v in buckets.items()]}


def item_out(session: Session, item: WorkflowItem) -> dict:
    step = _step(session, item)
    wf = session.get(WorkflowDefinition, item.workflow_id)
    ent = session.get(ProductEntity, item.entity_id)
    now = utcnow()
    return {"id": item.id, "workflow_code": wf.code if wf else None, "workflow_label": wf.label if wf else None, "entity_id": item.entity_id,
            "entity_label": ent.label if ent else item.entity_id,
            "step": {"id": step.id, "position": step.position, "label": step.label, "kind": step.kind, "role_code": step.role_code,
                     "group_codes": step.group_codes or [], "channel_codes": step.channel_codes or []} if step else None,
            "steps_total": len(wf.steps) if wf else 0, "state": item.state, "due_at": item.due_at.isoformat() if item.due_at else None,
            "overdue": bool(item.due_at and item.due_at < now and item.state == "open"), "assigned_role": item.assigned_role,
            "assigned_email": item.assigned_email, "history": item.history or [], "created_at": item.created_at.isoformat()}


# ---- DM-12 carryover -------------------------------------------------------------------------------------------
def siblings(session: Session, meta: Metadata, ent: ProductEntity) -> list[dict]:
    if ent.level != "style_color" or not ent.parent_id:
        return []
    out = []
    for sib in session.execute(select(ProductEntity).where(ProductEntity.parent_id == ent.parent_id, ProductEntity.id != ent.id)).scalars():
        pvs = session.execute(select(ProductValue).where(ProductValue.entity_id == sib.id, ProductValue.channel_code == "",
                                                         ProductValue.approval_state == "approved", ProductValue.source_type != "erp")).scalars().all()
        pvs = [p for p in pvs if not typed_from_row(p).is_empty() or p.not_applicable]
        out.append({"entity_id": sib.id, "label": sib.label, "color_code": sib.color_code, "approved_values": len(pvs),
                    "last_approved_at": max((p.set_at for p in pvs), default=None).isoformat() if pvs else None,
                    "attribute_codes": [p.attribute_code for p in pvs]})
    return sorted(out, key=lambda s: s["approved_values"], reverse=True)


def carryover(session: Session, meta: Metadata, user: CurrentUser, ent: ProductEntity, from_entity: ProductEntity,
              attribute_codes: list[str] | None = None) -> int:
    """Copy the sibling's most recent approved style-color-level values as drafts on the new color."""
    if ent.level != "style_color" or from_entity.parent_id != ent.parent_id:
        raise ValueError("Carryover works between colors of the same style")
    n = 0
    for pv in session.execute(select(ProductValue).where(ProductValue.entity_id == from_entity.id, ProductValue.channel_code == "",
                                                         ProductValue.approval_state == "approved")).scalars():
        attr = meta.attributes.get(pv.attribute_code)
        if attr is None or attr.is_erp or attr.level != "style_color" or (attribute_codes and pv.attribute_code not in attribute_codes):
            continue
        if not user.can_edit_group(attr.group_code):
            continue
        if typed_from_row(pv).is_empty() and not pv.not_applicable:
            continue
        existing = session.execute(select(ProductValue).where(ProductValue.entity_id == ent.id, ProductValue.attribute_code == pv.attribute_code,
                                                              ProductValue.channel_code == "")).scalar_one_or_none()
        if existing is not None and not (typed_from_row(existing).is_empty() and not existing.not_applicable):
            continue  # never overwrite a value the new color already has
        open_draft = session.execute(select(ValueDraft).where(ValueDraft.entity_id == ent.id, ValueDraft.attribute_code == pv.attribute_code,
                                                              ValueDraft.channel_code == "", ValueDraft.state.in_(["draft", "proposed"]))).scalars().first()
        proposed = {"value": typed_from_row(pv).as_python(), "not_applicable": pv.not_applicable, "carried_from": from_entity.id}
        if open_draft:
            open_draft.proposed, open_draft.submitted_by, open_draft.submitted_at = proposed, user.email, utcnow()
        else:
            session.add(ValueDraft(entity_level=ent.level, entity_id=ent.id, attribute_code=pv.attribute_code, channel_code="", proposed=proposed,
                                   source_type="user", ai_generated=pv.ai_generated, submitted_by=user.email, state="draft"))
        n += 1
    return n
