"""DM-13 relationship types and product relationships, GOV-02 change sets and whole-product restore."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.auth.identity import require_permission
from pim.models import ChangeSet, ProductEntity, ProductRelationship, RelationshipType
from pim.services import relationships as rel
from pim.services.changesets import rollback_change_set
from pim.services.history import change_set_out, list_change_sets, restore_to
from pim.services.metadata import invalidate
from pim.services.readiness import refresh_snapshots

router = APIRouter(prefix="/api", tags=["relationships"])


class RelationshipBody(BaseModel):
    type_code: str
    targets: list[str] = []  # entity ids, style numbers or style-colors
    paste: str | None = None  # comma-separated list as in the request sheet
    quantity: int | None = None


class RelationshipTypeBody(BaseModel):
    label: str | None = None
    direction: str | None = None
    level: str | None = None
    allows_quantity: bool | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    help_text: str | None = None


class RestoreToBody(BaseModel):
    at: datetime
    attribute_codes: list[str] | None = None


def _type_out(t: RelationshipType) -> dict:
    return {"code": t.code, "label": t.label, "direction": t.direction, "level": t.level, "allows_quantity": t.allows_quantity,
            "enabled": t.enabled, "sort_order": t.sort_order, "help_text": t.help_text}


def _entity(session: Session, entity_id: str, user: CurrentUser) -> ProductEntity:
    ent = session.get(ProductEntity, entity_id)
    if ent is None or not user.in_brand_scope(ent.brand_scopes or []):
        raise HTTPException(404, "Product not found")
    return ent


@router.get("/relationship-types")
def relationship_types(include_disabled: bool = False, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    return [_type_out(t) for t in rel.types(session, include_disabled=include_disabled)]


@router.put("/relationship-types/{code}")
def put_relationship_type(code: str, body: RelationshipTypeBody, session: Session = Depends(get_session),
                          user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    t = session.get(RelationshipType, code)
    if t is None:
        t = RelationshipType(code=code, label=body.label or code)
        session.add(t)
    if body.direction is not None and body.direction not in ("one_way", "two_way"):
        raise HTTPException(400, "direction must be one_way or two_way")
    if body.level is not None and body.level not in ("style", "style_color"):
        raise HTTPException(400, "level must be style or style_color")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(t, k, v)
    session.commit()
    invalidate()
    return _type_out(t)


@router.get("/products/{entity_id}/relationships")
def product_relationships(entity_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = _entity(session, entity_id, user)
    return {"rows": rel.links_for(session, ent)}


@router.post("/products/{entity_id}/relationships")
def add_relationships(entity_id: str, body: RelationshipBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                      user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = _entity(session, entity_id, user)
    if not user.can("edit_relationships") and not user.can("admin_metadata") and not user.can_edit_group("style_details"):
        raise HTTPException(403, "No rights to edit relationships")
    targets = list(body.targets) + rel.parse_targets(body.paste or "")
    if not targets:
        raise HTTPException(400, "Give at least one target product")
    try:
        res = rel.add(session, user, ent, body.type_code, targets, body.quantity)
    except rel.RelationshipError as exc:
        raise HTTPException(400, str(exc)) from exc
    refresh_snapshots(session, meta, [ent])
    session.commit()
    return {"created": len(res.created), "skipped": res.skipped, "rows": rel.links_for(session, ent)}


@router.delete("/relationships/{relationship_id}")
def delete_relationship(relationship_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                        user: CurrentUser = Depends(get_current_user)) -> dict:
    r = session.get(ProductRelationship, relationship_id)
    if r is None:
        raise HTTPException(404, "Relationship not found")
    ent = _entity(session, r.from_entity_id, user)
    if not user.can("edit_relationships") and not user.can("admin_metadata") and not user.can_edit_group("style_details"):
        raise HTTPException(403, "No rights to edit relationships")
    n = rel.remove(session, r)
    refresh_snapshots(session, meta, [ent])
    session.commit()
    return {"deleted": n}


# ---- GOV-02 ----------------------------------------------------------------------------------------
@router.post("/products/{entity_id}/restore-to")
def restore_product_to(entity_id: str, body: RestoreToBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                       user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = _entity(session, entity_id, user)
    res = restore_to(session, meta, user, ent, body.at, body.attribute_codes)
    refresh_snapshots(session, meta, [ent])
    session.commit()
    return res


@router.get("/change-sets")
def change_sets(kind: str | None = None, entity_id: str | None = None, page: int = 1, page_size: int = 50,
                session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    if entity_id:
        _entity(session, entity_id, user)
    return list_change_sets(session, kind, entity_id, page, min(page_size, 200))


@router.get("/change-sets/{change_set_id}")
def change_set(change_set_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    cs = session.get(ChangeSet, change_set_id)
    if cs is None:
        raise HTTPException(404, "Change set not found")
    return change_set_out(cs)


@router.post("/change-sets/{change_set_id}/rollback")
def rollback(change_set_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
             user: CurrentUser = Depends(get_current_user)) -> dict:
    """Rolls a change set back as a unit (GOV-02). Values touched since are listed under `manual`, not reverted."""
    cs = session.get(ChangeSet, change_set_id)
    if cs is None:
        raise HTTPException(404, "Change set not found")
    if not (user.can("admin_metadata") or user.can("bulk_edit") or cs.created_by == user.email):
        raise HTTPException(403, "Only the author, a bulk editor or an admin can roll a change set back")
    try:
        res = rollback_change_set(session, meta, user, change_set_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return res
