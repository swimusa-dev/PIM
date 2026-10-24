"""IMP-06 survivorship and IMP-07 review, commit, rollback.

Policies per attribute group (overridable per attribute): trusted_source (ordered source ranks), fill_empty_only,
most_recent, never_from_import. Defaults: ERP-owned groups never from import; a user-approved value is only replaced by
a higher-priority source; everything else fill-empty-only. When the policy does not clearly allow a change, a
conflict is created instead of a write and goes to the review queue."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.auth.identity import CurrentUser
from pim.models import (
    IdentifierAlias,
    ImportBatch,
    ImportConflict,
    ImportRow,
    ImportSource,
    ProductEntity,
    ProductValue,
)
from pim.models._common import utcnow
from pim.normalization import normalize_identifier
from pim.services.changesets import rollback_change_set
from pim.services.metadata import LEVEL_ORDER, Metadata
from pim.services.readiness import refresh_snapshots
from pim.services.values import NA_SENTINEL, new_change_set, set_value, typed_from_row

# Trusted source ranks (lower wins): ERP > PIM user-approved > retailer template > supplier file > Shopify legacy > AI
SOURCE_RANK = {"erp": 0, "user": 1, "rule": 1, "retailer": 2, "supplier": 3, "shopify": 4, "worksheet": 1, "other": 3, "import": 3, "ai": 5, "default": 6}


def policy_for(meta: Metadata, attr) -> str:  # noqa: ANN001
    if attr.survivorship:
        return attr.survivorship
    g = meta.groups.get(attr.group_code)
    if attr.is_erp or (g and g.read_only):
        return "never_from_import"
    return (g.survivorship if g else None) or "fill_empty_only"


def current_rank(pv: ProductValue | None) -> int:
    if pv is None:
        return 99
    if pv.source_type == "user" and pv.approval_state == "approved":
        return SOURCE_RANK["user"]
    if pv.source_type == "import":
        return SOURCE_RANK.get((pv.source_ref or "").split(":")[0], SOURCE_RANK["import"]) if pv.source_ref and ":" in pv.source_ref else SOURCE_RANK["import"]
    return SOURCE_RANK.get(pv.source_type, 3)


def decide(policy: str, pv: ProductValue | None, incoming_rank: int) -> str:
    """-> write | skip | conflict"""
    if policy == "never_from_import":
        return "skip"
    empty = pv is None or (typed_from_row(pv).is_empty() and not pv.not_applicable) or (pv.source_type == "default" and not pv.confirmed_default)
    if empty:
        return "write"
    if policy == "fill_empty_only":
        return "conflict"
    if policy == "most_recent":
        return "write"
    if policy == "trusted_source":
        cur = current_rank(pv)
        if incoming_rank < cur:
            return "write"
        if incoming_rank == cur:
            return "conflict"
        return "skip" if pv.approval_state == "approved" and pv.source_type == "user" else "conflict"
    return "conflict"


def _source_rank(session: Session, batch: ImportBatch) -> int:
    src = session.get(ImportSource, batch.source_code)
    return src.trust_rank if src else SOURCE_RANK["import"]


def _target_entity(session: Session, meta: Metadata, row: ImportRow, batch: ImportBatch, attr) -> ProductEntity | None:  # noqa: ANN001
    ent = session.get(ProductEntity, row.entity_id) if row.entity_id else None
    if ent is None:
        return None
    cur = ent
    while cur is not None and LEVEL_ORDER.get(cur.level, 0) > LEVEL_ORDER.get(attr.level, 0):
        cur = session.get(ProductEntity, cur.parent_id) if cur.parent_id else None
    return cur if cur is not None and cur.level == attr.level else None


def review_batch(session: Session, meta: Metadata, batch: ImportBatch) -> dict[str, Any]:
    """Compute the diff and create conflicts; nothing is written to product_value."""
    for c in session.execute(select(ImportConflict).where(ImportConflict.batch_id == batch.id, ImportConflict.status == "open")).scalars():
        session.delete(c)
    rank = _source_rank(session, batch)
    creates, adds, changes, skipped = [], [], [], []
    conflicts = 0
    seen_creates: set[str] = set()
    seen_conflicts: set[tuple[str, str, str]] = set()
    for row in batch.rows:
        if row.action == "skip":
            skipped.append({"row_number": row.row_number, "file_index": row.file_index,
                            "reason": "; ".join(e["message"] for e in row.errors) or f"{row.match_status} and policy does not allow create"})
            continue
        if row.action == "create":
            key = f"{row.mapped.get('style_number')}-{row.mapped.get('color_code')}-{row.mapped.get('size') or ''}"
            if key not in seen_creates:
                seen_creates.add(key)
                creates.append({"row_number": row.row_number, "key": key, "level": batch.level, "label": row.mapped.get("product_name") or key})
            for code, val in row.mapped.items():
                if code in meta.attributes and val not in (None, ""):
                    adds.append({"key": key, "attribute_code": code, "new": val})
            continue
        for code, val in row.mapped.items():
            attr = meta.attributes.get(code)
            if attr is None or val in (None, ""):
                continue
            target = _target_entity(session, meta, row, batch, attr)
            if target is None:
                continue
            pv = session.execute(select(ProductValue).where(ProductValue.entity_id == target.id, ProductValue.attribute_code == code,
                                                            ProductValue.channel_code == "")).scalar_one_or_none()
            current_val = typed_from_row(pv).as_python() if pv else None
            if pv is not None and current_val == (None if val == NA_SENTINEL else val) and not (pv.source_type == "default" and not pv.confirmed_default):
                continue
            verdict = decide(policy_for(meta, attr), pv, rank)
            if verdict == "write":
                (adds if pv is None or current_val is None else changes).append(
                    {"entity_id": target.id, "label": target.label, "attribute_code": code, "old": current_val, "new": val})
            elif verdict == "conflict":
                ckey = (target.id, code, str(val))
                if ckey in seen_conflicts:
                    continue
                seen_conflicts.add(ckey)
                conflicts += 1
                session.add(ImportConflict(batch_id=batch.id, row_id=row.id, entity_id=target.id, attribute_code=code,
                                           current={"value": current_val, "source_type": pv.source_type, "set_by": pv.set_by,
                                                    "set_at": pv.set_at.isoformat() if pv.set_at else None, "approval_state": pv.approval_state},
                                           incoming={"value": val, "source": batch.source_code, "row_number": row.row_number, "file_index": row.file_index},
                                           policy=policy_for(meta, attr)))
    batch.diff = {"creates": creates[:200], "adds": adds[:200], "changes": changes[:200], "conflicts": conflicts, "skipped": skipped[:200]}
    batch.stats = {**(batch.stats or {}), "creates": len(creates), "adds": len(adds), "changes": len(changes), "conflicts": conflicts, "skipped": len(skipped)}
    batch.status = "reviewed"
    return batch.diff


def decide_conflicts(session: Session, user: CurrentUser, ids: list[str], decision: str, value: Any = None) -> int:
    n = 0
    for c in session.execute(select(ImportConflict).where(ImportConflict.id.in_(ids))).scalars():
        c.status = {"accept": "accepted", "reject": "rejected", "edit": "edited"}.get(decision, "open")
        c.resolved_value = {"value": value} if decision == "edit" else None
        c.decided_by, c.decided_at = user.email, utcnow()
        n += 1
    return n


def _create_entity(session: Session, meta: Metadata, batch: ImportBatch, row: ImportRow, created: list[str]) -> ProductEntity | None:
    style = (row.mapped.get("style_number") or "").strip()
    color = (row.mapped.get("color_code") or "").strip() or None
    size = (row.mapped.get("size") or "").strip() or None
    if not style:
        return None

    def get_or_make(level: str, parent: ProductEntity | None, **extra: Any) -> ProductEntity:
        q = select(ProductEntity).where(ProductEntity.level == level, ProductEntity.style_number == style,
                                        ProductEntity.color_code == color if level != "style" else ProductEntity.color_code.is_(None),
                                        ProductEntity.size == size if level == "sku" else ProductEntity.size.is_(None))
        ent = session.execute(q).scalar_one_or_none()
        if ent is None:
            ent = ProductEntity(level=level, style_number=style, color_code=color if level != "style" else None,
                                size=size if level == "sku" else None, parent_id=parent.id if parent else None,
                                lifecycle_status="new", family_code=row.mapped.get("family_code") or (parent.family_code if parent else None),
                                brand_scopes=parent.brand_scopes if parent else [], label=extra.get("label") or style, **{k: v for k, v in extra.items() if k != "label"})
            session.add(ent)
            session.flush()
            created.append(ent.id)
            alias = style if level == "style" else (f"{style}-{color}" if level == "style_color" else (row.mapped.get("sku") or f"{style}-{color}-{size}"))
            atype = {"style": "style", "style_color": "style_color", "sku": "sku"}[level]
            if not session.execute(select(IdentifierAlias.id).where(IdentifierAlias.alias_type == atype, IdentifierAlias.normalized == normalize_identifier(alias))).first():
                session.add(IdentifierAlias(entity_id=ent.id, alias=alias, alias_type=atype, normalized=normalize_identifier(alias), source=f"import:{batch.source_code}"))
            if level == "sku" and row.mapped.get("upc"):
                session.add(IdentifierAlias(entity_id=ent.id, alias=row.mapped["upc"], alias_type="upc", normalized=normalize_identifier(row.mapped["upc"]), source=f"import:{batch.source_code}"))
        return ent

    label = row.mapped.get("product_name") or style
    st = get_or_make("style", None, label=label)
    if batch.level == "style":
        return st
    if not color:
        return None
    sc = get_or_make("style_color", st, label=f"{label} {row.mapped.get('customer_color_name') or color}")
    if batch.level == "style_color":
        return sc
    if not size and not row.mapped.get("sku"):
        return None
    return get_or_make("sku", sc, sku=row.mapped.get("sku") or f"{style}-{color}-{size}", upc=row.mapped.get("upc"), label=f"{sc.label} {size or ''}".strip())


def commit_batch(session: Session, meta: Metadata, user: CurrentUser, batch: ImportBatch) -> dict[str, Any]:
    """IMP-07 commit: writes through survivorship decisions and accepted conflicts; one reversible change set."""
    rank = _source_rank(session, batch)
    cs = new_change_set(session, "import", user.email, f"import {batch.source_code}", source_ref=batch.id)
    batch.change_set_id, batch.status = cs.id, "committing"
    created: list[str] = []
    counts: Counter = Counter()
    touched: dict[str, ProductEntity] = {}
    conflicts = {(c.entity_id, c.attribute_code): c for c in session.execute(select(ImportConflict).where(ImportConflict.batch_id == batch.id)).scalars()}
    for row in batch.rows:
        if row.action == "skip":
            counts["rows_skipped"] += 1
            continue
        if row.action == "create":
            ent = _create_entity(session, meta, batch, row, created)
            if ent is None:
                counts["rows_failed"] += 1
                continue
            row.entity_id = ent.id
        for code, val in row.mapped.items():
            attr = meta.attributes.get(code)
            if attr is None or val in (None, ""):
                continue
            target = _target_entity(session, meta, row, batch, attr)
            if target is None:
                continue
            if row.action == "create" and target.id in created:
                verdict = "write"
            else:
                pv = session.execute(select(ProductValue).where(ProductValue.entity_id == target.id, ProductValue.attribute_code == code,
                                                                ProductValue.channel_code == "")).scalar_one_or_none()
                if pv is not None and typed_from_row(pv).as_python() == (None if val == NA_SENTINEL else val):
                    continue
                verdict = decide(policy_for(meta, attr), pv, rank)
                conf = conflicts.get((target.id, code))
                if verdict == "conflict":
                    if conf is None or conf.status in ("open", "rejected"):
                        counts["conflicts_held" if conf is None or conf.status == "open" else "conflicts_rejected"] += 1
                        continue
                    if conf.status == "edited":
                        val = (conf.resolved_value or {}).get("value")
                    verdict = "write"
            if verdict != "write":
                counts["values_skipped"] += 1
                continue
            res = set_value(session, meta, user, target, attr, val, source_type="import", source_ref=f"{batch.source_code}:{batch.id}",
                            change_set=cs, force=True, approval_state="approved")
            counts[f"values_{res.outcome}"] += 1
            touched[target.id] = target
    session.flush()
    refresh_snapshots(session, meta, list(touched.values()))
    batch.report = {**dict(counts), "created_entities": created, "change_set_id": cs.id}
    batch.status, batch.committed_at = "committed", utcnow()
    return batch.report


def rollback_batch(session: Session, meta: Metadata, user: CurrentUser, batch: ImportBatch) -> dict:
    if batch.status != "committed" or not batch.change_set_id:
        raise ValueError("Only a committed batch can be rolled back")
    result = rollback_change_set(session, meta, user, batch.change_set_id, (batch.report or {}).get("created_entities", []))
    batch.status = "rolled_back"
    batch.report = {**(batch.report or {}), "rollback": result}
    return result
