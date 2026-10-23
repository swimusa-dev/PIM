"""DM-11 reference entities (Print, Fabric, Model profile)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.api.schemas import ReferenceBody
from pim.models import ProductEntity, ProductValue, ReferenceEntity
from pim.services.readiness import refresh_snapshots
from pim.services.values import cell, load_values, new_change_set, set_value

router = APIRouter(prefix="/api/reference-entities", tags=["reference"])


def _ref_out(session: Session, meta: Metadata, user: CurrentUser, r: ReferenceEntity, codes: list[str]) -> dict:
    vals = load_values(session, [r.id], codes).get(r.id, {})
    values = {}
    for c in codes:
        attr = meta.attributes[c]
        values[c] = cell(vals.get((c, "")), attr, read_only=not user.can_edit_group(attr.group_code),
                         reason=None if user.can_edit_group(attr.group_code) else "no_rights", meta=meta)
    linked = session.execute(select(func.count(func.distinct(ProductValue.entity_id))).where(ProductValue.value_ref == r.id)).scalar_one()
    return {"id": r.id, "type_code": r.type_code, "code": r.code, "label": r.label, "values": values,
            "certificate_refs": r.certificate_refs or [], "linked_products": linked}


@router.get("/{type_code}")
def list_refs(type_code: str, q: str | None = None, page: int = 1, page_size: int = 50, session: Session = Depends(get_session),
              meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    if type_code not in meta.reference_types:
        raise HTTPException(404, "Unknown reference type")
    stmt = select(ReferenceEntity).where(ReferenceEntity.type_code == type_code)
    if q:
        stmt = stmt.where(ReferenceEntity.label.ilike(f"%{q}%"))
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = session.execute(stmt.order_by(ReferenceEntity.label).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    codes = [a.code for a in meta.attributes_for_level(f"ref:{type_code}")]
    return {"rows": [_ref_out(session, meta, user, r, codes) for r in rows], "total": total}


@router.post("/{type_code}")
def create_ref(type_code: str, body: ReferenceBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
               user: CurrentUser = Depends(get_current_user)) -> dict:
    rt = meta.reference_types.get(type_code)
    if rt is None:
        raise HTTPException(404, "Unknown reference type")
    label = body.label or str(body.values.get(rt.label_attribute) or "")
    if not label:
        raise HTTPException(400, f"{rt.label_attribute} is required")
    r = ReferenceEntity(type_code=type_code, code=body.code or label.lower().replace(" ", "_"), label=label,
                        certificate_refs=body.certificate_refs or [])
    session.add(r)
    session.flush()
    _write_values(session, meta, user, r, body.values)
    session.commit()
    return _ref_out(session, meta, user, r, [a.code for a in meta.attributes_for_level(f"ref:{type_code}")])


def _write_values(session: Session, meta: Metadata, user: CurrentUser, r: ReferenceEntity, values: dict) -> list[dict]:
    cs = new_change_set(session, "edit", user.email, f"edit reference {r.label}")
    pseudo = ProductEntity(id=r.id, level=f"ref:{r.type_code}", style_number=r.code, label=r.label)
    out = []
    for code, raw in values.items():
        attr = meta.attributes.get(code)
        if attr is None:
            continue
        res = set_value(session, meta, user, pseudo, attr, raw, change_set=cs)
        out.append({"attribute_code": code, "outcome": res.outcome, "message": res.message})
    rt = meta.reference_types[r.type_code]
    if rt.label_attribute in values and values[rt.label_attribute]:
        r.label = str(values[rt.label_attribute])
    return out


@router.get("/{type_code}/{ref_id}")
def get_ref(type_code: str, ref_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
            user: CurrentUser = Depends(get_current_user)) -> dict:
    r = session.get(ReferenceEntity, ref_id)
    if r is None or r.type_code != type_code:
        raise HTTPException(404, "Not found")
    return _ref_out(session, meta, user, r, [a.code for a in meta.attributes_for_level(f"ref:{type_code}")])


@router.put("/{type_code}/{ref_id}")
def update_ref(type_code: str, ref_id: str, body: ReferenceBody, confirm: bool = False, session: Session = Depends(get_session),
               meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    r = session.get(ReferenceEntity, ref_id)
    if r is None or r.type_code != type_code:
        raise HTTPException(404, "Not found")
    linked_ids = [row[0] for row in session.execute(select(ProductValue.entity_id).where(ProductValue.value_ref == r.id).distinct())]
    linked = session.execute(select(ProductEntity).where(ProductEntity.id.in_(linked_ids))).scalars().all() if linked_ids else []
    channels = sorted({c for c in meta.channels if any(k.startswith(tuple(a.code for a in meta.attributes.values() if a.reference_type_code == type_code)) for k in (meta.channels[c].attribute_mapping or {}))})
    impact = {"products": len(linked), "channels": channels}
    if not confirm:
        return {"impact": impact, "saved": False}
    results = _write_values(session, meta, user, r, body.values)
    if body.certificate_refs is not None:
        r.certificate_refs = body.certificate_refs
    if body.label:
        r.label = body.label
    refresh_snapshots(session, meta, linked)
    session.commit()
    return {"impact": impact, "saved": True, "results": results,
            **_ref_out(session, meta, user, r, [a.code for a in meta.attributes_for_level(f"ref:{type_code}")])}
