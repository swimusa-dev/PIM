"""Completeness and channel readiness (DM-05, EXP-03, EXP-12, GOV-06, IMG-02, AI-06 certificate warning, DM-13 broken
relationship warning).

Readiness is computed for style-colors (the unit channels list) and cached in readiness_snapshot so grids
can filter on it. Style-level and SKU-level rows report the readiness of their style-colors (min / aggregate).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pim.models import AssetLink, Channel, ProductEntity, ProductValue, ReadinessSnapshot, ReferenceEntity
from pim.models._common import utcnow
from pim.services.metadata import Metadata
from pim.services.values import typed_from_row

CERT_WORDS = re.compile(r"\b(REPREVE|GOTS|OCS|RCS|GRS|OEKO[- ]?TEX)\b", re.IGNORECASE)


@dataclass
class Readiness:
    channel_code: str
    eligible: bool = True
    ready: bool = False
    completeness_pct: int = 0
    required_total: int = 0
    required_done: int = 0
    missing_attributes: list[str] = field(default_factory=list)
    missing_shots: list[str] = field(default_factory=list)
    mapping_gaps: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ready": self.ready, "eligible": self.eligible, "completeness": self.completeness_pct,
            "missing_attributes": self.missing_attributes, "missing_shots": self.missing_shots,
            "mapping_gaps": self.mapping_gaps, "invalid": self.invalid, "warnings": self.warnings, "reasons": self.reasons,
        }


def check_eligibility(channel: Channel, entity: ProductEntity, style: ProductEntity | None) -> list[str]:
    """EXP-12 rules evaluated before readiness. Returns reasons the product is ineligible (empty = eligible)."""
    rules = channel.eligibility or {}
    reasons: list[str] = []
    scopes = set(entity.brand_scopes or []) | set((style.brand_scopes if style else []) or [])
    wanted = rules.get("brand_scopes")
    if wanted and not scopes & set(wanted):
        reasons.append("Outside the channel's brand scope")
    cls = (entity.brand_classification or (style.brand_classification if style else None) or "").lower()
    erp = (style.erp_fields if style else entity.erp_fields) or {}
    subdiv = str(erp.get("sub_division", "")).upper()
    allowed = (rules.get("allow_classifications_for_subdivision") or {}).get(cls)
    if cls in {c.lower() for c in rules.get("exclude_classifications", [])}:
        reasons.append(f"{cls.replace('_', ' ').title()} products are eligible only for their own retailer")
    elif allowed is not None and not any(a.upper() in subdiv for a in allowed):
        reasons.append(f"{cls.replace('_', ' ').title()} product not made for this retailer")
    if entity.lifecycle_status in rules.get("exclude_lifecycle", []):
        reasons.append(f"Lifecycle status is {entity.lifecycle_status}")
    if entity.entity_type in rules.get("exclude_entity_types", []):
        reasons.append("Prepacks are excluded from this channel")
    return reasons


def _answered(pv: ProductValue | None) -> bool:
    if pv is None:
        return False
    if pv.not_applicable:
        return True  # IMP-10: Not applicable counts as answered
    if pv.source_type == "default" and not pv.confirmed_default:
        return False  # GOV-06: unconfirmed defaults never count
    if pv.approval_state not in ("approved",):
        return False
    return not typed_from_row(pv).is_empty()


def compute_readiness(session: Session, meta: Metadata, entity: ProductEntity, channel: Channel,
                      values: dict[tuple[str, str], ProductValue] | None = None,
                      style: ProductEntity | None = None, links: list[AssetLink] | None = None,
                      broken_relationships: list[str] | None = None) -> Readiness:
    r = Readiness(channel_code=channel.code)
    if broken_relationships is None:
        from pim.services.relationships import broken_links

        broken_relationships = broken_links(session, [entity.id]).get(entity.id, [])
    if broken_relationships:
        # DM-13: a related product that is discontinued or gone is a warning on every channel, never a blocker
        r.warnings.append(f"{len(broken_relationships)} related product(s) discontinued or missing: " + "; ".join(broken_relationships[:5]))
    if style is None and entity.parent_id:
        style = session.get(ProductEntity, entity.parent_id)
    inel = check_eligibility(channel, entity, style)
    if inel:
        r.eligible = False
        r.reasons.extend(inel)
    rs = meta.requirement_set_for(channel.code, entity.family_code or (style.family_code if style else None))
    if rs is None:
        r.ready = r.eligible
        r.completeness_pct = 100
        r.reasons.append("No requirement set bound to this channel")
        return r
    if values is None:
        ids = [entity.id] + ([style.id] if style else [])
        values = {}
        for pv in session.execute(select(ProductValue).where(ProductValue.entity_id.in_(ids))).scalars():
            values[(pv.attribute_code, pv.channel_code)] = pv
    mapping = channel.attribute_mapping or {}
    for req in rs.requirements:
        if req.attribute_code:
            attr = meta.attributes.get(req.attribute_code)
            if attr is None or attr.status == "deprecated":
                continue
            pv = values.get((req.attribute_code, channel.code)) or values.get((req.attribute_code, ""))
            if req.required:
                r.required_total += 1
                if _answered(pv):
                    r.required_done += 1
                else:
                    r.missing_attributes.append(req.attribute_code)
            if mapping and req.required and attr.code not in mapping and not any(k.startswith(attr.code + ".") for k in mapping):
                r.mapping_gaps.append(req.attribute_code)
            if pv is not None and req.max_length and pv.value_text and len(pv.value_text) > req.max_length:
                r.invalid.append(f"{req.attribute_code} exceeds {req.max_length} characters for this channel")
            # AI-06: certification claims in copy need a certificate on the Fabric entity (warning, not blocker)
            if pv is not None and pv.value_text and attr.data_type in ("text", "rich_text") and CERT_WORDS.search(pv.value_text):
                if not _has_certificate(session, meta, values):
                    r.warnings.append(f"{attr.label} mentions a certification but the Fabric has no certificate record")
        elif req.shot_type:
            if req.required:
                r.required_total += 1
                if links is None:
                    links = session.execute(select(AssetLink).where(
                        AssetLink.entity_id == entity.id, AssetLink.status == "confirmed")).scalars().all()
                if any(lnk.shot_type == req.shot_type for lnk in links):
                    r.required_done += 1
                else:
                    r.missing_shots.append(req.shot_type)
    r.completeness_pct = 100 if r.required_total == 0 else int(round(100 * r.required_done / r.required_total))
    r.ready = r.eligible and not r.missing_attributes and not r.missing_shots and not r.mapping_gaps and not r.invalid
    if r.missing_attributes:
        r.reasons.append(f"{len(r.missing_attributes)} required attribute(s) missing")
    if r.missing_shots:
        r.reasons.append(f"{len(r.missing_shots)} required image shot(s) missing")
    if r.mapping_gaps:
        r.reasons.append(f"{len(r.mapping_gaps)} required field(s) have no channel mapping")
    if r.invalid:
        r.reasons.append(f"{len(r.invalid)} value(s) invalid for this channel")
    return r


def _has_certificate(session: Session, meta: Metadata, values: dict[tuple[str, str], ProductValue]) -> bool:
    for (code, _), pv in values.items():
        attr = meta.attributes.get(code)
        if attr and attr.data_type == "reference_entity" and attr.reference_type_code == "fabric" and pv.value_ref:
            ref = session.get(ReferenceEntity, pv.value_ref)
            if ref and ref.certificate_refs:
                return True
    return False


def refresh_snapshots(session: Session, meta: Metadata, entities: list[ProductEntity]) -> None:
    """Recompute snapshots for the given style-colors (and the style-colors under given styles)."""
    targets: list[ProductEntity] = []
    for e in entities:
        if e.level == "style_color":
            targets.append(e)
        elif e.level == "style":
            targets.extend(session.execute(select(ProductEntity).where(
                ProductEntity.parent_id == e.id, ProductEntity.level == "style_color")).scalars().all())
        elif e.level == "sku" and e.parent_id:
            p = session.get(ProductEntity, e.parent_id)
            if p:
                targets.append(p)
    if not targets:
        return
    targets = list({t.id: t for t in targets}.values())
    ids = [t.id for t in targets]
    session.execute(delete(ReadinessSnapshot).where(ReadinessSnapshot.entity_id.in_(ids)))
    styles = {s.id: s for s in session.execute(select(ProductEntity).where(
        ProductEntity.id.in_({t.parent_id for t in targets if t.parent_id}))).scalars()}
    all_ids = ids + list(styles)
    values: dict[str, dict[tuple[str, str], ProductValue]] = {}
    for pv in session.execute(select(ProductValue).where(ProductValue.entity_id.in_(all_ids))).scalars():
        values.setdefault(pv.entity_id, {})[(pv.attribute_code, pv.channel_code)] = pv
    links: dict[str, list[AssetLink]] = {}
    for lnk in session.execute(select(AssetLink).where(AssetLink.entity_id.in_(ids), AssetLink.status == "confirmed")).scalars():
        links.setdefault(lnk.entity_id, []).append(lnk)
    from pim.services.relationships import broken_links

    broken = broken_links(session, ids)
    now = utcnow()
    for t in targets:
        style = styles.get(t.parent_id or "")
        merged = dict(values.get(style.id, {}) if style else {})
        merged.update(values.get(t.id, {}))
        for ch in meta.channels.values():
            r = compute_readiness(session, meta, t, ch, merged, style, links.get(t.id, []), broken.get(t.id, []))
            session.add(ReadinessSnapshot(entity_id=t.id, channel_code=ch.code, completeness_pct=r.completeness_pct,
                                          ready=r.ready, eligible=r.eligible, detail=r.as_dict(), computed_at=now))
    session.flush()
    try:
        from pim.services.quality import (
            refresh_quality,  # GOV-03 rides the same trigger; never blocks a value write
        )

        with session.begin_nested():  # savepoint: a failed quality statement rolls back alone, the value write survives
            refresh_quality(session, meta, targets)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("quality refresh failed")


def snapshots_for(session: Session, entity_ids: list[str]) -> dict[str, dict[str, ReadinessSnapshot]]:
    out: dict[str, dict[str, ReadinessSnapshot]] = {}
    if not entity_ids:
        return out
    for s in session.execute(select(ReadinessSnapshot).where(ReadinessSnapshot.entity_id.in_(entity_ids))).scalars():
        out.setdefault(s.entity_id, {})[s.channel_code] = s
    return out
