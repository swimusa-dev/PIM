"""Value reads and writes (ARC-03, DM-01, DM-03 validation, DM-08 drafts, GOV-02 history, GOV-06 defaults, P1, P2, P4).

Every write goes through `set_value`. It decides, from attribute metadata and the caller's rights, whether the
write lands as an approved value, a draft awaiting approval, or a rejection, and it records history.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from pim.auth.identity import CurrentUser
from pim.models import (
    AttributeDefinition,
    ChangeSet,
    ProductEntity,
    ProductValue,
    ReferenceEntity,
    ValueDraft,
    ValueHistory,
)
from pim.models._common import utcnow
from pim.services.metadata import Metadata


class ValueError_(Exception):
    """Validation failure for one attribute value."""


@dataclass
class Typed:
    text: str | None = None
    number: float | None = None
    boolean: bool | None = None
    day: date | None = None
    json: list | dict | None = None
    ref: str | None = None
    not_applicable: bool = False

    def is_empty(self) -> bool:
        return (
            not self.not_applicable
            and self.text is None
            and self.number is None
            and self.boolean is None
            and self.day is None
            and self.json is None
            and self.ref is None
        )

    def as_python(self) -> Any:
        if self.not_applicable:
            return None
        for v in (self.text, self.number, self.boolean, self.json, self.ref):
            if v is not None:
                return v
        if self.day is not None:
            return self.day.isoformat()
        return None


NA_SENTINEL = "__NOT_APPLICABLE__"


def coerce(meta: Metadata, attr: AttributeDefinition, raw: Any) -> Typed:
    """Validate and type a raw JSON value against the attribute definition (DM-03, 1.3)."""
    if raw == NA_SENTINEL or (isinstance(raw, dict) and raw.get("not_applicable")):
        if not attr.allows_not_applicable:
            raise ValueError_(f"{attr.label} does not allow Not applicable")
        return Typed(not_applicable=True)
    if raw is None or (isinstance(raw, str) and raw.strip() == "") or raw == []:
        return Typed()
    v = attr.validation or {}
    dt = attr.data_type
    if dt in ("text", "rich_text"):
        s = str(raw)
        if "max_length" in v and len(s) > int(v["max_length"]):
            raise ValueError_(f"{attr.label} exceeds {v['max_length']} characters")
        if "min_length" in v and len(s) < int(v["min_length"]):
            raise ValueError_(f"{attr.label} must be at least {v['min_length']} characters")
        if v.get("regex") and not re.search(v["regex"], s):
            raise ValueError_(f"{attr.label} does not match the required pattern")
        return Typed(text=s)
    if dt == "number":
        try:
            n = float(str(raw).replace(",", ""))
        except ValueError as exc:
            raise ValueError_(f"{attr.label} must be a number") from exc
        if "min" in v and n < float(v["min"]):
            raise ValueError_(f"{attr.label} must be at least {v['min']}")
        if "max" in v and n > float(v["max"]):
            raise ValueError_(f"{attr.label} must be at most {v['max']}")
        return Typed(number=n)
    if dt == "boolean":
        if isinstance(raw, bool):
            return Typed(boolean=raw)
        s = str(raw).strip().lower()
        if s in ("true", "yes", "y", "1"):
            return Typed(boolean=True)
        if s in ("false", "no", "n", "0"):
            return Typed(boolean=False)
        raise ValueError_(f"{attr.label} must be yes or no")
    if dt == "date":
        if isinstance(raw, date):
            return Typed(day=raw)
        s = str(raw).strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m.%d.%y", "%m.%d.%Y", "%m/%d/%y"):
            try:
                return Typed(day=datetime.strptime(s, fmt).date())
            except ValueError:
                continue
        raise ValueError_(f"{attr.label} is not a recognizable date (use YYYY-MM-DD)")
    if dt == "single_select":
        code = str(raw)
        codes = meta.option_codes(attr.option_list_code)
        if codes and code not in codes:
            raise ValueError_(f"{attr.label}: '{code}' is not an allowed option")
        return Typed(text=code)
    if dt == "multi_select":
        items = raw if isinstance(raw, list) else [p.strip() for p in str(raw).split(",") if p.strip()]
        codes = meta.option_codes(attr.option_list_code)
        bad = [i for i in items if codes and i not in codes]
        if bad:
            raise ValueError_(f"{attr.label}: {', '.join(bad)} not allowed")
        return Typed(json=[str(i) for i in items])
    if dt in ("reference_entity", "product_ref", "asset_ref"):
        return Typed(ref=str(raw))
    raise ValueError_(f"Unsupported data type {dt}")


def typed_from_row(pv: ProductValue) -> Typed:
    return Typed(
        text=pv.value_text,
        number=pv.value_number,
        boolean=pv.value_bool,
        day=pv.value_date,
        json=pv.value_json,
        ref=pv.value_ref,
        not_applicable=pv.not_applicable,
    )


def apply_typed(pv: ProductValue, t: Typed) -> None:
    pv.value_text, pv.value_number, pv.value_bool = t.text, t.number, t.boolean
    pv.value_date, pv.value_json, pv.value_ref, pv.not_applicable = t.day, t.json, t.ref, t.not_applicable


def snapshot(pv: ProductValue | None) -> dict | None:
    if pv is None:
        return None
    return {
        "value": typed_from_row(pv).as_python(),
        "not_applicable": pv.not_applicable,
        "source_type": pv.source_type,
        "approval_state": pv.approval_state,
        "ai_generated": pv.ai_generated,
        "version": pv.version,
    }


def cell(pv: ProductValue | None, attr: AttributeDefinition, *, read_only: bool, reason: str | None,
         inherited_from: dict | None = None, draft: ValueDraft | None = None, meta: Metadata | None = None,
         label_refs: dict[str, str] | None = None) -> dict:
    """Build the ValueCell shape from docs/api-contract.md."""
    base: dict[str, Any] = {
        "value": None, "raw_value": None, "not_applicable": False, "source_type": "user", "source_ref": None,
        "set_by": None, "set_at": None, "ai_generated": False, "approval_state": "approved", "version": 0,
        "inherited_from": inherited_from, "read_only": read_only, "read_only_reason": reason, "is_default": False,
        "draft": None,
    }
    if pv is not None:
        t = typed_from_row(pv)
        base.update(
            value=t.as_python(),
            raw_value=pv.raw_value,
            not_applicable=pv.not_applicable,
            source_type=pv.source_type,
            source_ref=pv.source_ref,
            set_by=pv.set_by,
            set_at=pv.set_at.isoformat() if pv.set_at else None,
            ai_generated=pv.ai_generated,
            approval_state=pv.approval_state,
            version=pv.version,
            is_default=pv.source_type == "default" and not pv.confirmed_default,
        )
        if attr.data_type == "reference_entity" and pv.value_ref and label_refs:
            base["display"] = label_refs.get(pv.value_ref)
        if attr.data_type == "single_select" and meta is not None and pv.value_text:
            base["display"] = meta.option_label(attr.option_list_code, pv.value_text) or pv.value_text
    if draft is not None:
        base["draft"] = {"value": draft.proposed.get("value"), "set_by": draft.submitted_by,
                         "set_at": draft.submitted_at.isoformat(), "id": draft.id, "ai_generated": draft.ai_generated}
    return base


# ---------------------------------------------------------------------------------------------------
# Reads with inheritance (DM-01)
# ---------------------------------------------------------------------------------------------------
def ancestors_of(session: Session, entity: ProductEntity) -> list[ProductEntity]:
    out: list[ProductEntity] = []
    cur = entity
    while cur.parent_id:
        cur = session.get(ProductEntity, cur.parent_id)
        if cur is None:
            break
        out.append(cur)
    return out


def load_values(session: Session, entity_ids: list[str], attribute_codes: list[str] | None = None,
                channel_code: str | None = None) -> dict[str, dict[tuple[str, str], ProductValue]]:
    """Returns entity_id -> {(attr_code, channel_code): ProductValue} for global ("") and the given channel."""
    if not entity_ids:
        return {}
    chans = [""] if not channel_code else ["", channel_code]
    q = select(ProductValue).where(ProductValue.entity_id.in_(entity_ids), ProductValue.channel_code.in_(chans))
    if attribute_codes:
        q = q.where(ProductValue.attribute_code.in_(attribute_codes))
    out: dict[str, dict[tuple[str, str], ProductValue]] = {}
    for pv in session.execute(q).scalars():
        out.setdefault(pv.entity_id, {})[(pv.attribute_code, pv.channel_code)] = pv
    return out


def resolve_cells(session: Session, meta: Metadata, user: CurrentUser, entities: list[ProductEntity],
                  attribute_codes: list[str], channel_code: str | None = None,
                  include_drafts: bool = True) -> dict[str, dict[str, dict]]:
    """entity_id -> attr_code -> ValueCell, resolving inherited values from ancestors and channel overrides."""
    # Gather ancestors so inherited attributes can be read in one query.
    by_id: dict[str, ProductEntity] = {e.id: e for e in entities}
    needed: set[str] = set(by_id)
    parent_ids = {e.parent_id for e in entities if e.parent_id}
    if parent_ids:
        parents = session.execute(select(ProductEntity).where(ProductEntity.id.in_(parent_ids))).scalars().all()
        for p in parents:
            by_id[p.id] = p
            needed.add(p.id)
        gp_ids = {p.parent_id for p in parents if p.parent_id}
        if gp_ids:
            for gp in session.execute(select(ProductEntity).where(ProductEntity.id.in_(gp_ids))).scalars():
                by_id[gp.id] = gp
                needed.add(gp.id)
    values = load_values(session, list(needed), attribute_codes, channel_code)
    drafts: dict[tuple[str, str, str], ValueDraft] = {}
    if include_drafts:
        dq = select(ValueDraft).where(
            ValueDraft.entity_id.in_(list(needed)), ValueDraft.state.in_(["draft", "proposed"]),
            ValueDraft.attribute_code.in_(attribute_codes),
        )
        for d in session.execute(dq).scalars():
            drafts[(d.entity_id, d.attribute_code, d.channel_code)] = d
    # Reference entity labels for display
    ref_ids = {pv.value_ref for vals in values.values() for pv in vals.values() if pv.value_ref}
    labels: dict[str, str] = {}
    if ref_ids:
        for r in session.execute(select(ReferenceEntity).where(ReferenceEntity.id.in_(ref_ids))).scalars():
            labels[r.id] = r.label

    out: dict[str, dict[str, dict]] = {}
    for e in entities:
        row: dict[str, dict] = {}
        chain = [e]
        cur = e
        while cur.parent_id and cur.parent_id in by_id:
            cur = by_id[cur.parent_id]
            chain.append(cur)
        for code in attribute_codes:
            attr = meta.attributes.get(code)
            if attr is None:
                continue
            owner = next((x for x in chain if x.level == attr.level), None)
            if owner is None:
                # attribute lives below this level (for example a SKU attribute on a style row)
                row[code] = cell(None, attr, read_only=True, reason="inherited")
                continue
            vals = values.get(owner.id, {})
            pv = vals.get((code, channel_code or "")) if channel_code else None
            pv = pv or vals.get((code, ""))
            inherited = None if owner.id == e.id else {"level": owner.level, "entity_id": owner.id}
            if not user.can_view_group(attr.group_code):
                row[code] = cell(None, attr, read_only=True, reason="no_rights")
                row[code]["value"] = None
                continue
            read_only, reason = False, None
            if attr.is_erp or meta.groups.get(attr.group_code, None) and meta.groups[attr.group_code].read_only:
                read_only, reason = True, "erp"
            elif inherited:
                read_only, reason = True, "inherited"
            elif attr.status == "deprecated":
                read_only, reason = True, "deprecated"
            elif not user.can_edit_group(attr.group_code):
                read_only, reason = True, "no_rights"
            d = drafts.get((owner.id, code, channel_code or "")) if include_drafts else None
            row[code] = cell(pv, attr, read_only=read_only, reason=reason, inherited_from=inherited, draft=d,
                             meta=meta, label_refs=labels)
        out[e.id] = row
    return out


# ---------------------------------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------------------------------
@dataclass
class WriteOutcome:
    attribute_code: str
    outcome: str  # approved | draft | rejected | unchanged
    message: str | None = None


def new_change_set(session: Session, kind: str, user_email: str, description: str | None = None,
                   source_ref: str | None = None) -> ChangeSet:
    cs = ChangeSet(kind=kind, created_by=user_email, description=description, source_ref=source_ref)
    session.add(cs)
    session.flush()
    return cs


def set_value(session: Session, meta: Metadata, user: CurrentUser | None, entity: ProductEntity,
              attr: AttributeDefinition, raw: Any, *, channel_code: str | None = None,
              source_type: str = "user", source_ref: str | None = None, change_set: ChangeSet | None = None,
              raw_value: str | None = None, ai_generated: bool = False, force: bool = False,
              approval_state: str | None = None) -> WriteOutcome:
    """Write one value with provenance. `force=True` is for system sources (ERP ingest, restore)."""
    channel = channel_code or ""
    code = attr.code
    # --- rules that do not depend on rights ------------------------------------------------------
    if attr.level != entity.level:
        return WriteOutcome(code, "rejected", f"{attr.label} is owned at the {attr.level} level; edit it there")
    if channel and not attr.channel_scopable:
        return WriteOutcome(code, "rejected", f"{attr.label} is not channel-scopable")
    if channel and channel not in meta.channels:
        return WriteOutcome(code, "rejected", f"Unknown channel {channel}")
    group = meta.groups.get(attr.group_code)
    if not force:
        if attr.is_erp or (group and group.read_only):
            return WriteOutcome(code, "rejected", f"{attr.label} is owned by the ERP and read-only in the PIM")
        if attr.status == "deprecated":
            return WriteOutcome(code, "rejected", f"{attr.label} is deprecated")
        if user is None or not user.can_edit_group(attr.group_code):
            return WriteOutcome(code, "rejected", f"No edit rights on {group.label if group else attr.group_code}")
        if source_type == "ai":
            return WriteOutcome(code, "rejected", "AI output must land as a suggestion (P4)")
    try:
        typed = coerce(meta, attr, raw)
    except ValueError_ as exc:
        return WriteOutcome(code, "rejected", str(exc))

    existing = session.execute(
        select(ProductValue).where(
            and_(ProductValue.entity_id == entity.id, ProductValue.attribute_code == code, ProductValue.channel_code == channel)
        )
    ).scalar_one_or_none()

    # GOV-06: a default never overwrites a non-default value.
    if source_type == "default" and existing is not None and existing.source_type != "default":
        return WriteOutcome(code, "unchanged", "Existing value kept; defaults never overwrite")

    # Draft path (DM-08): user may edit but not approve -> draft awaiting approval.
    if not force and user is not None and not user.can_approve_group(attr.group_code):
        proposed = {"value": typed.as_python(), "not_applicable": typed.not_applicable}
        open_draft = session.execute(select(ValueDraft).where(
            ValueDraft.entity_id == entity.id, ValueDraft.attribute_code == code, ValueDraft.channel_code == channel,
            ValueDraft.state.in_(["draft", "proposed"])).order_by(ValueDraft.submitted_at.desc())).scalars().first()
        if open_draft is not None:
            # One open draft per value: a correction replaces the pending proposal instead of stacking a new one.
            open_draft.proposed, open_draft.submitted_by, open_draft.submitted_at = proposed, user.email, utcnow()
            open_draft.source_type, open_draft.ai_generated, open_draft.state = source_type, ai_generated, "draft"
        else:
            session.add(ValueDraft(
                entity_level=entity.level, entity_id=entity.id, attribute_code=code, channel_code=channel,
                proposed=proposed, source_type=source_type, ai_generated=ai_generated, submitted_by=user.email, state="draft",
            ))
        return WriteOutcome(code, "draft", "Saved as a draft; send for approval")

    old = snapshot(existing)
    if existing is None:
        if typed.is_empty():
            return WriteOutcome(code, "unchanged")
        existing = ProductValue(entity_level=entity.level, entity_id=entity.id, attribute_code=code,
                                channel_code=channel, source_type=source_type, version=1)
        session.add(existing)
    else:
        if typed_from_row(existing).as_python() == typed.as_python() and existing.not_applicable == typed.not_applicable \
                and existing.source_type == source_type and (raw_value or None) == existing.raw_value:
            return WriteOutcome(code, "unchanged")
        existing.version += 1
    apply_typed(existing, typed)
    existing.raw_value = raw_value
    existing.source_type = source_type
    existing.source_ref = source_ref
    existing.set_by = user.email if user else source_type
    existing.set_at = utcnow()
    existing.ai_generated = ai_generated
    existing.approval_state = approval_state or ("approved" if source_type in ("user", "erp", "rule", "import", "default") else "proposed")
    existing.change_set_id = change_set.id if change_set else None
    if source_type != "default":
        existing.confirmed_default = False
    session.add(ValueHistory(
        entity_level=entity.level, entity_id=entity.id, attribute_code=code, channel_code=channel,
        old_value=old, new_value=snapshot(existing), source_type=source_type,
        set_by=existing.set_by, change_set_id=existing.change_set_id, version=existing.version,
    ))
    return WriteOutcome(code, "approved")


def clear_value(session: Session, meta: Metadata, user: CurrentUser, entity: ProductEntity,
                attr: AttributeDefinition, channel_code: str | None = None, change_set: ChangeSet | None = None) -> WriteOutcome:
    channel = channel_code or ""
    group = meta.groups.get(attr.group_code)
    if attr.is_erp or (group and group.read_only):
        return WriteOutcome(attr.code, "rejected", "ERP values cannot be cleared in the PIM")
    if not user.can_approve_group(attr.group_code):
        return WriteOutcome(attr.code, "rejected", "Clearing a value requires Approve rights")
    pv = session.execute(select(ProductValue).where(
        ProductValue.entity_id == entity.id, ProductValue.attribute_code == attr.code, ProductValue.channel_code == channel
    )).scalar_one_or_none()
    if pv is None:
        return WriteOutcome(attr.code, "unchanged")
    session.add(ValueHistory(entity_level=entity.level, entity_id=entity.id, attribute_code=attr.code,
                             channel_code=channel, old_value=snapshot(pv), new_value=None, source_type="user",
                             set_by=user.email, change_set_id=change_set.id if change_set else None, reason="clear",
                             version=pv.version + 1))
    session.delete(pv)
    return WriteOutcome(attr.code, "approved")


def restore_from_history(session: Session, meta: Metadata, user: CurrentUser, hist: ValueHistory) -> WriteOutcome:
    """GOV-02 single-attribute restore: re-applies the old value from a history row."""
    entity = session.get(ProductEntity, hist.entity_id)
    attr = meta.attributes.get(hist.attribute_code)
    if entity is None or attr is None:
        return WriteOutcome(hist.attribute_code, "rejected", "Entity or attribute no longer exists")
    if not user.can_approve_group(attr.group_code):
        return WriteOutcome(attr.code, "rejected", "Restore requires Approve rights")
    cs = new_change_set(session, "restore", user.email, f"restore {hist.id}")
    if hist.old_value is None:
        return clear_value(session, meta, user, entity, attr, hist.channel_code or None, cs)
    raw = NA_SENTINEL if hist.old_value.get("not_applicable") else hist.old_value.get("value")
    return set_value(session, meta, user, entity, attr, raw, channel_code=hist.channel_code or None,
                     source_type="user", source_ref=f"restore:{hist.id}", change_set=cs, force=True)


def decide_drafts(session: Session, meta: Metadata, user: CurrentUser, draft_ids: list[str], decision: str,
                  comment: str | None = None) -> list[WriteOutcome]:
    """DM-08 approve or reject drafts. Approval requires Approve rights on the attribute's group."""
    out: list[WriteOutcome] = []
    drafts = session.execute(select(ValueDraft).where(ValueDraft.id.in_(draft_ids))).scalars().all()
    cs = new_change_set(session, "approval", user.email, f"{decision} {len(drafts)} drafts")
    for d in drafts:
        attr = meta.attributes.get(d.attribute_code)
        if attr is None or not user.can_approve_group(attr.group_code):
            out.append(WriteOutcome(d.attribute_code, "rejected", "No approve rights"))
            continue
        d.decided_by, d.decided_at, d.comment = user.email, utcnow(), comment
        if decision == "reject":
            d.state = "rejected"
            out.append(WriteOutcome(d.attribute_code, "rejected", "Draft rejected"))
            continue
        entity = session.get(ProductEntity, d.entity_id)
        raw = NA_SENTINEL if d.proposed.get("not_applicable") else d.proposed.get("value")
        res = set_value(session, meta, user, entity, attr, raw, channel_code=d.channel_code or None,
                        source_type=d.source_type, source_ref=f"draft:{d.id}", change_set=cs,
                        ai_generated=d.ai_generated, force=True, approval_state="approved")
        d.state = "approved" if res.outcome in ("approved", "unchanged") else "rejected"
        out.append(res)
    return out


def to_json_safe(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    try:
        json.dumps(v)
        return v
    except TypeError:
        return str(v)
