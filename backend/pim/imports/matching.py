"""IMP-05 matching: exact first through the identifier alias table using an ordered key list per template, then
assisted candidates (fuzzy on label, color name, description) that a person must confirm. Keyless mode extracts
a product name from a chosen column ("the Skylar Top") and proposes candidates from the catalog. The match key
itself is never overwritten by an import."""

from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.models import IdentifierAlias, ImportBatch, ImportRow, ProductEntity
from pim.normalization import normalize_identifier
from pim.services.metadata import LEVEL_ORDER, Metadata

NAME_RE = re.compile(r"\b(?:the|our)\s+([A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){0,3})")
KEY_TYPES = {"upc": "upc", "sku": "sku", "style_color": "style_color", "style": "style", "gms": "gms", "vendor_style": "vendor"}


def _key_value(key: str, mapped: dict[str, Any]) -> str | None:
    if key == "style_color":
        s, c = mapped.get("style_number"), mapped.get("color_code")
        return f"{s}-{c}" if s and c else None
    if key == "vendor_style":
        return mapped.get("erp_vendor_style") or mapped.get("vendor_style")
    if key == "gms":
        return mapped.get("erp_gms_style_no") or mapped.get("gms_style_no")
    return mapped.get(key)


def _lift(session: Session, ent: ProductEntity, level: str) -> ProductEntity | None:
    """Walk up from a matched entity to the batch level (a UPC hit on a SKU resolves a style-color batch row)."""
    cur = ent
    while cur is not None and LEVEL_ORDER.get(cur.level, 0) > LEVEL_ORDER.get(level, 0):
        cur = session.get(ProductEntity, cur.parent_id) if cur.parent_id else None
    return cur if cur is not None and cur.level == level else None


def exact_match(session: Session, mapped: dict[str, Any], keys: list[str], level: str) -> tuple[str, str | None, list[str]]:
    """Returns (status, entity_id, key_used/ambiguous ids)."""
    for key in keys:
        val = _key_value(key, mapped)
        if not val:
            continue
        norm = normalize_identifier(val)
        hits = session.execute(select(IdentifierAlias).where(IdentifierAlias.alias_type == KEY_TYPES.get(key, key),
                                                             IdentifierAlias.normalized == norm)).scalars().all()
        ents = []
        for h in hits:
            e = session.get(ProductEntity, h.entity_id)
            lifted = _lift(session, e, level) if e else None
            if lifted and lifted.id not in [x.id for x in ents]:
                ents.append(lifted)
        if key == "style" and level != "style" and len(ents) == 0 and hits:
            # a style key alone cannot pick a color; let the color code narrow it
            st = session.get(ProductEntity, hits[0].entity_id)
            color = mapped.get("color_code")
            if st and color:
                for child in session.execute(select(ProductEntity).where(ProductEntity.parent_id == st.id)).scalars():
                    if normalize_identifier(child.color_code) == normalize_identifier(color):
                        ents = [child]
                        break
        if len(ents) == 1:
            return "matched", ents[0].id, [key]
        if len(ents) > 1:
            return "ambiguous", None, [e.id for e in ents]
    return "unmatched", None, []


def extract_name(text: str | None) -> str | None:
    if not text:
        return None
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    m = NAME_RE.search(first)
    if m:
        return m.group(1)
    m = NAME_RE.search(text)
    return m.group(1) if m else None


def candidates(session: Session, meta: Metadata, level: str, query: str, limit: int = 5,
               season: str | None = None) -> list[dict]:
    """Assisted candidates ranked by fuzzy similarity on label (style description + color)."""
    q = select(ProductEntity).where(ProductEntity.level == level, ProductEntity.lifecycle_status != "discontinued")
    ents = session.execute(q.limit(20000)).scalars().all()
    if season:
        seasoned = [e for e in ents if str((e.erp_fields or {}).get("season", "")).upper() == season.upper()]
        ents = seasoned or ents
    choices = {e.id: e.label or e.style_number for e in ents}
    if not choices or not query:
        return []
    results = process.extract(query, choices, scorer=fuzz.token_set_ratio, limit=limit, processor=lambda s: str(s).lower())
    out = []
    for label, score, eid in results:
        if score < 40:
            continue
        out.append({"entity_id": eid, "label": label, "score": round(score / 100, 2), "reason": f"name similarity to '{query}'"})
    return out


def match_batch(session: Session, meta: Metadata, batch: ImportBatch) -> dict[str, int]:
    keys = batch.match_keys or ["upc", "sku", "style_color", "style", "vendor_style"]
    policy = (batch.options or {}).get("unmatched_policy", "update_only")
    keyless_col = (batch.options or {}).get("keyless_name_column")
    stats = {"matched": 0, "new": 0, "ambiguous": 0, "unmatched": 0}
    for row in batch.rows:
        if row.action == "skip" and row.errors:
            continue
        if row.entity_id and (row.decided_by or row.match_key_used in ("worksheet", "assisted")):
            stats["matched"] += 1  # confirmed by a person (IMP-05) or keyed by a returned worksheet (IMP-12)
            continue
        status, eid, used = exact_match(session, row.mapped, keys, batch.level)
        row.candidates = []
        if status == "matched":
            row.match_status, row.entity_id, row.match_key_used = "matched", eid, used[0]
            row.action = "update"
            stats["matched"] += 1
            continue
        if status == "ambiguous":
            row.match_status, row.entity_id, row.match_key_used = "ambiguous", None, None
            row.candidates = [{"entity_id": i, "label": (session.get(ProductEntity, i).label if session.get(ProductEntity, i) else i),
                               "score": 1.0, "reason": "exact key matched several products"} for i in used]
            row.action = "skip"
            stats["ambiguous"] += 1
            continue
        # unmatched: assisted candidates
        query = None
        if keyless_col:
            query = extract_name(row.raw.get(keyless_col))
            row.mapped["_extracted_name"] = query
        if not query:
            parts = [str(row.mapped.get(k) or "") for k in ("product_name", "erp_style_description", "style_number", "customer_color_name", "erp_color_description")]
            query = " ".join(p for p in parts if p).strip() or None
        season = str(row.mapped.get("erp_season") or "") or None
        row.candidates = candidates(session, meta, batch.level, query, season=season) if query else []
        has_keys = any(_key_value(k, row.mapped) for k in keys)
        if policy == "create" and has_keys:
            row.match_status, row.action = "new", "create"
            stats["new"] += 1
        elif policy == "create_under_match" and has_keys and row.mapped.get("style_number"):
            st_status, st_id, _ = exact_match(session, row.mapped, ["style"], "style")
            if st_status == "matched":
                row.match_status, row.action = "new", "create"
                stats["new"] += 1
            else:
                row.match_status, row.action = "unmatched", "skip"
                stats["unmatched"] += 1
        else:
            row.match_status, row.action = "unmatched", "skip"
            stats["unmatched"] += 1
    batch.stats = {**(batch.stats or {}), **stats}
    batch.status = "matched"
    return stats


def confirm_row(session: Session, row: ImportRow, entity_id: str | None, action: str | None, user_email: str) -> ImportRow:
    """A person confirms an assisted match (IMP-05: assisted matches never auto-commit)."""
    if entity_id is not None:
        ent = session.get(ProductEntity, entity_id)
        if ent is None:
            raise ValueError("Unknown product")
        row.entity_id, row.match_status, row.match_key_used = entity_id, "matched", "assisted"
        row.action = action or "update"
    if action:
        row.action = action
        if action == "create":
            row.match_status, row.entity_id = "new", None
    row.decided_by = user_email
    return row
