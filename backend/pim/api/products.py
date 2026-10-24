"""Product grid, detail, values, history, tree, images (DM-01 to DM-05, DM-08, GOV-02, IMG-05)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.api.schemas import ClearBody, GridQueryBody, LinkDecisionBody, ValuesBody
from pim.api.serializers import attribute_out, group_out
from pim.models import AssetLink, ProductEntity, SavedView, ValueHistory
from pim.services.grid import GridQuery, row_dict, run_grid_query
from pim.services.images import decide_link
from pim.services.readiness import refresh_snapshots, snapshots_for
from pim.services.values import clear_value, new_change_set, resolve_cells, restore_from_history, set_value

router = APIRouter(prefix="/api", tags=["products"])


def _entity_or_404(session: Session, entity_id: str, user: CurrentUser) -> ProductEntity:
    ent = session.get(ProductEntity, entity_id)
    if ent is None or not user.in_brand_scope(ent.brand_scopes or []):
        raise HTTPException(404, "Product not found")
    return ent


@router.post("/products/query")
def query_products(body: GridQueryBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                   user: CurrentUser = Depends(get_current_user)) -> dict:
    q = GridQuery(**{k: v for k, v in body.model_dump().items() if k != "view_id"})
    q.columns = _attribute_columns(q.columns)
    if body.view_id:
        view = session.get(SavedView, body.view_id)
        if view:
            d = view.definition or {}
            q.filters = q.filters or d.get("filters", [])
            q.columns = q.columns or d.get("columns", [])
            q.sort = q.sort or d.get("sort", [])
            q.search = q.search or d.get("search")
            q.level = view.level
    try:
        return run_grid_query(session, meta, user, q)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _attribute_columns(columns: list[str]) -> list[str]:
    """The grid sends field keys (`attr:<code>`, core fields, `completeness:<ch>`); only attributes need resolving.
    An explicit list with no attribute keys means no attribute values are needed on this page."""
    if not columns:
        return []
    return [c[5:] for c in columns if c.startswith("attr:")] + [c for c in columns if ":" not in c and c not in CORE_KEYS] or ["__none__"]


CORE_KEYS = {"style_number", "color_code", "size", "sku", "upc", "family_code", "lifecycle_status", "label", "entity_type",
             "brand_scopes", "launch_date", "parent_id", "entity_id", "level"}


def _row(session: Session, meta: Metadata, user: CurrentUser, ent: ProductEntity, codes: list[str] | None = None) -> dict:
    codes = codes or [a.code for a in meta.attributes_for_family(ent.family_code) if a.level in ("style", "style_color", "sku")]
    cells = resolve_cells(session, meta, user, [ent], codes)
    row = row_dict(session, meta, ent, cells.get(ent.id, {}))
    target = ent if ent.level == "style_color" else (session.get(ProductEntity, ent.parent_id) if ent.level == "sku" and ent.parent_id else None)
    if target:
        for chan, s in snapshots_for(session, [target.id]).get(target.id, {}).items():
            row["completeness"][chan] = s.completeness_pct
            row["readiness"][chan] = s.detail
    return row


@router.get("/products/{entity_id}")
def product_detail(entity_id: str, channel_code: str | None = None, channel: str | None = None, session: Session = Depends(get_session),
                   meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = _entity_or_404(session, entity_id, user)
    channel_code = channel_code or channel
    groups = []
    for g in meta.groups_for_family(ent.family_code):
        if not user.can_view_group(g.code):
            continue
        attrs = [a for a in sorted(g.attributes, key=lambda a: (a.sort_order, a.code)) if a.status != "deprecated" or True]
        attrs = [a for a in attrs if a.level in ("style", "style_color", "sku")]
        if attrs:
            groups.append({"group": group_out(g), "attributes": [attribute_out(a) for a in attrs]})
    codes = [a["code"] for grp in groups for a in grp["attributes"]]
    cells = resolve_cells(session, meta, user, [ent], codes, channel_code)
    row = row_dict(session, meta, ent, cells.get(ent.id, {}))
    target = ent if ent.level == "style_color" else (session.get(ProductEntity, ent.parent_id) if ent.level == "sku" and ent.parent_id else None)
    if target:
        for chan, s in snapshots_for(session, [target.id]).get(target.id, {}).items():
            row["completeness"][chan] = s.completeness_pct
            row["readiness"][chan] = s.detail
    ancestors = []
    cur = ent
    while cur.parent_id:
        cur = session.get(ProductEntity, cur.parent_id)
        if cur is None:
            break
        ancestors.append(row_dict(session, meta, cur, {}))
    children = [row_dict(session, meta, c, {}) for c in session.execute(
        select(ProductEntity).where(ProductEntity.parent_id == ent.id)).scalars()]
    hist_count = session.execute(select(func.count()).select_from(ValueHistory).where(ValueHistory.entity_id == ent.id)).scalar_one()
    return {"entity": row, "ancestors": ancestors, "children": children, "groups": groups,
            "images": _images_for(session, meta, ent)["links"], "history_count": hist_count}


@router.put("/products/{entity_id}/values")
def put_values(entity_id: str, body: ValuesBody, session: Session = Depends(get_session),
               meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = _entity_or_404(session, entity_id, user)
    cs = new_change_set(session, "edit", user.email, f"edit {len(body.values)} value(s) on {ent.label}")
    results = []
    for code, raw in body.values.items():
        attr = meta.attributes.get(code)
        if attr is None:
            results.append({"attribute_code": code, "outcome": "rejected", "message": "Unknown attribute"})
            continue
        res = set_value(session, meta, user, ent, attr, raw, channel_code=body.channel_code, change_set=cs)
        results.append({"attribute_code": code, "outcome": res.outcome, "message": res.message})
    refresh_snapshots(session, meta, [ent])
    session.commit()
    return {"results": results, "change_set_id": cs.id}


@router.post("/products/{entity_id}/values/clear")
def clear_values(entity_id: str, body: ClearBody, session: Session = Depends(get_session),
                 meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = _entity_or_404(session, entity_id, user)
    cs = new_change_set(session, "edit", user.email, "clear values")
    results = []
    for code in body.attribute_codes:
        attr = meta.attributes.get(code)
        if attr is None:
            continue
        res = clear_value(session, meta, user, ent, attr, body.channel_code, cs)
        results.append({"attribute_code": code, "outcome": res.outcome, "message": res.message})
    refresh_snapshots(session, meta, [ent])
    session.commit()
    return {"results": results}


@router.get("/products/{entity_id}/history")
def history(entity_id: str, attribute_code: str | None = None, user_email: str | None = None, page: int = 1,
            page_size: int = 50, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
            user: CurrentUser = Depends(get_current_user)) -> dict:
    _entity_or_404(session, entity_id, user)
    # History carries old and new values, so it is scoped by the same data rights as the cells (RBAC-01, D-05).
    viewable = [a.code for a in meta.attributes.values() if user.can_view_group(a.group_code)]
    q = select(ValueHistory).where(ValueHistory.entity_id == entity_id, ValueHistory.attribute_code.in_(viewable))
    if attribute_code:
        q = q.where(ValueHistory.attribute_code == attribute_code)
    if user_email:
        q = q.where(ValueHistory.set_by == user_email)
    total = session.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = session.execute(q.order_by(ValueHistory.set_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"rows": [{"id": h.id, "attribute_code": h.attribute_code, "channel_code": h.channel_code or None,
                      "old_value": h.old_value, "new_value": h.new_value, "source_type": h.source_type,
                      "set_by": h.set_by, "set_at": h.set_at.isoformat(), "change_set_id": h.change_set_id,
                      "reason": h.reason, "version": h.version} for h in rows], "total": total}


@router.post("/products/{entity_id}/history/{history_id}/restore")
def restore(entity_id: str, history_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
            user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = _entity_or_404(session, entity_id, user)
    h = session.get(ValueHistory, history_id)
    if h is None or h.entity_id != entity_id:
        raise HTTPException(404, "History row not found")
    res = restore_from_history(session, meta, user, h)
    if res.outcome == "rejected":
        raise HTTPException(403, res.message or "Restore rejected")
    refresh_snapshots(session, meta, [ent])
    session.commit()
    return {"attribute_code": res.attribute_code, "outcome": res.outcome}


@router.get("/products/{entity_id}/tree")
def tree(entity_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
         user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = _entity_or_404(session, entity_id, user)
    root = ent
    while root.parent_id:
        root = session.get(ProductEntity, root.parent_id)

    def node(e: ProductEntity) -> dict:
        kids = session.execute(select(ProductEntity).where(ProductEntity.parent_id == e.id)).scalars().all()
        return {"row": row_dict(session, meta, e, {}), "children": [node(k) for k in kids]}

    kids = session.execute(select(ProductEntity).where(ProductEntity.parent_id == root.id)).scalars().all()
    return {"root": row_dict(session, meta, root, {}), "nodes": [node(k) for k in kids]}


def _images_for(session: Session, meta: Metadata, ent: ProductEntity) -> dict:
    target = ent if ent.level == "style_color" else (session.get(ProductEntity, ent.parent_id) if ent.level == "sku" and ent.parent_id else None)
    if target is None:
        return {"slots": [], "candidates": [], "links": []}
    links = session.execute(select(AssetLink).where(AssetLink.entity_id == target.id, AssetLink.status != "rejected")
                            .order_by(AssetLink.sort_order)).scalars().all()
    required: dict[str, list[str]] = {}
    for ch in meta.channels.values():
        rs = meta.requirement_set_for(ch.code, target.family_code)
        if rs:
            for r in rs.requirements:
                if r.shot_type and r.required:
                    required.setdefault(r.shot_type, []).append(ch.code)
    out_links = [_link_out(lk) for lk in links]
    confirmed = {lk.shot_type: _link_out(lk) for lk in links if lk.status == "confirmed" and lk.shot_type}
    slots = [{"shot_type": st.code, "label": st.label, "required_by": required.get(st.code, []), "link": confirmed.get(st.code)}
             for st in sorted(meta.shot_types.values(), key=lambda s: s.sort_order)]
    return {"slots": slots, "candidates": [lk for lk in out_links if lk["status"] == "proposed"], "links": out_links}


def _link_out(lk: AssetLink) -> dict:
    a = lk.asset
    return {"id": lk.id, "asset_id": lk.asset_id, "entity_id": lk.entity_id, "shot_type": lk.shot_type, "tier": lk.tier,
            "confidence": lk.confidence, "status": lk.status, "thumbnail_url": a.thumbnail_url if a else None,
            "filename": a.filename if a else "", "width": a.width if a else None, "height": a.height if a else None,
            "sort_order": lk.sort_order, "evidence": lk.evidence}


@router.get("/products/{entity_id}/images")
def product_images(entity_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                   user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = _entity_or_404(session, entity_id, user)
    d = _images_for(session, meta, ent)
    return {"slots": d["slots"], "candidates": d["candidates"]}


@router.post("/images/links/{link_id}/{decision}")
def decide_image_link(link_id: str, decision: str, body: LinkDecisionBody | None = None, session: Session = Depends(get_session),
                      meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    if decision not in ("confirm", "reject"):
        raise HTTPException(400, "decision must be confirm or reject")
    lk = session.get(AssetLink, link_id)
    if lk is None:
        raise HTTPException(404, "Link not found")
    ent = _entity_or_404(session, lk.entity_id, user)
    if not user.can_edit_group("channel_shopify") and not user.can("admin_metadata"):
        raise HTTPException(403, "Image assignment requires edit rights on the Shopify channel group")
    decide_link(session, lk, decision, user.email, body.shot_type if body else None)
    refresh_snapshots(session, meta, [ent])
    session.commit()
    return _link_out(lk)
