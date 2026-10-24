"""Change-set rollback shared by imports (IMP-07), bulk actions (DM-04), and rules (GOV-02).

A change set is rolled back as a unit: each value changed by the set is restored to its prior value unless a later
change touched the same value, in which case it is listed for manual handling."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.auth.identity import CurrentUser
from pim.models import ChangeSet, ProductEntity, ProductValue, ValueHistory
from pim.models._common import utcnow
from pim.services.metadata import Metadata
from pim.services.readiness import refresh_snapshots
from pim.services.values import NA_SENTINEL, clear_value, new_change_set, set_value


def rollback_change_set(session: Session, meta: Metadata, user: CurrentUser, change_set_id: str,
                        created_entity_ids: list[str] | None = None) -> dict:
    cs = session.get(ChangeSet, change_set_id)
    if cs is None:
        raise ValueError("Change set not found")
    if cs.rolled_back_at is not None:
        raise ValueError("Change set already rolled back")
    undo = new_change_set(session, "rollback", user.email, f"rollback of {change_set_id}", source_ref=change_set_id)
    hist = session.execute(select(ValueHistory).where(ValueHistory.change_set_id == change_set_id)
                           .order_by(ValueHistory.set_at.desc())).scalars().all()
    restored, manual = 0, []
    touched: dict[str, ProductEntity] = {}
    seen: set[tuple[str, str, str]] = set()
    for h in hist:
        key = (h.entity_id, h.attribute_code, h.channel_code or "")
        if key in seen:
            continue  # several writes in the set; the earliest old_value is restored below (we iterate newest first)
        entity = session.get(ProductEntity, h.entity_id)
        attr = meta.attributes.get(h.attribute_code)
        if entity is None or attr is None:
            continue
        pv = session.execute(select(ProductValue).where(ProductValue.entity_id == h.entity_id, ProductValue.attribute_code == h.attribute_code,
                                                        ProductValue.channel_code == (h.channel_code or ""))).scalar_one_or_none()
        latest_version = max((x.version for x in hist if (x.entity_id, x.attribute_code, x.channel_code or "") == key), default=h.version)
        if pv is not None and pv.version != latest_version:
            manual.append({"entity_id": entity.id, "label": entity.label, "attribute_code": attr.code,
                           "reason": "a later change touched this value"})
            seen.add(key)
            continue
        earliest = min((x for x in hist if (x.entity_id, x.attribute_code, x.channel_code or "") == key), key=lambda x: x.version)
        old = earliest.old_value
        if old is None:
            res = clear_value(session, meta, user, entity, attr, h.channel_code or None, undo) if pv is not None else None
            if res is not None and res.outcome == "rejected":
                manual.append({"entity_id": entity.id, "label": entity.label, "attribute_code": attr.code, "reason": res.message})
        else:
            raw = NA_SENTINEL if old.get("not_applicable") else old.get("value")
            res = set_value(session, meta, user, entity, attr, raw, channel_code=h.channel_code or None, source_type=old.get("source_type", "user"),
                            source_ref=f"rollback:{change_set_id}", change_set=undo, force=True,
                            approval_state=old.get("approval_state", "approved"), ai_generated=bool(old.get("ai_generated")))
            if res.outcome == "rejected":
                manual.append({"entity_id": entity.id, "label": entity.label, "attribute_code": attr.code, "reason": res.message})
                seen.add(key)
                continue
        restored += 1
        touched[entity.id] = entity
        seen.add(key)
    # entities created by the set and untouched since are removed, children before parents
    session.flush()
    removed = 0
    created = [e for e in (session.get(ProductEntity, i) for i in (created_entity_ids or [])) if e is not None]
    from pim.services.metadata import LEVEL_ORDER

    deleted: set[str] = set()
    for ent in sorted(created, key=lambda e: -LEVEL_ORDER.get(e.level, 0)):
        later = session.execute(select(ValueHistory.id).where(ValueHistory.entity_id == ent.id,
                                                              ValueHistory.change_set_id.notin_([change_set_id, undo.id]))).first()
        kids = [k for (k,) in session.execute(select(ProductEntity.id).where(ProductEntity.parent_id == ent.id)) if k not in deleted]
        if later or kids:
            manual.append({"entity_id": ent.id, "label": ent.label, "attribute_code": None, "reason": "created by this batch but changed or extended since"})
            continue
        for pv in session.execute(select(ProductValue).where(ProductValue.entity_id == ent.id)).scalars():
            session.delete(pv)
        session.delete(ent)
        deleted.add(ent.id)
        removed += 1
    session.flush()
    cs.rolled_back_at = utcnow()
    session.flush()
    refresh_snapshots(session, meta, [e for e in touched.values() if e.id not in deleted])
    return {"restored": restored, "removed_entities": removed, "manual": manual, "undo_change_set_id": undo.id}
