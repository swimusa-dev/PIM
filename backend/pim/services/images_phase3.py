"""Phase 3 image services: IMG-03 tier 3 AI candidates, IMG-05 ordering and technical rule checks,
IMG-06 write-back on confirmation and the AI-generated flag, IMG-07 renditions.

Tier 3 never auto-links (P4): it returns proposed links for a human to confirm. Technical rules come from the
channel requirement set's `image_rules` (min_width, min_height, aspect_ratio "4:5", max_aspect_delta, formats,
require_shot_types) and are evaluated against the Air snapshot metadata; nothing is downloaded.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from fractions import Fraction
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from pim.adapters.base import NotConfigured
from pim.config import get_settings
from pim.models import Asset, AssetLink, Channel, ImageRendition, ProductEntity
from pim.services.images import resolve_style_color
from pim.services.metadata import Metadata

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------------------------
# IMG-05 technical rules
# ---------------------------------------------------------------------------------------------------
def _ratio(text: str | None) -> float | None:
    if not text:
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*[:/x]\s*(\d+(?:\.\d+)?)\s*$", str(text))
    if m:
        return float(m.group(1)) / float(m.group(2))
    try:
        return float(text)
    except ValueError:
        return None


def check_image_rules(asset: Asset, rules: dict | None) -> list[str]:
    """Reasons the asset fails a channel's technical rules (empty = passes)."""
    rules = rules or {}
    out: list[str] = []
    w, h = asset.width, asset.height
    if rules.get("min_width") and (w is None or w < int(rules["min_width"])):
        out.append(f"width {w or 'unknown'} below {rules['min_width']}")
    if rules.get("min_height") and (h is None or h < int(rules["min_height"])):
        out.append(f"height {h or 'unknown'} below {rules['min_height']}")
    if rules.get("max_width") and w and w > int(rules["max_width"]):
        out.append(f"width {w} above {rules['max_width']}")
    want = _ratio(rules.get("aspect_ratio"))
    if want and w and h:
        delta = float(rules.get("max_aspect_delta", 0.02))
        if abs((w / h) - want) > delta:
            out.append(f"aspect ratio {Fraction(w, h).limit_denominator(20)} is not {rules['aspect_ratio']}")
    fmts = [f.lower().lstrip(".") for f in rules.get("formats", [])]
    if fmts:
        ext = asset.filename.rsplit(".", 1)[-1].lower() if "." in asset.filename else ""
        if ext and ext not in fmts:
            out.append(f"format {ext} not in {', '.join(fmts)}")
    if rules.get("reject_ai_generated") and asset.ai_generated_image:
        out.append("AI generated images are not allowed by this channel")
    return out


def rule_failures_for(meta: Metadata, asset: Asset, family_code: str | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ch in meta.channels.values():
        rs = meta.requirement_set_for(ch.code, family_code)
        if rs and rs.image_rules:
            fails = check_image_rules(asset, rs.image_rules)
            if fails:
                out[ch.code] = fails
    return out


def failing_rules_queue(session: Session, meta: Metadata, channel_code: str | None, page: int, page_size: int) -> dict:
    links = session.execute(select(AssetLink).options(selectinload(AssetLink.asset)).where(AssetLink.status == "confirmed")
                            .order_by(AssetLink.created_at.desc())).scalars().all()
    ents = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_({lk.entity_id for lk in links}))).scalars()} if links else {}
    rows = []
    for lk in links:
        if lk.asset is None:
            continue
        e = ents.get(lk.entity_id)
        fails = rule_failures_for(meta, lk.asset, e.family_code if e else None)
        if channel_code:
            fails = {k: v for k, v in fails.items() if k == channel_code}
        if fails:
            rows.append({"id": lk.id, "asset_id": lk.asset_id, "entity_id": lk.entity_id, "product_label": e.label if e else lk.entity_id,
                         "shot_type": lk.shot_type, "filename": lk.asset.filename, "thumbnail_url": lk.asset.thumbnail_url,
                         "width": lk.asset.width, "height": lk.asset.height, "rule_failures": fails,
                         "reason": "; ".join(f"{c}: {', '.join(v)}" for c, v in fails.items())})
    total = len(rows)
    return {"kind": "failing_rules", "total": total, "rows": rows[(page - 1) * page_size: page * page_size]}


def reorder_links(session: Session, entity_id: str, link_ids: list[str]) -> list[AssetLink]:
    links = session.execute(select(AssetLink).where(AssetLink.entity_id == entity_id, AssetLink.status != "rejected")).scalars().all()
    by_id = {lk.id: lk for lk in links}
    unknown = [i for i in link_ids if i not in by_id]
    if unknown:
        raise ValueError(f"Links not on this product: {', '.join(unknown[:3])}")
    pos = 0
    for lid in link_ids:
        by_id[lid].sort_order = pos
        pos += 1
    for lk in sorted((lk for lk in links if lk.id not in link_ids), key=lambda x: x.sort_order):
        lk.sort_order = pos
        pos += 1
    return sorted(links, key=lambda x: x.sort_order)


