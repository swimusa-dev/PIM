"""Channel eligibility and brand scopes, editable in the app (D-15).

A channel admits a style-color by its eligibility rules (`Channel.eligibility`, see readiness.check_eligibility), and
a brand scope is a rule over the ERP fields stored on each entity (`BrandScope.rules`). Both are validated here, an
impact preview shows what a change would do before it is saved, and `recompute_scopes_and_readiness` applies a
change to the products already loaded: it re-derives every entity's brand scopes from its stored ERP fields and
recomputes readiness and quality, so nothing needs the Style Master read again."""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from pim.auth.identity import evaluate_brand_scopes
from pim.models import BrandScope, Channel, ProductEntity, UserRole
from pim.services.metadata import Metadata, load_metadata
from pim.services.readiness import check_eligibility, refresh_snapshots

# ERP fields kept on every entity (ingest `erp_fields`), so a scope rule can only use these.
SCOPE_FIELDS = ("division", "sub_division", "brand_name", "brand_classification", "product_type", "season", "style_status")
SCOPE_OPS = ("eq", "neq", "in", "contains")
LIFECYCLES = ("new", "active", "discontinued")
ENTITY_TYPES = ("product", "prepack")
ELIGIBILITY_KEYS = ("brand_scopes", "exclude_classifications", "allow_classifications_for_subdivision", "exclude_lifecycle",
                    "exclude_entity_types")


class EligibilityError(ValueError):
    """A rule or eligibility body that cannot be saved; the message is shown to the user."""


def _strings(value: Any, what: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise EligibilityError(f"{what} must be a list of text values")
    return [v.strip() for v in value]


def validate_scope_rules(rules: Any) -> list[list[dict]]:
    """A scope matches when any rule matches (OR); a rule matches when all its conditions do (AND)."""
    if not isinstance(rules, list) or not rules:
        raise EligibilityError("A brand scope needs at least one rule")
    out: list[list[dict]] = []
    for i, rule in enumerate(rules, 1):
        if not isinstance(rule, list) or not rule:
            raise EligibilityError(f"Rule {i} needs at least one condition")
        conds: list[dict] = []
        for cond in rule:
            if not isinstance(cond, dict):
                raise EligibilityError(f"Rule {i} has a condition that is not a field, operator and value")
            field, op, value = cond.get("field"), cond.get("op", "eq"), cond.get("value")
            if field not in SCOPE_FIELDS:
                raise EligibilityError(f"Rule {i}: field must be one of {', '.join(SCOPE_FIELDS)}")
            if op not in SCOPE_OPS:
                raise EligibilityError(f"Rule {i}: operator must be one of {', '.join(SCOPE_OPS)}")
            if op == "in":
                value = [v for v in (value if isinstance(value, list) else str(value or "").split(",")) if str(v).strip()]
                value = [str(v).strip() for v in value]
                if not value:
                    raise EligibilityError(f"Rule {i}: give at least one value for {field}")
            else:
                value = str(value if value is not None else "").strip()
                if not value:
                    raise EligibilityError(f"Rule {i}: give a value for {field}")
            conds.append({"field": field, "op": op, "value": value})
        out.append(conds)
    return out


def validate_eligibility(raw: Any, scope_codes: set[str], classification_codes: set[str]) -> dict:
    """The normalized eligibility rules for a channel. Empty values are left out; an absent `brand_scopes` means the
    channel is open to every brand."""
    if not isinstance(raw, dict):
        raise EligibilityError("Eligibility must be a set of rules")
    unknown = sorted(set(raw) - set(ELIGIBILITY_KEYS))
    if unknown:
        raise EligibilityError(f"Unknown eligibility rule: {', '.join(unknown)}")
    out: dict[str, Any] = {}
    scopes = _strings(raw.get("brand_scopes", []), "Brand scopes")
    missing = sorted(set(scopes) - scope_codes)
    if missing:
        raise EligibilityError(f"Unknown brand scope: {', '.join(missing)}")
    if scopes:
        out["brand_scopes"] = scopes
    classes = [c.lower() for c in _strings(raw.get("exclude_classifications", []), "Excluded classifications")]
    bad = sorted(set(classes) - classification_codes)
    if bad:
        raise EligibilityError(f"Unknown brand classification: {', '.join(bad)}")
    if classes:
        out["exclude_classifications"] = classes
    for key, allowed, what in (("exclude_lifecycle", LIFECYCLES, "lifecycle status"),
                               ("exclude_entity_types", ENTITY_TYPES, "product type")):
        values = _strings(raw.get(key, []), key.replace("_", " ").capitalize())
        bad = sorted(set(values) - set(allowed))
        if bad:
            raise EligibilityError(f"Unknown {what}: {', '.join(bad)}")
        if values:
            out[key] = values
    allow = raw.get("allow_classifications_for_subdivision", {})
    if not isinstance(allow, dict) or not all(isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v)
                                              for k, v in allow.items()):
        raise EligibilityError("Subdivision exceptions must map a classification to a list of subdivision words")
    if allow:
        out["allow_classifications_for_subdivision"] = allow
    return out


def _channel_view(eligibility: dict) -> Any:
    return SimpleNamespace(eligibility=eligibility)


