"""IMG-01 asset snapshot, IMG-03 image matching (tier 1 filename, tier 2 Air metadata, tier 3 AI candidates),
IMG-05 queues, IMG-06 write-back.

Tier 1 and 2 link automatically with status confirmed only for exact matches whose style and color both resolve
through identifier_alias. Tier 3 never auto-links (P4); it produces proposed links for review.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.models import Asset, AssetLink, FilenamePattern, IdentifierAlias, ProductEntity
from pim.models._common import utcnow
from pim.normalization import normalize_identifier
from pim.services.metadata import Metadata

log = logging.getLogger(__name__)

STYLE_FIELD_KEYS = ("style", "style number", "style_number", "style #", "style no")
COLOR_FIELD_KEYS = ("color", "color code", "color_code", "colour")
SHOT_FIELD_KEYS = ("shot", "shot type", "shot_type", "view")


@dataclass
class ParsedName:
    style: str
    color: str | None
    shot: str | None
    seq: int | None
    pattern_id: str


def parse_filename(filename: str, patterns: list[FilenamePattern]) -> ParsedName | None:
    for p in sorted((x for x in patterns if x.enabled), key=lambda x: x.priority):
        m = re.match(p.regex, filename, re.IGNORECASE)
        if not m:
            continue
        g = m.groupdict()
        shot_token = (g.get("shot") or g.get("seq") or "").lower()
        shot = (p.shot_map or {}).get(shot_token) or (p.shot_map or {}).get(shot_token.lstrip("0")) or None
        seq = int(g["seq"]) if g.get("seq") and str(g["seq"]).isdigit() else None
        return ParsedName(style=g.get("style", ""), color=g.get("color"), shot=shot, seq=seq, pattern_id=p.id)
    return None


def resolve_style_color(session: Session, style: str, color: str | None) -> ProductEntity | None:
    """Resolve through identifier_alias so any known format matches (DM-01, F7)."""
    if color:
        norm = normalize_identifier(f"{style}{color}")
        hit = session.execute(select(IdentifierAlias).where(
            IdentifierAlias.alias_type == "style_color", IdentifierAlias.normalized == norm)).scalar_one_or_none()
        if hit:
            return session.get(ProductEntity, hit.entity_id)
    style_hit = session.execute(select(IdentifierAlias).where(
        IdentifierAlias.alias_type.in_(["style", "gms", "vendor"]), IdentifierAlias.normalized == normalize_identifier(style)
    )).scalar_one_or_none()
    if not style_hit:
        return None
    st = session.get(ProductEntity, style_hit.entity_id)
    if st is None or not color:
        return None
    for child in session.execute(select(ProductEntity).where(
            ProductEntity.parent_id == st.id, ProductEntity.level == "style_color")).scalars():
        if normalize_identifier(child.color_code) == normalize_identifier(color):
            return child
    return None


def _lookup(fields: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    lowered = {str(k).lower(): v for k, v in fields.items()}
    for k in keys:
        v = lowered.get(k)
        if v:
            return str(v[0] if isinstance(v, list) else v)
    return None


def match_asset(session: Session, meta: Metadata, asset: Asset, patterns: list[FilenamePattern]) -> AssetLink | None:
    """Run tiers 1 and 2 for one asset. Returns the created link, or None (asset goes to the unparsed queue)."""
    existing = session.execute(select(AssetLink).where(AssetLink.asset_id == asset.id,
                                                       AssetLink.status.in_(["proposed", "confirmed"]))).first()
    if existing:
        return None
    # Tier 1: filename convention
    parsed = parse_filename(asset.filename, patterns)
    if parsed:
        ent = resolve_style_color(session, parsed.style, parsed.color)
        if ent is not None:
            asset.parse_status = "parsed"
            link = AssetLink(asset_id=asset.id, entity_id=ent.id, shot_type=parsed.shot, tier=1, confidence=1.0,
                             status="confirmed" if parsed.shot else "proposed", sort_order=parsed.seq or 0,
                             evidence={"tier": 1, "pattern_id": parsed.pattern_id, "style": parsed.style, "color": parsed.color},
                             decided_by="system:tier1" if parsed.shot else None, decided_at=utcnow() if parsed.shot else None)
            session.add(link)
            return link
    # Tier 2: Air custom fields and tags
    style = _lookup(asset.custom_fields or {}, STYLE_FIELD_KEYS)
    color = _lookup(asset.custom_fields or {}, COLOR_FIELD_KEYS)
    shot = _lookup(asset.custom_fields or {}, SHOT_FIELD_KEYS)
    if not style:
        for tag in asset.tags or []:
            m = re.match(r"^(\d{6})[-_]?([A-Za-z]{2,6})?$", str(tag))
            if m:
                style, color = m.group(1), m.group(2) or color
                break
    if style:
        ent = resolve_style_color(session, style, color)
        if ent is not None:
            asset.parse_status = "parsed"
            shot_code = shot.lower().replace(" ", "_").replace("-", "_") if shot else None
            if shot_code and shot_code not in meta.shot_types:
                shot_code = None
            link = AssetLink(asset_id=asset.id, entity_id=ent.id, shot_type=shot_code, tier=2, confidence=0.95,
                             status="confirmed" if shot_code else "proposed",
                             evidence={"tier": 2, "style": style, "color": color, "shot": shot},
                             decided_by="system:tier2" if shot_code else None, decided_at=utcnow() if shot_code else None)
            session.add(link)
            return link
    asset.parse_status = "unparsed"
    return None


def run_matching(session: Session, meta: Metadata, limit: int = 5000) -> dict[str, int]:
    patterns = session.execute(select(FilenamePattern)).scalars().all()
    stats = {"scanned": 0, "tier1": 0, "tier2": 0, "unparsed": 0}
    assets = session.execute(select(Asset).where(Asset.parse_status == "pending").limit(limit)).scalars().all()
    for a in assets:
        stats["scanned"] += 1
        link = match_asset(session, meta, a, patterns)
        if link is None:
            stats["unparsed"] += 1
        else:
            stats[f"tier{link.tier}"] += 1
    session.flush()
    return stats


def upsert_assets(session: Session, items: list[dict]) -> dict[str, int]:
    """IMG-01: store the snapshot and detect new or changed versions."""
    stats = {"new": 0, "changed": 0, "unchanged": 0}
    now = utcnow()
    for item in items:
        a = session.get(Asset, item["id"])
        if a is None:
            a = Asset(**item, parse_status="pending", last_seen_at=now)
            session.add(a)
            stats["new"] += 1
        elif a.version_id != item.get("version_id") or a.filename != item.get("filename") \
                or a.custom_fields != item.get("custom_fields") or a.tags != item.get("tags"):
            for k, v in item.items():
                setattr(a, k, v)
            a.parse_status = "pending"
            a.last_seen_at = now
            stats["changed"] += 1
        else:
            a.last_seen_at = now
            stats["unchanged"] += 1
    session.flush()
    return stats


def decide_link(session: Session, link: AssetLink, decision: str, user_email: str, shot_type: str | None = None) -> AssetLink:
    link.status = "confirmed" if decision == "confirm" else "rejected"
    if shot_type:
        link.shot_type = shot_type
    link.decided_by, link.decided_at = user_email, utcnow()
    return link


def write_back_to_air(session: Session, client, link: AssetLink) -> None:  # noqa: ANN001
    """IMG-06: write style, color, and shot type to Air custom fields after confirmation."""
    ent = session.get(ProductEntity, link.entity_id)
    if ent is None:
        return
    client.set_custom_fields(link.asset_id, {"Style Number": ent.style_number, "Color Code": ent.color_code,
                                             "Shot Type": link.shot_type or ""})
    link.written_back_at = utcnow()
