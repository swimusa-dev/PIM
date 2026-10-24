"""Server-side paged, filtered, sorted product grid (DM-01, DM-02). The catalog exceeds 100,000 SKUs, so
nothing here loads more than one page. Attribute filters use EXISTS subqueries against product_value at the
attribute's owning level (style, style-color, or SKU) so inherited values filter correctly."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import String, and_, cast, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from pim.auth.identity import CurrentUser
from pim.models import (
    AssetLink,
    IdentifierAlias,
    ProductEntity,
    ProductValue,
    QualitySnapshot,
    ReadinessSnapshot,
    ValueDraft,
)
from pim.services.metadata import LEVEL_ORDER, Metadata
from pim.services.readiness import snapshots_for
from pim.services.values import resolve_cells

CORE_FIELDS = {"style_number", "color_code", "size", "sku", "upc", "family_code", "lifecycle_status", "label", "entity_type"}


@dataclass
class GridQuery:
    level: str = "style_color"
    page: int = 1
    page_size: int = 100
    sort: list[dict] = field(default_factory=list)
    filters: list[dict] = field(default_factory=list)
    search: str | None = None
    columns: list[str] = field(default_factory=list)
    channel_code: str | None = None


def _entity_for_level(level: str, grid_level: str, e, parent, grandparent):  # noqa: ANN001
    """Pick the alias that owns `level` when the grid shows `grid_level`."""
    diff = LEVEL_ORDER[grid_level] - LEVEL_ORDER.get(level, 0)
    return {0: e, 1: parent, 2: grandparent}.get(diff)


def _value_predicate(pv, op: str, value: Any):  # noqa: ANN001
    text = func.coalesce(pv.value_text, cast(pv.value_number, String), cast(pv.value_bool, String),
                         cast(pv.value_date, String), cast(pv.value_json, String), pv.value_ref)
    if op == "eq":
        return text == str(value)
    if op == "neq":
        return text != str(value)
    if op == "contains":
        return text.ilike(f"%{value}%")
    if op == "in":
        return text.in_([str(v) for v in (value or [])])
    if op == "gt":
        return pv.value_number > float(value)
    if op == "gte":
        return pv.value_number >= float(value)
    if op == "lt":
        return pv.value_number < float(value)
    if op == "lte":
        return pv.value_number <= float(value)
    return text == str(value)


def run_grid_query(session: Session, meta: Metadata, user: CurrentUser, q: GridQuery) -> dict:
    if q.level not in LEVEL_ORDER:
        raise ValueError("level must be style, style_color or sku")
    e = aliased(ProductEntity, name="e")
    parent = aliased(ProductEntity, name="p")
    grandparent = aliased(ProductEntity, name="gp")
    stmt = select(e).where(e.level == q.level)
    stmt = stmt.outerjoin(parent, parent.id == e.parent_id).outerjoin(grandparent, grandparent.id == parent.parent_id)

    # RBAC-04 brand scope: users with restricted scopes only see their brands.
    if user.brand_scopes:
        conds = [cast(e.brand_scopes, String).like(f'%"{s}"%') for s in user.brand_scopes]
        stmt = stmt.where(or_(*conds))

    if q.search:
        like = f"%{q.search}%"
        norm = q.search.upper().replace("-", "").replace(" ", "")
        al = aliased(IdentifierAlias)
        alias_hit = exists().where(and_(al.normalized.like(f"%{norm}%"),
                                        or_(al.entity_id == e.id, al.entity_id == parent.id, al.entity_id == grandparent.id)))
        stmt = stmt.where(or_(e.style_number.ilike(like), e.color_code.ilike(like), e.sku.ilike(like),
                              e.upc.ilike(like), e.label.ilike(like), alias_hit))

    for f in q.filters:
        fld, op, val = f.get("field", ""), f.get("op", "eq"), f.get("value")
        if fld in CORE_FIELDS:
            col = getattr(e, fld)
            if op == "eq":
                stmt = stmt.where(col == val)
            elif op == "neq":
                stmt = stmt.where(col != val)
            elif op == "contains":
                stmt = stmt.where(col.ilike(f"%{val}%"))
            elif op == "in":
                stmt = stmt.where(col.in_(val or []))
            elif op == "empty":
                stmt = stmt.where(or_(col.is_(None), col == ""))
            elif op == "not_empty":
                stmt = stmt.where(and_(col.isnot(None), col != ""))
        elif fld.startswith("attr:"):
            code = fld[5:]
            attr = meta.attributes.get(code)
            if attr is None:
                continue
            owner = _entity_for_level(attr.level, q.level, e, parent, grandparent)
            if owner is None:
                continue
            pv = aliased(ProductValue)
            base = and_(pv.entity_id == owner.id, pv.attribute_code == code, pv.channel_code == (q.channel_code or ""))
            if op == "empty":
                stmt = stmt.where(~exists().where(base).where(or_(pv.not_applicable.is_(True), pv.value_text.isnot(None),
                                  pv.value_number.isnot(None), pv.value_bool.isnot(None), pv.value_date.isnot(None),
                                  pv.value_json.isnot(None), pv.value_ref.isnot(None))))
            elif op == "not_empty":
                stmt = stmt.where(exists().where(base))
            else:
                stmt = stmt.where(exists().where(base).where(_value_predicate(pv, op, val)))
        elif fld.startswith("completeness:") or fld.startswith("readiness:"):
            kind, chan = fld.split(":", 1)
            owner = _entity_for_level("style_color", q.level, e, parent, grandparent) if q.level != "style" else None
            rs = aliased(ReadinessSnapshot)
            if q.level == "style":
                # a style is ready when all of its colors are ready; completeness filter uses the minimum
                child = aliased(ProductEntity)
                sub = select(func.min(rs.completeness_pct)).where(rs.channel_code == chan, rs.entity_id == child.id,
                                                                   child.parent_id == e.id).scalar_subquery()
                if kind == "completeness":
                    stmt = stmt.where(_num_pred(sub, op, val))
                else:
                    want = str(val).lower() in ("true", "ready", "1", "yes")
                    notready = exists().where(and_(child.parent_id == e.id, rs.entity_id == child.id,
                                                   rs.channel_code == chan, rs.ready.is_(False)))
                    stmt = stmt.where(~notready if want else notready)
            else:
                base = and_(rs.entity_id == owner.id, rs.channel_code == chan)
                if kind == "completeness":
                    stmt = stmt.where(exists().where(base).where(_num_pred(rs.completeness_pct, op, val)))
                else:
                    want = str(val).lower() in ("true", "ready", "1", "yes")
                    stmt = stmt.where(exists().where(base).where(rs.ready.is_(want)))
        elif fld.startswith("quality:"):
            # GOV-03: grade filter (op in: ["A","B"]; eq: "A"; lt/gt on the score) on the style-color's snapshot
            chan = fld.split(":", 1)[1]
            chan = "" if chan == "overall" else chan
            qs = aliased(QualitySnapshot)
            owner = _entity_for_level("style_color", q.level, e, parent, grandparent) if q.level != "style" else None
            grades = [str(x).upper() for x in (val if isinstance(val, list) else [val])] if op in ("in", "eq") else []
            if q.level == "style":
                child = aliased(ProductEntity)
                base = and_(child.parent_id == e.id, qs.entity_id == child.id, qs.channel_code == chan)
                pred = qs.grade.in_(grades) if grades else _num_pred(qs.score, op, val)
                stmt = stmt.where(exists().where(base).where(pred))
            elif owner is not None:
                base = and_(qs.entity_id == owner.id, qs.channel_code == chan)
                pred = qs.grade.in_(grades) if grades else _num_pred(qs.score, op, val)
                stmt = stmt.where(exists().where(base).where(pred))
        elif fld == "approval_state":
            pv = aliased(ProductValue)
            stmt = stmt.where(exists().where(and_(pv.entity_id == e.id, pv.approval_state == val)))
        elif fld == "ai_generated":
            pv = aliased(ProductValue)
            want = str(val).lower() in ("true", "1", "yes")
            cond = exists().where(and_(pv.entity_id == e.id, pv.ai_generated.is_(True)))
            stmt = stmt.where(cond if want else ~cond)
        elif fld == "has_draft":
            d = aliased(ValueDraft)
            stmt = stmt.where(exists().where(and_(d.entity_id == e.id, d.state.in_(["draft", "proposed"]))))
        elif fld == "missing_images":
            owner = _entity_for_level("style_color", q.level, e, parent, grandparent)
            if owner is not None:
                al = aliased(AssetLink)
                stmt = stmt.where(~exists().where(and_(al.entity_id == owner.id, al.status == "confirmed")))
        elif fld == "import_batch":
            pv = aliased(ProductValue)
            stmt = stmt.where(exists().where(and_(pv.entity_id == e.id, pv.change_set_id == val)))
        elif fld == "brand_scope":
            stmt = stmt.where(cast(e.brand_scopes, String).like(f'%"{val}"%'))

    total = session.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()

    # Sorting: core fields directly; attributes through a correlated scalar subquery; sizes by scale order (DM-14)
    order_cols = []
    for s in q.sort or [{"field": "style_number", "dir": "asc"}]:
        fld, direction = s.get("field", "style_number"), s.get("dir", "asc")
        col = None
        if fld in CORE_FIELDS:
            col = getattr(e, fld)
            if fld == "size":
                col = _size_order_expr(meta, e)
        elif fld.startswith("attr:"):
            attr = meta.attributes.get(fld[5:])
            if attr:
                owner = _entity_for_level(attr.level, q.level, e, parent, grandparent)
                if owner is not None:
                    pv = aliased(ProductValue)
                    col = select(func.coalesce(pv.value_text, cast(pv.value_number, String))).where(
                        pv.entity_id == owner.id, pv.attribute_code == attr.code, pv.channel_code == "").scalar_subquery()
        elif fld.startswith("completeness:"):
            chan = fld.split(":", 1)[1]
            owner = _entity_for_level("style_color", q.level, e, parent, grandparent)
            if owner is not None:
                rs = aliased(ReadinessSnapshot)
                col = select(rs.completeness_pct).where(rs.entity_id == owner.id, rs.channel_code == chan).scalar_subquery()
        elif fld.startswith("quality:"):
            chan = fld.split(":", 1)[1]
            chan = "" if chan == "overall" else chan
            qs = aliased(QualitySnapshot)
            if q.level == "style":
                child = aliased(ProductEntity)
                col = select(func.min(qs.score)).where(qs.channel_code == chan, qs.entity_id == child.id, child.parent_id == e.id).scalar_subquery()
            else:
                owner = _entity_for_level("style_color", q.level, e, parent, grandparent)
                if owner is not None:
                    col = select(qs.score).where(qs.entity_id == owner.id, qs.channel_code == chan).scalar_subquery()
        if col is not None:
            order_cols.append(col.desc().nullslast() if direction == "desc" else col.asc().nullsfirst())
    order_cols.append(e.id)
    stmt = stmt.order_by(*order_cols).offset((q.page - 1) * q.page_size).limit(q.page_size)
    entities = session.execute(stmt).scalars().all()

    if q.columns == ["__none__"]:
        cols: list[str] = []
    else:
        cols = q.columns or [a.code for a in meta.attributes_for_level(q.level)][:12]
    cells = resolve_cells(session, meta, user, entities, cols, q.channel_code)
    rows = [row_dict(session, meta, ent, cells.get(ent.id, {})) for ent in entities]
    _attach_readiness(session, rows, entities)
    _attach_quality(session, rows, entities)
    return {"rows": rows, "total": total, "page": q.page, "page_size": q.page_size}


def _num_pred(col, op: str, val: Any):  # noqa: ANN001
    v = float(val)
    return {"gt": col > v, "gte": col >= v, "lt": col < v, "lte": col <= v, "neq": col != v}.get(op, col == v)


def _size_order_expr(meta: Metadata, e):  # noqa: ANN001
    from sqlalchemy import case

    whens = []
    for lst in meta.option_lists.values():
        if lst.kind == "size_scale":
            for v in lst.values:
                whens.append((func.upper(e.size) == v.code.upper(), v.sort_order))
    return case(*whens, else_=9999) if whens else e.size


def row_dict(session: Session, meta: Metadata, ent: ProductEntity, values: dict[str, dict]) -> dict:
    return {
        "entity_id": ent.id, "level": ent.level, "entity_type": ent.entity_type,
        "style_number": ent.style_number, "color_code": ent.color_code, "size": ent.size, "sku": ent.sku,
        "upc": ent.upc, "family_code": ent.family_code, "lifecycle_status": ent.lifecycle_status,
        "brand_scopes": ent.brand_scopes or [], "parent_id": ent.parent_id, "label": ent.label,
        "launch_date": ent.launch_date.isoformat() if ent.launch_date else None,
        "size_unmapped": ent.size_unmapped,
        "values": values, "completeness": {}, "readiness": {}, "quality": {},
    }


def _attach_readiness(session: Session, rows: list[dict], entities: list[ProductEntity]) -> None:
    """Style-colors carry their own snapshot; SKUs show the parent's; styles aggregate the minimum of their colors."""
    by_level: dict[str, list[ProductEntity]] = {}
    for ent in entities:
        by_level.setdefault(ent.level, []).append(ent)
    index = {r["entity_id"]: r for r in rows}
    if "style_color" in by_level:
        snaps = snapshots_for(session, [x.id for x in by_level["style_color"]])
        for ent in by_level["style_color"]:
            _fill(index[ent.id], snaps.get(ent.id, {}))
    if "sku" in by_level:
        pids = [x.parent_id for x in by_level["sku"] if x.parent_id]
        snaps = snapshots_for(session, pids)
        for ent in by_level["sku"]:
            _fill(index[ent.id], snaps.get(ent.parent_id or "", {}))
    if "style" in by_level:
        sids = [x.id for x in by_level["style"]]
        kids = session.execute(select(ProductEntity.id, ProductEntity.parent_id).where(
            ProductEntity.parent_id.in_(sids), ProductEntity.level == "style_color")).all()
        kid_ids = [k.id for k in kids]
        snaps = snapshots_for(session, kid_ids)
        for ent in by_level["style"]:
            agg: dict[str, dict] = {}
            for k in kids:
                if k.parent_id != ent.id:
                    continue
                for chan, s in snaps.get(k.id, {}).items():
                    cur = agg.setdefault(chan, {"min": 100, "ready": True, "eligible": False, "n": 0, "reasons": set()})
                    cur["min"] = min(cur["min"], s.completeness_pct)
                    cur["ready"] = cur["ready"] and s.ready
                    cur["eligible"] = cur["eligible"] or s.eligible
                    cur["n"] += 1
                    cur["reasons"].update(s.detail.get("reasons", []))
            for chan, a in agg.items():
                index[ent.id]["completeness"][chan] = a["min"]
                index[ent.id]["readiness"][chan] = {"ready": a["ready"], "eligible": a["eligible"],
                                                    "missing_attributes": [], "missing_shots": [], "mapping_gaps": [],
                                                    "invalid": [], "reasons": sorted(a["reasons"]), "colors": a["n"]}