def eligibility_impact(session: Session, current: dict, proposed: dict) -> dict:
    """What a channel's eligibility rules would do to the style-colors loaded now, using the brand scopes stored on
    each product (recompute after changing a scope for those to be current)."""
    styles = {sid: SimpleNamespace(brand_scopes=scopes or [], brand_classification=cls, erp_fields=erp or {})
              for sid, scopes, cls, erp in session.execute(select(
                  ProductEntity.id, ProductEntity.brand_scopes, ProductEntity.brand_classification,
                  ProductEntity.erp_fields).where(ProductEntity.level == "style"))}
    now_ch, after_ch = _channel_view(current), _channel_view(proposed)
    total = eligible_now = eligible_after = newly_eligible = newly_ineligible = 0
    reasons: Counter[str] = Counter()
    for parent, scopes, cls, life, etype, erp in session.execute(select(
            ProductEntity.parent_id, ProductEntity.brand_scopes, ProductEntity.brand_classification,
            ProductEntity.lifecycle_status, ProductEntity.entity_type, ProductEntity.erp_fields
    ).where(ProductEntity.level == "style_color")):
        ent = SimpleNamespace(brand_scopes=scopes or [], brand_classification=cls, lifecycle_status=life, entity_type=etype,
                              erp_fields=erp or {})
        style = styles.get(parent or "")
        before, after = check_eligibility(now_ch, ent, style), check_eligibility(after_ch, ent, style)
        total += 1
        eligible_now += not before
        eligible_after += not after
        newly_eligible += bool(before) and not after
        newly_ineligible += not before and bool(after)
        for r in after:
            reasons[r] += 1
    return {"total": total, "eligible_now": eligible_now, "eligible_after": eligible_after,
            "newly_eligible": newly_eligible, "newly_ineligible": newly_ineligible,
            "ineligible_reasons": [{"reason": r, "count": n} for r, n in reasons.most_common(6)]}


def scope_matches(session: Session, rules: list[list[dict]]) -> dict:
    """How many styles and style-colors a scope rule would match, and in which divisions."""
    probe = BrandScope(code="preview", label="preview", rules=rules, enabled=True)
    matched: dict[str, str] = {}
    for sid, erp in session.execute(select(ProductEntity.id, ProductEntity.erp_fields).where(ProductEntity.level == "style")):
        erp = erp or {}
        if evaluate_brand_scopes(erp, [probe]):
            matched[sid] = str(erp.get("division") or "unknown")
    colors = 0
    by_division: Counter[str] = Counter()
    if matched:
        for parent, n in session.execute(select(ProductEntity.parent_id, func.count()).where(
                ProductEntity.level == "style_color").group_by(ProductEntity.parent_id)):
            if parent in matched:
                colors += n
                by_division[matched[parent]] += n
    return {"styles": len(matched), "style_colors": colors,
            "divisions": [{"division": d, "style_colors": n} for d, n in by_division.most_common(8)]}


def recompute_scopes_and_readiness(session: Session, meta: Metadata | None = None, batch: int = 500) -> dict[str, int]:
    """Apply a change to the products already loaded. Re-derive brand scopes from each entity's stored ERP fields (SKUs
    follow their style-color), then recompute readiness and quality for every style-color. Committed in chunks, so a
    failed run leaves finished chunks consistent and a repeat finishes the rest."""
    meta = meta or load_metadata(session, force=True)
    changed: dict[tuple[str, ...], list[str]] = {}
    for eid, erp, old in session.execute(select(ProductEntity.id, ProductEntity.erp_fields, ProductEntity.brand_scopes).where(
            ProductEntity.level.in_(["style", "style_color"]))).yield_per(5000):
        if not erp:
            continue  # nothing to evaluate a rule against; keep what is there
        new = sorted(evaluate_brand_scopes(erp, meta.brand_scopes))
        if new != sorted(old or []):
            changed.setdefault(tuple(new), []).append(eid)
    scope_changes = 0
    for scopes, ids in changed.items():
        for i in range(0, len(ids), 2000):
            part = ids[i:i + 2000]
            session.execute(update(ProductEntity).where(ProductEntity.id.in_(part)).values(brand_scopes=list(scopes)))
            session.execute(update(ProductEntity).where(ProductEntity.level == "sku", ProductEntity.parent_id.in_(part))
                            .values(brand_scopes=list(scopes)))
            scope_changes += len(part)
        session.commit()
    ids = list(session.execute(select(ProductEntity.id).where(ProductEntity.level == "style_color")).scalars())
    for i in range(0, len(ids), batch):
        targets = list(session.execute(select(ProductEntity).where(ProductEntity.id.in_(ids[i:i + batch]))).scalars())
        refresh_snapshots(session, meta, targets)
        session.commit()
    return {"scopes_changed": scope_changes, "style_colors_recomputed": len(ids)}


def referenced_scopes(session: Session) -> dict[str, list[str]]:
    """Brand scope code -> where it is used (channel codes, and 'user roles'), so a scope in use cannot be deleted."""
    used: dict[str, list[str]] = {}
    for ch in session.execute(select(Channel)).scalars():
        for code in (ch.eligibility or {}).get("brand_scopes", []):
            used.setdefault(code, []).append(ch.code)
    for roles in session.execute(select(UserRole.brand_scopes)).scalars():
        for code in roles or []:
            if "user roles" not in used.setdefault(code, []):
                used[code].append("user roles")
    return used
