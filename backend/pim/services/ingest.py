"""IMP-09 Style Master ingest with IMP-10 placeholder normalization, IMP-11 value mapping and ERP defects,
DM-01 hierarchy and identifier aliases, DM-14 size scale check, RBAC-04 brand scope assignment, DM-12 carryover
hook, and the New style-color launch workflow start (DM-07).

Never deletes: discontinued products are flagged. Never writes back to BlueCherry (P1).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.adapters.base import SourceAdapter
from pim.auth.identity import evaluate_brand_scopes
from pim.models import (
    ErpDefect,
    IdentifierAlias,
    IngestRun,
    PrepackComponent,
    ProductEntity,
    WorkflowDefinition,
    WorkflowItem,
)
from pim.models._common import utcnow
from pim.normalization import looks_like_test_value, map_raw_to_option, normalize_identifier
from pim.services.metadata import Metadata, load_metadata
from pim.services.readiness import refresh_snapshots
from pim.services.values import NA_SENTINEL, new_change_set, set_value

log = logging.getLogger(__name__)

HIERARCHY_KEYS = {"style_number", "color_code", "size", "sku", "upc"}


def _s(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _is_truthy(v: Any) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "y", "d", "discontinued", "inactive")


def _family_for(meta: Metadata, row: dict) -> str | None:
    for fam in meta.families.values():
        rule = fam.erp_match or {}
        if not rule:
            continue
        val = str(row.get(rule.get("field", ""), "") or "").upper()
        if "in" in rule and val in {str(x).upper() for x in rule["in"]}:
            return fam.code
        if "eq" in rule and val == str(rule["eq"]).upper():
            return fam.code
        if "contains" in rule and str(rule["contains"]).upper() in val:
            return fam.code
    return "unassigned" if "unassigned" in meta.families else None


class _Stats:
    def __init__(self) -> None:
        self.rows = 0
        self.created = 0
        self.updated = 0
        self.discontinued = 0
        self.placeholders = 0
        self.defects = 0
        self.workflows = 0
        self.placeholders_by_column: dict[str, int] = {}
        self.unmapped_sizes = 0


def _upsert_entity(session: Session, cache: dict[tuple, ProductEntity], level: str, style: str,
                   color: str | None, size: str | None, parent: ProductEntity | None, stats: _Stats,
                   now: datetime, **fields: Any) -> tuple[ProductEntity, bool]:
    key = (level, style, color, size)
    ent = cache.get(key)
    if ent is None:
        ent = session.execute(select(ProductEntity).where(
            ProductEntity.level == level, ProductEntity.style_number == style,
            ProductEntity.color_code.is_(color) if color is None else ProductEntity.color_code == color,
            ProductEntity.size.is_(size) if size is None else ProductEntity.size == size,
        )).scalar_one_or_none()
    is_new = ent is None
    if ent is None:
        ent = ProductEntity(level=level, style_number=style, color_code=color, size=size,
                            parent_id=parent.id if parent else None, lifecycle_status="new")
        session.add(ent)
        session.flush()
        stats.created += 1
    else:
        stats.updated += 1
    for k, v in fields.items():
        if v is not None:
            setattr(ent, k, v)
    ent.erp_last_seen_at = now
    if parent and ent.parent_id != parent.id:
        ent.parent_id = parent.id
    cache[key] = ent
    return ent, is_new


def _add_alias(session: Session, seen: set[tuple[str, str]], ent: ProductEntity, alias: str | None,
               alias_type: str, source: str = "erp") -> None:
    if not alias:
        return
    norm = normalize_identifier(alias)
    if not norm or (alias_type, norm) in seen:
        return
    seen.add((alias_type, norm))
    existing = session.execute(select(IdentifierAlias).where(
        IdentifierAlias.alias_type == alias_type, IdentifierAlias.normalized == norm)).scalar_one_or_none()
    if existing is None:
        session.add(IdentifierAlias(entity_id=ent.id, alias=str(alias), alias_type=alias_type, normalized=norm, source=source))
    elif existing.entity_id != ent.id:
        log.warning("Alias %s (%s) already points to another entity; kept the first", alias, alias_type)


def _write_erp_attributes(session: Session, meta: Metadata, ent: ProductEntity, row: dict, stats: _Stats,
                          change_set, now: datetime) -> None:
    """Map Style Master columns to ERP-owned attributes through AttributeDefinition.erp_column (IMP-09/10/11)."""
    for attr in meta.attributes.values():
        if not attr.erp_column or attr.level != ent.level or attr.status == "deprecated":
            continue
        if attr.erp_column not in row:
            continue
        raw = row.get(attr.erp_column)
        norm = meta.normalizer.normalize_text(raw, allows_not_applicable=attr.allows_not_applicable,
                                              not_required_means_na=attr.not_required_means_na)
        if norm.was_placeholder:
            stats.placeholders += 1
            stats.placeholders_by_column[attr.erp_column] = stats.placeholders_by_column.get(attr.erp_column, 0) + 1
        value: Any = NA_SENTINEL if norm.not_applicable else norm.value
        raw_keep: str | None = None
        if value is not None and value != NA_SENTINEL and attr.data_type == "single_select" and attr.option_list_code:
            mappings = meta.value_mappings.get(("erp", attr.option_list_code), {})
            outcome = map_raw_to_option(str(value), mappings, meta.option_codes(attr.option_list_code))
            raw_keep = str(value)
            if outcome.option_code:
                value = outcome.option_code
            else:
                _record_defect(session, ent, attr.code, attr.erp_column, str(value), outcome.defect_reason or "unmapped", now)
                stats.defects += 1
                value = None  # the raw value stays visible through raw_value on the defect report
        elif value is not None and value != NA_SENTINEL and attr.data_type in ("text", "rich_text"):
            reason = looks_like_test_value(str(value))
            if reason and attr.option_list_code is None and "claim" in attr.code:
                _record_defect(session, ent, attr.code, attr.erp_column, str(value), reason, now)
                stats.defects += 1
        set_value(session, meta, None, ent, attr, value, source_type="erp", source_ref=attr.erp_column,
                  change_set=change_set, raw_value=raw_keep, force=True)


def _record_defect(session: Session, ent: ProductEntity, attr_code: str, column: str | None, raw: str,
                   reason: str, now: datetime) -> None:
    d = session.execute(select(ErpDefect).where(
        ErpDefect.entity_id == ent.id, ErpDefect.attribute_code == attr_code, ErpDefect.raw_value == raw,
        ErpDefect.resolved_at.is_(None))).scalar_one_or_none()
    if d is None:
        session.add(ErpDefect(entity_id=ent.id, attribute_code=attr_code, erp_column=column, raw_value=raw,
                              reason=reason, first_seen_at=now, last_seen_at=now))
    else:
        d.last_seen_at = now


def _start_launch_workflow(session: Session, ent: ProductEntity, stats: _Stats, now: datetime) -> None:
    wf = session.execute(select(WorkflowDefinition).where(
        WorkflowDefinition.code == "new_style_color_launch", WorkflowDefinition.enabled.is_(True))).scalar_one_or_none()
    if wf is None or not wf.steps:
        return
    exists = session.execute(select(WorkflowItem.id).where(
        WorkflowItem.workflow_id == wf.id, WorkflowItem.entity_id == ent.id, WorkflowItem.state == "open")).first()
    if exists:
        return
    step = wf.steps[0]
    session.add(WorkflowItem(workflow_id=wf.id, entity_id=ent.id, current_step_id=step.id, state="open",
                             due_at=now + timedelta(days=step.due_in_days), assigned_role=step.role_code,
                             history=[{"at": now.isoformat(), "event": "started", "step": step.label}]))
    stats.workflows += 1


def run_style_master_ingest(session: Session, source: SourceAdapter, requested_by: str = "job",
                            since: datetime | None = None, rows: Iterable[dict] | None = None) -> IngestRun:
    run = IngestRun(source=getattr(source, "name", "bluecherry"), status="running")
    session.add(run)
    session.flush()
    meta = load_metadata(session, force=True)
    stats = _Stats()
    now = utcnow()
    change_set = new_change_set(session, "ingest", requested_by, "Style Master ingest", source_ref=run.id)
    cache: dict[tuple, ProductEntity] = {}
    alias_seen: set[tuple[str, str]] = set()
    seen_entity_ids: set[str] = set()
    touched_style_colors: dict[str, ProductEntity] = {}
    new_style_colors: list[ProductEntity] = []
    try:
        for row in rows if rows is not None else source.read_changes(since):
            stats.rows += 1
            style = _s(row.get("style_number"))
            if not style:
                continue
            style = normalize_identifier(style) if "-" in style or " " in style else style.strip()
            color = _s(row.get("color_code"))
            size = _s(row.get("size"))
            sku = _s(row.get("sku"))
            upc = _s(row.get("upc"))
            erp_fields = {k: row.get(k) for k in ("division", "sub_division", "brand_name", "brand_classification",
                                                  "product_type", "season", "style_status") if k in row}
            scopes = evaluate_brand_scopes(erp_fields, meta.brand_scopes)
            family = _family_for(meta, row)
            cls_raw = _s(row.get("brand_classification"))
            cls_code = None
            if cls_raw:
                cls_code = map_raw_to_option(cls_raw, meta.value_mappings.get(("erp", "brand_classification"), {}),
                                             meta.option_codes("brand_classification")).option_code
            discontinued = _is_truthy(row.get("discontinued")) or "DISC" in str(row.get("style_status") or "").upper()
            is_prepack = bool(_s(row.get("pack_type"))) or (size is None and color and sku and any(
                t in (sku or "").upper() for t in ("AST", "PPK", "PREPACK")))

            # Style
            st, st_new = _upsert_entity(session, cache, "style", style, None, None, None, stats, now,
                                        family_code=family, brand_scopes=scopes, erp_fields=erp_fields,
                                        brand_classification=cls_code,
                                        label=_s(row.get("style_description")) or style)
            seen_entity_ids.add(st.id)
            _add_alias(session, alias_seen, st, style, "style")
            _add_alias(session, alias_seen, st, row.get("gms_style_no"), "gms")
            _add_alias(session, alias_seen, st, row.get("vendor_style"), "vendor")
            if st_new or st.lifecycle_status == "new":
                _write_erp_attributes(session, meta, st, row, stats, change_set, now)
            else:
                _write_erp_attributes(session, meta, st, row, stats, change_set, now)
            if discontinued:
                st.lifecycle_status = "discontinued"
            if not color:
                continue
            # Style-color
            label = f"{st.label} {_s(row.get('color_description')) or color}".strip()
            sc, sc_new = _upsert_entity(session, cache, "style_color", style, color, None, st, stats, now,
                                        family_code=family, brand_scopes=scopes, erp_fields=erp_fields,
                                        brand_classification=cls_code, label=label,
                                        entity_type="product")
            seen_entity_ids.add(sc.id)
            _add_alias(session, alias_seen, sc, f"{style}-{color}", "style_color")
            _add_alias(session, alias_seen, sc, row.get("parent_sku"), "style_color")
            _write_erp_attributes(session, meta, sc, row, stats, change_set, now)
            if discontinued:
                sc.lifecycle_status = "discontinued"
                stats.discontinued += 1
            elif sc_new:
                new_style_colors.append(sc)
            touched_style_colors[sc.id] = sc
            # SKU (a style-color may have no sizes yet, F8)
            if size or is_prepack:
                sku_label = f"{label} {size or ''}".strip()
                sk, _ = _upsert_entity(session, cache, "sku", style, color, size, sc, stats, now,
                                       sku=sku or (f"{style}-{color}-{size}" if size else None), upc=upc,
                                       family_code=family, brand_scopes=scopes, label=sku_label,
                                       entity_type="prepack" if is_prepack else "product")
                seen_entity_ids.add(sk.id)
                if is_prepack:
                    sc.entity_type = "prepack" if size is None else sc.entity_type
                    comps = _s(row.get("pack_components"))
                    if comps:
                        for comp in comps.split(","):
                            comp_norm = normalize_identifier(comp)
                            tgt = session.execute(select(IdentifierAlias).where(
                                IdentifierAlias.alias_type == "sku", IdentifierAlias.normalized == comp_norm)).scalar_one_or_none()
                            if tgt and not session.get(PrepackComponent, {"prepack_id": sk.id, "sku_id": tgt.entity_id}):
                                session.add(PrepackComponent(prepack_id=sk.id, sku_id=tgt.entity_id))
                _add_alias(session, alias_seen, sk, sk.sku, "sku")
                _add_alias(session, alias_seen, sk, upc, "upc")
                if size:
                    entry = meta.size_scale_entry(size)
                    sk.size_unmapped = entry is None
                    if entry is None:
                        stats.unmapped_sizes += 1
                        _record_defect(session, sk, "size", "size", size, "not_in_scale", now)
                _write_erp_attributes(session, meta, sk, row, stats, change_set, now)
                if discontinued:
                    sk.lifecycle_status = "discontinued"
            if stats.rows % 500 == 0:
                session.flush()
                log.info("ingest: %s rows", stats.rows)
        # Promote "new" to "active" once ERP attributes exist, start launch workflows for new style-colors
        for sc in new_style_colors:
            _start_launch_workflow(session, sc, stats, now)
        for ent in cache.values():
            if ent.lifecycle_status == "new" and ent.id not in {e.id for e in new_style_colors}:
                ent.lifecycle_status = "active"
        session.flush()
        refresh_snapshots(session, meta, list(touched_style_colors.values()))
        run.status = "succeeded"
    except Exception as exc:  # noqa: BLE001
        log.exception("ingest failed")
        run.status = "failed"
        run.error = str(exc)[:2000]
        raise
    finally:
        run.finished_at = utcnow()
        run.rows_read, run.created, run.updated = stats.rows, stats.created, stats.updated
        run.discontinued, run.placeholders_removed = stats.discontinued, stats.placeholders
        run.defects_found, run.workflows_started = stats.defects, stats.workflows
        run.report = {"placeholders_by_column": stats.placeholders_by_column, "unmapped_sizes": stats.unmapped_sizes,
                      "change_set_id": change_set.id}
        session.flush()
    return run


def latest_successful_load(session: Session) -> IngestRun | None:
    return session.execute(select(IngestRun).where(IngestRun.status == "succeeded")
                           .order_by(IngestRun.finished_at.desc()).limit(1)).scalar_one_or_none()