# ---------------------------------------------------------------------------------------------------
# IMG-06 write-back on confirmation
# ---------------------------------------------------------------------------------------------------
def try_write_back(session: Session, link: AssetLink, client=None) -> bool:  # noqa: ANN001
    """Best effort: a missing Air key or an API failure never blocks the confirmation."""
    from pim.services.images import write_back_to_air

    try:
        if client is None:
            from pim.adapters.air_dam import AirClient

            client = AirClient()
        write_back_to_air(session, client, link)
        if link.asset is not None and link.asset.ai_generated_image:
            client.set_custom_fields(link.asset_id, {"AI Generated": "Yes"})
        return True
    except NotConfigured:
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning("Air write-back failed for link %s: %s", link.id, exc)
        return False


# ---------------------------------------------------------------------------------------------------
# IMG-03 tier 3: Air semantic search plus a vision model, behind PIM_FEATURE_IMAGE_AI_MATCH
# ---------------------------------------------------------------------------------------------------
class FeatureOff(RuntimeError):
    pass


def ai_candidates(session: Session, meta: Metadata, asset: Asset, *, air_client=None, ai_service=None,  # noqa: ANN001
                  user_email: str = "system", max_candidates: int = 3) -> list[AssetLink]:
    if not get_settings().feature_image_ai_match:
        raise FeatureOff("PIM_FEATURE_IMAGE_AI_MATCH is off; tier 3 matching stays disabled until PLT-00 step 8 passes")
    hints: list[dict] = []
    # Step 1: Air semantic search for sibling assets that already resolved to a product (tier 1 or 2)
    if air_client is not None:
        try:
            for hit in air_client.search_assets(asset.filename.rsplit(".", 1)[0], semantic=True, limit=10):
                sib = session.get(Asset, str(hit.get("id")))
                if sib is None or sib.id == asset.id:
                    continue
                lk = session.execute(select(AssetLink).where(AssetLink.asset_id == sib.id, AssetLink.status == "confirmed")).scalars().first()
                if lk:
                    hints.append({"entity_id": lk.entity_id, "why": f"Air semantic neighbor {sib.filename}", "score": float(hit.get("score", 0.5))})
        except Exception as exc:  # noqa: BLE001
            log.warning("Air semantic search failed: %s", exc)
    # Step 2: vision model reads any visible style or color text and names the shot type
    vision: dict[str, Any] = {}
    if ai_service is not None and asset.thumbnail_url:
        try:
            vision = ai_service.describe_image(asset.thumbnail_url, shot_types=list(meta.shot_types), user_email=user_email) or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("vision call failed: %s", exc)
    if vision.get("style_number"):
        ent = resolve_style_color(session, str(vision["style_number"]), vision.get("color_code"))
        if ent is not None:
            hints.insert(0, {"entity_id": ent.id, "why": "Vision model read the style and color from the image",
                             "score": float(vision.get("confidence", 0.7)), "vision": True})
    shot = vision.get("shot_type") if vision.get("shot_type") in meta.shot_types else None
    seen: set[str] = set()
    out: list[AssetLink] = []
    for h in sorted(hints, key=lambda x: (0 if x.get("vision") else 1, -x["score"])):  # a read code beats a neighbor
        if h["entity_id"] in seen or len(out) >= max_candidates:
            continue
        seen.add(h["entity_id"])
        exists = session.execute(select(AssetLink).where(AssetLink.asset_id == asset.id, AssetLink.entity_id == h["entity_id"],
                                                         AssetLink.status.in_(["proposed", "confirmed"]))).scalars().first()
        if exists:
            out.append(exists)
            continue
        link = AssetLink(asset_id=asset.id, entity_id=h["entity_id"], shot_type=shot, tier=3, confidence=min(0.89, h["score"]),
                         status="proposed", evidence={"tier": 3, "why": h["why"], "vision": {k: v for k, v in vision.items() if k != "raw"}})
        session.add(link)
        out.append(link)
    if out:
        asset.parse_status = "parsed"
    session.flush()
    return out


# ---------------------------------------------------------------------------------------------------
# IMG-07 renditions
# ---------------------------------------------------------------------------------------------------
def profile_hash(profile: dict) -> str:
    keep = {k: profile.get(k) for k in ("width", "height", "format", "pad_to_ratio", "background")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:16]


def rendition_out(r: ImageRendition) -> dict:
    return {"id": r.id, "asset_id": r.asset_id, "version_id": r.version_id, "channel_code": r.channel_code, "url": r.url,
            "width": r.width, "height": r.height, "format": r.format, "source": r.source, "created_at": r.created_at.isoformat()}


