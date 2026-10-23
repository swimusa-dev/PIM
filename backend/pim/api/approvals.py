"""DM-08 approval queue."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.api.schemas import DecideBody
from pim.models import ProductEntity, ProductValue, ValueDraft
from pim.services.readiness import refresh_snapshots
from pim.services.values import decide_drafts, typed_from_row

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("")
def queue(group: str | None = None, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
          user: CurrentUser = Depends(get_current_user)) -> dict:
    drafts = session.execute(select(ValueDraft).where(ValueDraft.state.in_(["draft", "proposed"]))
                             .order_by(ValueDraft.submitted_by, ValueDraft.submitted_at)).scalars().all()
    groups: dict[str, list[dict]] = {}
    ents = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_({d.entity_id for d in drafts}))).scalars()} if drafts else {}
    for d in drafts:
        attr = meta.attributes.get(d.attribute_code)
        if attr is None or (group and attr.group_code != group) or not user.can_view_group(attr.group_code):
            continue
        ent = ents.get(d.entity_id)
        cur = session.execute(select(ProductValue).where(ProductValue.entity_id == d.entity_id,
                                                         ProductValue.attribute_code == d.attribute_code,
                                                         ProductValue.channel_code == d.channel_code)).scalar_one_or_none()
        groups.setdefault(d.submitted_by, []).append({
            "draft_id": d.id, "entity_id": d.entity_id, "label": ent.label if ent else d.entity_id,
            "attribute_code": d.attribute_code, "attribute_label": attr.label, "group_code": attr.group_code,
            "channel_code": d.channel_code or None, "current": typed_from_row(cur).as_python() if cur else None,
            "proposed": d.proposed.get("value"), "not_applicable": d.proposed.get("not_applicable", False),
            "ai_generated": d.ai_generated, "set_at": d.submitted_at.isoformat(),
            "can_approve": user.can_approve_group(attr.group_code),
        })
    return {"groups": [{"submitter": s, "items": items} for s, items in groups.items()]}


@router.post("/decide")
def decide(body: DecideBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
           user: CurrentUser = Depends(get_current_user)) -> dict:
    if body.decision not in ("approve", "reject"):
        return {"results": [], "error": "decision must be approve or reject"}
    results = decide_drafts(session, meta, user, body.draft_ids, body.decision, body.comment)
    ids = {d.entity_id for d in session.execute(select(ValueDraft).where(ValueDraft.id.in_(body.draft_ids))).scalars()}
    ents = session.execute(select(ProductEntity).where(ProductEntity.id.in_(ids))).scalars().all()
    refresh_snapshots(session, meta, ents)
    session.commit()
    return {"results": [{"attribute_code": r.attribute_code, "outcome": r.outcome, "message": r.message} for r in results]}
