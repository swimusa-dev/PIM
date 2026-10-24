"""GOV-03 data quality score, separate from completeness. Configurable checks over a style-color (and its style):
casing and spelling heuristics, length within attribute and channel limits, brand voice blocked terms, duplicate
copy across other products, image technical checks, and unsupported certification claims (AI-06). Admins exclude
attribute groups (for example ERP data) and weight the checks; the grade is A to E per channel plus an overall
grade (channel_code ""), cached in quality_snapshot for the grid and the dashboard."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from pim.models import (
    AssetLink,
    BrandVoice,
    ProductEntity,
    ProductValue,
    QualitySettings,
    QualitySnapshot,
    ReferenceEntity,
)
from pim.models._common import utcnow
from pim.services.images_phase3 import check_image_rules
from pim.services.metadata import Metadata
from pim.services.readiness import CERT_WORDS

CHECKS = {
    "casing": "Casing and spacing (no shouting, no double spaces, no em dash)",
    "spelling": "Spelling heuristics (repeated letters, repeated words)",
    "length": "Length within attribute and channel limits",
    "blocked_terms": "No brand voice blocked terms",
    "duplicate_copy": "Copy is not duplicated from another product",
    "image_rules": "Images pass the channel's technical rules",
    "claims": "Certification claims are backed by a certificate",
}
DEFAULTS = {"excluded_groups": ["erp", "cost"], "enabled_checks": list(CHECKS), "weights": {k: 1.0 for k in CHECKS},
            "grade_bands": {"A": 90, "B": 75, "C": 60, "D": 40}}
_REPEAT = re.compile(r"(\w)\1{2,}", re.IGNORECASE)
_DOUBLE_WORD = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)


def settings_row(session: Session) -> QualitySettings:
    row = session.get(QualitySettings, "default")
    if row is None:
        row = QualitySettings(id="default", **DEFAULTS)
        session.add(row)
        session.flush()
    return row


def settings_out(row: QualitySettings) -> dict:
    return {"excluded_groups": row.excluded_groups or [], "enabled_checks": row.enabled_checks or list(CHECKS),
            "weights": {**{k: 1.0 for k in CHECKS}, **(row.weights or {})}, "grade_bands": {**DEFAULTS["grade_bands"], **(row.grade_bands or {})},
            "checks": [{"code": k, "label": v} for k, v in CHECKS.items()]}


def grade_for(score: int, bands: dict) -> str:
    for g in ("A", "B", "C", "D"):
        if score >= float(bands.get(g, DEFAULTS["grade_bands"][g])):
            return g
    return "E"


def _text_values(meta: Metadata, merged: dict[tuple[str, str], ProductValue], excluded: set[str], channel: str) -> dict[str, tuple[Any, str]]:
    """attribute code -> (text, channel used) for text attributes not in an excluded group."""
    out: dict[str, tuple[Any, str]] = {}
    for (code, ch), pv in merged.items():
        attr = meta.attributes.get(code)
        if attr is None or attr.group_code in excluded or attr.data_type not in ("text", "rich_text"):
            continue
        if ch not in ("", channel) or pv.approval_state != "approved" or not pv.value_text:
            continue
        if code in out and out[code][1] == channel and ch == "":
            continue  # channel override already taken
        out[code] = (pv.value_text, ch)
    return out


def compute_scores(session: Session, meta: Metadata, ent: ProductEntity, style: ProductEntity | None, merged: dict,
                   links: list[AssetLink], blocked: list[str], dup_index: dict[tuple[str, str], int] | None,
                   cfg: dict) -> dict[str, dict]:
    """Returns channel_code ("" overall) -> {grade, score, checks}."""
    excluded = set(cfg["excluded_groups"])
    enabled = [c for c in cfg["enabled_checks"] if c in CHECKS]
    weights = cfg["weights"]
    out: dict[str, dict] = {}
    channels = [""] + [c.code for c in meta.channels.values()]
    for chan in channels:
        texts = _text_values(meta, merged, excluded, chan)
        results: list[dict] = []
        # casing and spacing
        if "casing" in enabled:
            details = []
            for code, (txt, _ch) in texts.items():
                plain = re.sub(r"<[^>]+>", "", str(txt))
                letters = [c for c in plain if c.isalpha()]
                if len(letters) >= 12 and sum(c.isupper() for c in letters) / len(letters) > 0.8:
                    details.append(f"{meta.attributes[code].label} is all upper case")
                if "  " in plain:
                    details.append(f"{meta.attributes[code].label} has double spaces")
                if "—" in plain:
                    details.append(f"{meta.attributes[code].label} uses an em dash")
            results.append({"code": "casing", "passed": not details, "details": details[:10]})
        if "spelling" in enabled:
            details = []
            for code, (txt, _ch) in texts.items():
                plain = re.sub(r"<[^>]+>", "", str(txt))
                if _REPEAT.search(plain):
                    details.append(f"{meta.attributes[code].label}: repeated letters ({_REPEAT.search(plain).group(0)})")
                if _DOUBLE_WORD.search(plain):
                    details.append(f"{meta.attributes[code].label}: repeated word ({_DOUBLE_WORD.search(plain).group(1)})")
            results.append({"code": "spelling", "passed": not details, "details": details[:10]})
        if "length" in enabled:
            details = []
            limits: dict[str, int] = {}
            for code in texts:
                v = meta.attributes[code].validation or {}
                if v.get("max_length"):
                    limits[code] = int(v["max_length"])
            if chan:
                rs = meta.requirement_set_for(chan, ent.family_code or (style.family_code if style else None))
                for r in (rs.requirements if rs else []):
                    if r.attribute_code and r.max_length:
                        limits[r.attribute_code] = min(limits.get(r.attribute_code, r.max_length), r.max_length)
            for code, (txt, _ch) in texts.items():
                lim = limits.get(code)
                if lim and len(str(txt)) > lim:
                    details.append(f"{meta.attributes[code].label} is {len(str(txt))} characters, limit {lim}")
            results.append({"code": "length", "passed": not details, "details": details})
        if "blocked_terms" in enabled:
            details = []
            for code, (txt, _ch) in texts.items():
                for term in blocked:
                    if term and re.search(rf"\b{re.escape(term)}\b", str(txt), re.IGNORECASE):
                        details.append(f"{meta.attributes[code].label} contains the blocked term '{term}'")
            results.append({"code": "blocked_terms", "passed": not details, "details": details})
        if "duplicate_copy" in enabled and dup_index is not None:
            details = []
            for code, (txt, _ch) in texts.items():
                key = (code, _norm(txt))
                if len(str(txt)) >= 40 and dup_index.get(key, 0) > 1:
                    details.append(f"{meta.attributes[code].label} is identical on {dup_index[key] - 1} other product(s)")
            results.append({"code": "duplicate_copy", "passed": not details, "details": details})
        if "image_rules" in enabled:
            details = []
            rule_channels = [chan] if chan else list(meta.channels)
            for rc in rule_channels:
                rs = meta.requirement_set_for(rc, ent.family_code or (style.family_code if style else None))
                rules = rs.image_rules if rs else None
                if not rules:
                    continue
                for lk in links:
                    if lk.asset is None:
                        continue
                    fails = check_image_rules(lk.asset, rules)
                    if fails:
                        details.append(f"{lk.asset.filename}: {', '.join(fails)}" + (f" ({rc})" if not chan else ""))
            results.append({"code": "image_rules", "passed": not details, "details": details[:10]})
        if "claims" in enabled:
            details = []
            has_cert = _has_certificate(session, meta, merged)
            for code, (txt, _ch) in texts.items():
                m = CERT_WORDS.search(str(txt))
                if m and not has_cert:
                    details.append(f"{meta.attributes[code].label} claims {m.group(0)} but the Fabric has no certificate record")
            results.append({"code": "claims", "passed": not details, "details": details})
        total_w = sum(float(weights.get(r["code"], 1.0)) for r in results) or 1.0
        got = sum(float(weights.get(r["code"], 1.0)) for r in results if r["passed"])
        score = int(round(100 * got / total_w))
        out[chan] = {"grade": grade_for(score, cfg["grade_bands"]), "score": score,
                     "checks": [{**r, "label": CHECKS[r["code"]], "weight": float(weights.get(r["code"], 1.0))} for r in results]}
    return out


def _norm(txt: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(txt))).strip().lower()


def _has_certificate(session: Session, meta: Metadata, merged: dict) -> bool:
    for (code, _), pv in merged.items():
        attr = meta.attributes.get(code)
        if attr and attr.data_type == "reference_entity" and attr.reference_type_code == "fabric" and pv.value_ref:
            ref = session.get(ReferenceEntity, pv.value_ref)
            if ref and ref.certificate_refs:
                return True
    return False


def _blocked_terms(session: Session) -> list[str]:
    terms: list[str] = []
    for bv in session.execute(select(BrandVoice)).scalars():
        terms.extend(bv.blocked_terms or [])
    return terms


def duplicate_index(session: Session, meta: Metadata, codes: list[str] | None = None) -> dict[tuple[str, str], int]:
    """(attribute code, normalized text) -> number of entities carrying it, over approved global text values."""
    q = select(ProductValue.attribute_code, ProductValue.value_text).where(ProductValue.channel_code == "", ProductValue.approval_state == "approved",
                                                                            ProductValue.value_text.isnot(None), func.length(ProductValue.value_text) >= 40)
    if codes:
        q = q.where(ProductValue.attribute_code.in_(codes))
    idx: Counter = Counter()
    for code, txt in session.execute(q):
        if code in meta.attributes and meta.attributes[code].data_type in ("text", "rich_text"):
            idx[(code, _norm(txt))] += 1
    return dict(idx)


def duplicate_counts_for(session: Session, meta: Metadata, values: dict[str, dict[tuple[str, str], ProductValue]],
                         excluded: set[str]) -> dict[tuple[str, str], int]:
    """Incremental form of `duplicate_index`: one count query per long text value on the touched entities, normalized
    in SQL the same way (tags stripped, whitespace collapsed, lower case), instead of scanning the catalog."""
    keys: set[tuple[str, str]] = set()
    for per in values.values():
        for (code, ch), pv in per.items():
            attr = meta.attributes.get(code)
            if ch or attr is None or attr.group_code in excluded or attr.data_type not in ("text", "rich_text"):
                continue
            if pv.approval_state == "approved" and pv.value_text and len(pv.value_text) >= 40:
                keys.add((code, _norm(pv.value_text)))
    out: dict[tuple[str, str], int] = {}
    norm_sql = func.lower(func.trim(func.regexp_replace(func.regexp_replace(ProductValue.value_text, "<[^>]+>", "", "g"), r"\s+", " ", "g")))
    for code, norm in keys:
        n = session.execute(select(func.count(func.distinct(ProductValue.entity_id))).where(
            ProductValue.attribute_code == code, ProductValue.channel_code == "", ProductValue.approval_state == "approved",
            func.length(ProductValue.value_text) >= 40, norm_sql == norm)).scalar_one()
        out[(code, norm)] = int(n)
    return out


def refresh_quality(session: Session, meta: Metadata, entities: list[ProductEntity], dup_index: dict | None = None) -> int:
    """Recompute quality snapshots for the given style-colors (styles expand to their colors, SKUs to the parent)."""
    targets: dict[str, ProductEntity] = {}
    for e in entities:
        if e.level == "style_color":
            targets[e.id] = e
        elif e.level == "style":
            for c in session.execute(select(ProductEntity).where(ProductEntity.parent_id == e.id, ProductEntity.level == "style_color")).scalars():
                targets[c.id] = c
        elif e.level == "sku" and e.parent_id:
            p = session.get(ProductEntity, e.parent_id)
            if p:
                targets[p.id] = p
    if not targets:
        return 0
    cfg = settings_out(settings_row(session))
    blocked = _blocked_terms(session)
    ids = list(targets)
    styles = {s.id: s for s in session.execute(select(ProductEntity).where(ProductEntity.id.in_({t.parent_id for t in targets.values() if t.parent_id}))).scalars()}
    values: dict[str, dict[tuple[str, str], ProductValue]] = defaultdict(dict)
    for pv in session.execute(select(ProductValue).where(ProductValue.entity_id.in_(ids + list(styles)))).scalars():
        values[pv.entity_id][(pv.attribute_code, pv.channel_code)] = pv
    links: dict[str, list[AssetLink]] = defaultdict(list)
    for lk in session.execute(select(AssetLink).options(selectinload(AssetLink.asset)).where(AssetLink.entity_id.in_(ids), AssetLink.status == "confirmed")).scalars():
        links[lk.entity_id].append(lk)
    if dup_index is None and "duplicate_copy" in cfg["enabled_checks"]:
        dup_index = duplicate_counts_for(session, meta, values, excluded=set(cfg["excluded_groups"]))
    session.execute(delete(QualitySnapshot).where(QualitySnapshot.entity_id.in_(ids)))
    now = utcnow()
    for t in targets.values():
        style = styles.get(t.parent_id or "")
        merged = dict(values.get(style.id, {}) if style else {})
        merged.update(values.get(t.id, {}))
        for chan, r in compute_scores(session, meta, t, style, merged, links.get(t.id, []), blocked, dup_index, cfg).items():
            session.add(QualitySnapshot(entity_id=t.id, channel_code=chan, grade=r["grade"], score=r["score"], checks=r["checks"], computed_at=now))
    session.flush()
    return len(targets)


def recompute_all(session: Session, meta: Metadata, batch: int = 200) -> int:
    dup = duplicate_index(session, meta)
    total = 0
    ids = [r for r in session.execute(select(ProductEntity.id).where(ProductEntity.level == "style_color")).scalars()]
    for i in range(0, len(ids), batch):
        ents = session.execute(select(ProductEntity).where(ProductEntity.id.in_(ids[i:i + batch]))).scalars().all()
        total += refresh_quality(session, meta, ents, dup)
        session.commit()
    return total


def scores_for(session: Session, entity_ids: list[str]) -> dict[str, dict[str, QualitySnapshot]]:
    out: dict[str, dict[str, QualitySnapshot]] = {}
    if entity_ids:
        for s in session.execute(select(QualitySnapshot).where(QualitySnapshot.entity_id.in_(entity_ids))).scalars():
            out.setdefault(s.entity_id, {})[s.channel_code] = s
    return out


def snapshot_out(s: QualitySnapshot) -> dict:
    return {"entity_id": s.entity_id, "channel_code": s.channel_code, "grade": s.grade, "score": s.score, "checks": s.checks or [],
            "computed_at": s.computed_at.isoformat()}


def dashboard(session: Session, meta: Metadata, by: str = "family") -> list[dict]:
    """Grade counts by family, season (ERP season attribute at the style) or channel."""
    rows: dict[str, dict] = {}

    def bucket(key: str, label: str) -> dict:
        return rows.setdefault(key, {"key": key, "label": label, "A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "sum": 0, "n": 0})

    if by == "channel":
        for s in session.execute(select(QualitySnapshot).where(QualitySnapshot.channel_code != "")).scalars():
            b = bucket(s.channel_code, meta.channels[s.channel_code].label if s.channel_code in meta.channels else s.channel_code)
            b[s.grade] += 1
            b["sum"] += s.score
            b["n"] += 1
    else:
        snaps = session.execute(select(QualitySnapshot).where(QualitySnapshot.channel_code == "")).scalars().all()
        ents = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_({s.entity_id for s in snaps}))).scalars()} if snaps else {}
        seasons: dict[str, str] = {}
        if by == "season":
            parent_ids = {e.parent_id for e in ents.values() if e.parent_id}
            season_attr = next((a.code for a in meta.attributes.values() if a.erp_column == "season"), "erp_season")
            for pv in session.execute(select(ProductValue).where(ProductValue.entity_id.in_(parent_ids), ProductValue.attribute_code == season_attr,
                                                                 ProductValue.channel_code == "")).scalars() if parent_ids else []:
                seasons[pv.entity_id] = pv.value_text or "unknown"
        for s in snaps:
            e = ents.get(s.entity_id)
            if e is None:
                continue
            if by == "season":
                key = seasons.get(e.parent_id or "", (e.erp_fields or {}).get("season") or "unknown")
                label = key
            else:
                key = e.family_code or "unassigned"
                fam = meta.families.get(key) if hasattr(meta, "families") else None
                label = getattr(fam, "label", None) or key
            b = bucket(str(key), str(label))
            b[s.grade] += 1
            b["sum"] += s.score
            b["n"] += 1
    out = []
    for b in sorted(rows.values(), key=lambda x: x["label"]):
        out.append({k: v for k, v in b.items() if k not in ("sum", "n")} | {"avg_score": round(b["sum"] / b["n"], 1) if b["n"] else 0, "products": b["n"]})
    return out