def _fill(row: dict, snaps: dict) -> None:
    for chan, s in snaps.items():
        row["completeness"][chan] = s.completeness_pct
        row["readiness"][chan] = s.detail


def _attach_quality(session: Session, rows: list[dict], entities: list[ProductEntity]) -> None:
    """GOV-03 grades: style-colors their own, SKUs the parent's, styles the lowest grade of their colors."""
    from pim.services.quality import scores_for

    index = {r["entity_id"]: r for r in rows}
    sc_ids = [e.id for e in entities if e.level == "style_color"]
    sku_parents = {e.id: e.parent_id for e in entities if e.level == "sku" and e.parent_id}
    style_ids = [e.id for e in entities if e.level == "style"]
    kids = session.execute(select(ProductEntity.id, ProductEntity.parent_id).where(ProductEntity.parent_id.in_(style_ids),
                                                                                   ProductEntity.level == "style_color")).all() if style_ids else []
    snaps = scores_for(session, sc_ids + list(sku_parents.values()) + [k.id for k in kids])
    for eid in sc_ids:
        index[eid]["quality"] = {("overall" if c == "" else c): {"grade": s.grade, "score": s.score} for c, s in snaps.get(eid, {}).items()}
    for eid, pid in sku_parents.items():
        index[eid]["quality"] = {("overall" if c == "" else c): {"grade": s.grade, "score": s.score} for c, s in snaps.get(pid, {}).items()}
    for sid in style_ids:
        agg: dict[str, dict] = {}
        for k in kids:
            if k.parent_id != sid:
                continue
            for c, s in snaps.get(k.id, {}).items():
                key = "overall" if c == "" else c
                cur = agg.get(key)
                if cur is None or s.score < cur["score"]:
                    agg[key] = {"grade": s.grade, "score": s.score}
        index[sid]["quality"] = agg
