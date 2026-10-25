"""DM-13 product relationships: typed, directional, inherited from style to its colors, validated on save, checked
in readiness, and exposed to channel feeds as `related:<type>` (EXP-09).

Layer owns Shopify cross-sell data (D-09): nothing here writes a Shopify field. If ownership ever moves into the PIM
the Shopify channel profile flips those metafields from protected to mapped and this module is unchanged."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.auth.identity import CurrentUser
from pim.models import IdentifierAlias, ProductEntity, ProductRelationship, RelationshipType
from pim.normalization import normalize_identifier

LIST_SPLIT = re.compile(r"[,\n;]+")


class RelationshipError(ValueError):
    pass


@dataclass
class ResolvedTarget:
    token: str
    entity: ProductEntity | None
    error: str | None = None


@dataclass
class AddResult:
    created: list[ProductRelationship] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {token, reason}


def types(session: Session, include_disabled: bool = False) -> list[RelationshipType]:
    q = select(RelationshipType).order_by(RelationshipType.sort_order, RelationshipType.code)
    rows = session.execute(q).scalars().all()
    return rows if include_disabled else [r for r in rows if r.enabled]


def parse_targets(text: str) -> list[str]:
    """A pasted comma-separated list of style-colors as the request sheet writes them: "200809-FVP, 200809 ECB"."""
    return [t.strip() for t in LIST_SPLIT.split(text or "") if t.strip()]


def resolve_target(session: Session, token: str, level: str) -> ResolvedTarget:
    """A target is an entity id, a style number (style level) or a style-color in any known format (DM-01 aliases)."""
    ent = session.get(ProductEntity, token)
    if ent is None:
        alias_types = ["style", "gms", "vendor"] if level == "style" else ["style_color"]
        hit = session.execute(select(IdentifierAlias).where(IdentifierAlias.alias_type.in_(alias_types),
                                                            IdentifierAlias.normalized == normalize_identifier(token))).scalars().first()
        if hit is not None:
            ent = session.get(ProductEntity, hit.entity_id)
    if ent is None:
        return ResolvedTarget(token, None, "not found")
    if ent.level != level:
        return ResolvedTarget(token, ent, f"is a {ent.level.replace('_', ' ')}, this relationship links {level.replace('_', ' ')}s")
    if ent.lifecycle_status == "discontinued":
        return ResolvedTarget(token, ent, "is discontinued")
    return ResolvedTarget(token, ent)


def add(session: Session, user: CurrentUser, source: ProductEntity, type_code: str, targets: list[str],
        quantity: int | None = None) -> AddResult:
    rt = session.get(RelationshipType, type_code)
    if rt is None or not rt.enabled:
        raise RelationshipError(f"Unknown or disabled relationship type {type_code}")
    if source.level != rt.level:
        raise RelationshipError(f"{rt.label} links {rt.level.replace('_', ' ')}s; set it on the {rt.level.replace('_', ' ')}")
    if quantity is not None and not rt.allows_quantity:
        raise RelationshipError(f"{rt.label} does not take a quantity")
    out = AddResult()
    existing = {r.to_entity_id for r in session.execute(select(ProductRelationship).where(
        ProductRelationship.type_code == type_code, ProductRelationship.from_entity_id == source.id)).scalars()}
    for token in targets:
        res = resolve_target(session, token, rt.level)
        if res.error or res.entity is None:
            out.skipped.append({"token": token, "reason": res.error or "not found"})
            continue
        tgt = res.entity
        if tgt.id == source.id:
            out.skipped.append({"token": token, "reason": "a product cannot relate to itself"})
            continue
        if not user.in_brand_scope(tgt.brand_scopes or []):
            out.skipped.append({"token": token, "reason": "outside your brand scope"})
            continue
        if tgt.id in existing:
            out.skipped.append({"token": token, "reason": "already linked"})
            continue
        rel = ProductRelationship(type_code=type_code, from_entity_id=source.id, to_entity_id=tgt.id, quantity=quantity, created_by=user.email)
        session.add(rel)
        session.flush()
        existing.add(tgt.id)
        out.created.append(rel)
        if rt.direction == "two_way":
            back = session.execute(select(ProductRelationship).where(ProductRelationship.type_code == type_code,
                                                                     ProductRelationship.from_entity_id == tgt.id,
                                                                     ProductRelationship.to_entity_id == source.id)).scalars().first()
            if back is None:
                session.add(ProductRelationship(type_code=type_code, from_entity_id=tgt.id, to_entity_id=source.id, quantity=quantity,
                                                mirror_of=rel.id, created_by=user.email))
    session.flush()
    return out


def remove(session: Session, rel: ProductRelationship) -> int:
    """Removes a link and, for a two-way type, its mirror."""
    n = 1
    mirror = session.execute(select(ProductRelationship).where(
        (ProductRelationship.mirror_of == rel.id) | (ProductRelationship.id == (rel.mirror_of or "")))).scalars().all()
    for m in mirror:
        session.delete(m)
        n += 1
    session.delete(rel)
    session.flush()
    return n


def links_for(session: Session, entity: ProductEntity) -> list[dict]:
    """Outgoing links of the entity plus, for a style-color, the links inherited from its style (DM-13)."""
    own = session.execute(select(ProductRelationship).where(ProductRelationship.from_entity_id == entity.id)).scalars().all()
    inherited: list[ProductRelationship] = []
    if entity.level == "style_color" and entity.parent_id:
        inherited = session.execute(select(ProductRelationship).where(ProductRelationship.from_entity_id == entity.parent_id)).scalars().all()
    ids = {r.to_entity_id for r in own + inherited}
    targets = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_(ids))).scalars()} if ids else {}
    types_by_code = {t.code: t for t in types(session, include_disabled=True)}
    out = []
    for r, inh in [(r, False) for r in own] + [(r, True) for r in inherited]:
        t = targets.get(r.to_entity_id)
        rt = types_by_code.get(r.type_code)
        out.append({"id": r.id, "type_code": r.type_code, "type_label": rt.label if rt else r.type_code, "direction": rt.direction if rt else "one_way",
                    "inherited": inh, "quantity": r.quantity, "created_by": r.created_by, "created_at": r.created_at.isoformat(),
                    "target": {"entity_id": r.to_entity_id, "label": t.label if t else None, "style_number": t.style_number if t else None,
                               "color_code": t.color_code if t else None, "lifecycle_status": t.lifecycle_status if t else None},
                    "broken": t is None or t.lifecycle_status == "discontinued"})
    return out


def broken_links(session: Session, entity_ids: list[str]) -> dict[str, list[str]]:
    """EXP-03: per entity, labels of related products that are discontinued or gone (style links count for colors)."""
    if not entity_ids:
        return {}
    ents = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_(entity_ids))).scalars()}
    sources = set(ents) | {e.parent_id for e in ents.values() if e.parent_id}
    rels = session.execute(select(ProductRelationship).where(ProductRelationship.from_entity_id.in_(sources))).scalars().all()
    if not rels:
        return {}
    targets = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_({r.to_entity_id for r in rels}))).scalars()}
    by_source: dict[str, list[str]] = {}
    for r in rels:
        t = targets.get(r.to_entity_id)
        if t is None or t.lifecycle_status == "discontinued":
            by_source.setdefault(r.from_entity_id, []).append(f"{r.type_code}: {t.label if t else r.to_entity_id}")
    out: dict[str, list[str]] = {}
    for eid, e in ents.items():
        found = list(by_source.get(eid, [])) + (list(by_source.get(e.parent_id, [])) if e.parent_id else [])
        if found:
            out[eid] = found
    return out


def related_external_ids(session: Session, entity: ProductEntity, type_code: str) -> list[str]:
    """EXP-09 feed source `related:<type>`: the style-color identifiers of related products (own and inherited)."""
    return [f"{lk['target']['style_number']}-{lk['target']['color_code']}" if lk["target"]["color_code"] else str(lk["target"]["style_number"])
            for lk in links_for(session, entity) if lk["type_code"] == type_code and not lk["broken"]]