def ensure_rendition(session: Session, channel: Channel, asset: Asset, air_client=None) -> tuple[ImageRendition | None, bool]:  # noqa: ANN001
    """Returns (rendition, queued). Air CDN transforms serve the derivative without storing a copy; when Air is not
    configured the row is queued (source=pending) for the resize job."""
    profile = channel.image_profile or {}
    if not profile:
        return None, False
    ph = profile_hash(profile)
    existing = session.execute(select(ImageRendition).where(ImageRendition.asset_id == asset.id, ImageRendition.channel_code == channel.code,
                                                            ImageRendition.profile_hash == ph,
                                                            ImageRendition.version_id == (asset.version_id or None))).scalars().first()
    if existing and existing.source != "pending":
        return existing, False
    url = None
    try:
        client = air_client
        if client is None:
            from pim.adapters.air_dam import AirClient

            client = AirClient()
        url = client.cdn_url(asset.id, width=profile.get("width"), height=profile.get("height"), fmt=profile.get("format", "jpg"))
    except NotConfigured:
        url = None
    except Exception as exc:  # noqa: BLE001
        log.warning("Air CDN transform failed for %s: %s", asset.id, exc)
        url = None
    if existing is None:
        existing = ImageRendition(asset_id=asset.id, version_id=asset.version_id or None, channel_code=channel.code, profile_hash=ph,
                                  url=url or "", width=profile.get("width"), height=profile.get("height"), format=profile.get("format", "jpg"),
                                  source="air_cdn" if url else "pending")
        session.add(existing)
    else:
        existing.url, existing.source = url or "", "air_cdn" if url else "pending"
    session.flush()
    return existing, not url


def refresh_renditions(session: Session, channel: Channel, entity_ids: list[str] | None, air_client=None) -> dict[str, int]:  # noqa: ANN001
    q = select(AssetLink).where(AssetLink.status == "confirmed")
    if entity_ids:
        q = q.where(AssetLink.entity_id.in_(entity_ids))
    wanted = set((channel.image_profile or {}).get("shot_types") or [])
    created = queued = 0
    for lk in session.execute(q).scalars():
        if wanted and lk.shot_type not in wanted or lk.asset is None:
            continue
        r, q_ = ensure_rendition(session, channel, lk.asset, air_client)
        if r is None:
            continue
        if q_:
            queued += 1
        else:
            created += 1
    return {"created": created, "queued": queued}


def render_pending_with_pillow(session: Session, fetch, storage, limit: int = 200) -> int:  # noqa: ANN001
    """Fallback resize job (IMG-07): download the original through `fetch(asset) -> bytes`, apply the profile with
    Pillow, write to the publish volume, and point the rendition at it. Used only when Air transforms are unavailable."""
    from PIL import Image, ImageOps

    pending = session.execute(select(ImageRendition).where(ImageRendition.source == "pending").limit(limit)).scalars().all()
    channels = {c.code: c for c in session.execute(select(Channel)).scalars()}
    done = 0
    for r in pending:
        ch = channels.get(r.channel_code)
        asset = session.get(Asset, r.asset_id)
        if ch is None or asset is None:
            continue
        profile = ch.image_profile or {}
        try:
            raw = fetch(asset)
            img = Image.open(_bytes(raw))
            img = ImageOps.exif_transpose(img)
            w, h = profile.get("width"), profile.get("height")
            if w or h:
                img.thumbnail((w or img.width, h or img.height))
            ratio = _ratio(profile.get("pad_to_ratio"))
            if ratio:
                tw, th = img.width, img.height
                if tw / th < ratio:
                    tw = int(round(th * ratio))
                else:
                    th = int(round(tw / ratio))
                bg = (255, 255, 255, 0) if profile.get("background") == "transparent" else (255, 255, 255)
                canvas = Image.new("RGBA" if profile.get("background") == "transparent" else "RGB", (tw, th), bg)
                canvas.paste(img, ((tw - img.width) // 2, (th - img.height) // 2))
                img = canvas
            fmt = (profile.get("format") or "jpg").lower()
            pil_fmt = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}.get(fmt, "JPEG")
            if pil_fmt == "JPEG" and img.mode != "RGB":
                img = img.convert("RGB")
            buf = _bytes(b"")
            img.save(buf, pil_fmt, quality=90)
            rel = f"renditions/{r.channel_code}/{asset.id}-{r.profile_hash}.{fmt}"
            full = storage.write(rel, buf.getvalue())
            r.url, r.width, r.height, r.source = full, img.width, img.height, "job"
            done += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("rendition job failed for %s: %s", r.asset_id, exc)
    session.flush()
    return done


def _bytes(data: bytes):  # noqa: ANN201
    import io

    return io.BytesIO(data)


def link_out_phase3(lk: AssetLink, meta: Metadata, family_code: str | None) -> dict:
    a = lk.asset
    return {"id": lk.id, "asset_id": lk.asset_id, "entity_id": lk.entity_id, "shot_type": lk.shot_type, "tier": lk.tier,
            "confidence": lk.confidence, "status": lk.status, "thumbnail_url": a.thumbnail_url if a else None,
            "filename": a.filename if a else "", "width": a.width if a else None, "height": a.height if a else None,
            "sort_order": lk.sort_order, "evidence": lk.evidence or {},
            "rule_failures": rule_failures_for(meta, a, family_code) if a else {},
            "ai_generated_image": bool(a.ai_generated_image) if a else False,
            "written_back_at": lk.written_back_at.isoformat() if lk.written_back_at else None}
