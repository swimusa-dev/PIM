"""IMP-09 Style Master ingest with IMP-10 placeholder normalization, IMP-11 value mapping and ERP defects,
DM-01 hierarchy and identifier aliases, DM-14 size scale check, RBAC-04 brand scope assignment, DM-12 carryover
hook, and the New style-color launch workflow start (DM-07).

Never deletes: discontinued products are flagged. Never writes back to BlueCherry (P1).
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
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
from pim.services.metadata import NON_SIZE_VALUES, PREPACK_SIZES, Metadata, load_metadata
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


def _rule_fields(rule: dict) -> list[str]:
    """The ERP fields a family rule reads: `fields` (a list, tried in turn) or the older single `field`."""
    f = rule.get("fields") or rule.get("field")
    return [f] if isinstance(f, str) else list(f or [])


def _rule_matches(rule: dict, row: dict) -> bool:
    for field in _rule_fields(rule):
        val = str(row.get(field, "") or "").upper()
        if not val:
            continue
        if "in" in rule and val in {str(x).upper() for x in rule["in"]}:
            return True
        if "eq" in rule and val == str(rule["eq"]).upper():
            return True
        if "contains" in rule and str(rule["contains"]).upper() in val:
            return True
        if any(re.search(p, val) for p in rule.get("regex_any", ())):
            return True
    return False


def _family_for(meta: Metadata, row: dict) -> str | None:
    """First family whose rule matches, in `priority` order (lower first; the default is 100, then by code)."""
    ruled = sorted((f for f in meta.families.values() if f.erp_match),
                   key=lambda f: (f.erp_match.get("priority", 100), f.code))
    for fam in ruled:
        if _rule_matches(fam.erp_match, row):
            return fam.code
    return "unassigned" if "unassigned" in meta.families else None


def _normalized_style(raw: str) -> str:
    return normalize_identifier(raw) if "-" in raw or " " in raw else raw.strip()


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
                          change_set, now: datetime,
                          erp_last: dict[tuple[str, str], tuple[Any, int]] | None = None) -> None:
    """Map Style Master columns to ERP-owned attributes through AttributeDefinition.erp_column (IMP-09/10/11).

    A style repeats on each of its color and size rows and a color on each size row, usually with the same values.
    `erp_last` remembers the raw value last written per entity and attribute: the same value again cannot change a
    stored value, its history or its defect, so only the counters are replayed and the two database lookups are
    skipped. A different value, including a return to an earlier one, is written as before (last row wins)."""
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
        key = (ent.id, attr.code)
        if erp_last is not None and key in erp_last and erp_last[key][0] == raw:
            stats.defects += erp_last[key][1]
            continue
        defects_before = stats.defects
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
        if erp_last is not None:
            erp_last[key] = (raw, stats.defects - defects_before)


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
    from pim.services.workflow import start_workflow

    wf = session.execute(select(WorkflowDefinition).where(
        WorkflowDefinition.code == "new_style_color_launch", WorkflowDefinition.enabled.is_(True))).scalar_one_or_none()
    if wf is None or not wf.steps:
        return
    if start_workflow(session, load_metadata(session), wf, ent, by="ingest") is not None:
        stats.workflows += 1


def close_baseline_launch_items(session: Session) -> int:
    """Cancel the launch tasks the first load started for the whole existing catalog. They were never worked
    (the history holds only the start by the ingest) and were created while the first successful load ran, so tasks
    started by later loads, or touched by anyone, stay. Safe to repeat: a cancelled task no longer matches."""
    base = session.execute(select(IngestRun).where(IngestRun.status == "succeeded")
                           .order_by(IngestRun.started_at.asc()).limit(1)).scalar_one_or_none()
    if base is None or base.finished_at is None:
        return 0
    now = utcnow()
    closed = 0
    items = session.execute(select(WorkflowItem).join(WorkflowDefinition, WorkflowDefinition.id == WorkflowItem.workflow_id)
                            .where(WorkflowDefinition.code == "new_style_color_launch", WorkflowItem.state == "open",
                                   WorkflowItem.created_at >= base.started_at, WorkflowItem.created_at <= base.finished_at)
                            ).scalars()
    for item in items:
        if len(item.history) != 1 or item.history[0].get("event") != "started" or item.history[0].get("by") != "ingest":
            continue
        item.state, item.current_step_id, item.due_at, item.assigned_role = "cancelled", None, None, None
        item.history = [*item.history, {"at": now.isoformat(), "event": "cancelled",
                                        "reason": "started by the first load for the existing catalog"}]
        closed += 1
    session.flush()
    return closed


def _columns_read(meta: Metadata) -> set[str]:
    """Style Master columns the ingest reads besides the key aliases, so a wide source can be narrowed."""
    cols = {a.erp_column for a in meta.attributes.values() if a.erp_column and a.status != "deprecated"}
    cols |= _family_columns(meta)
    return cols


def _family_columns(meta: Metadata) -> set[str]:
    """Style Master columns the family rules read."""
    return {c for f in meta.families.values() for c in _rule_fields(f.erp_match or {}) if c}


def _ingest_rows(session: Session, meta: Metadata, change_set: Any, row_iter: Iterable[dict], stats: _Stats,
                 now: datetime, launch: bool = True) -> None:
    """Load one chunk of Style Master rows: entities, aliases and ERP values, then the lifecycle roll-up, launch
    workflows and readiness for what the chunk touched. The caller commits. A style's rows all fall in one chunk
    (the Delta source slices by style number), so the per-style roll-up below is complete within a chunk."""
    cache: dict[tuple, ProductEntity] = {}
    alias_seen: set[tuple[str, str]] = set()
    seen_entity_ids: set[str] = set()
    touched_style_colors: dict[str, ProductEntity] = {}
    new_style_colors: list[ProductEntity] = []
    style_live: dict[str, bool] = {}  # style id -> at least one non-discontinued row seen this chunk
    # (entity id, attribute code) -> (raw value, defects it raised) of the last ERP write in this chunk
    erp_last: dict[tuple[str, str], tuple[Any, int]] = {}

    for row in row_iter:
        stats.rows += 1
        style = _s(row.get("style_number"))
        if not style:
            continue
        style = _normalized_style(style)
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
        size_is_pack = bool(size) and size.upper() in PREPACK_SIZES
        is_prepack = bool(_s(row.get("pack_type"))) or size_is_pack or (size is None and color and sku and any(
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
        _write_erp_attributes(session, meta, st, row, stats, change_set, now, erp_last)
        style_live[st.id] = style_live.get(st.id, False) or not discontinued
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
        _write_erp_attributes(session, meta, sc, row, stats, change_set, now, erp_last)
        if discontinued:
            sc.lifecycle_status = "discontinued"
            stats.discontinued += 1
        elif sc_new:
            new_style_colors.append(sc)
        elif sc.lifecycle_status == "discontinued":
            sc.lifecycle_status = "active"  # reactivated in the ERP
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
            if size_is_pack or (size and size.upper() in NON_SIZE_VALUES):
                sk.size_unmapped = False
            elif size:
                entry = meta.size_scale_entry(size)
                sk.size_unmapped = entry is None
                if entry is None:
                    stats.unmapped_sizes += 1
                    _record_defect(session, sk, "size", "size", size, "not_in_scale", now)
            _write_erp_attributes(session, meta, sk, row, stats, change_set, now, erp_last)
            if discontinued:
                sk.lifecycle_status = "discontinued"
            elif sk.lifecycle_status == "discontinued":
                sk.lifecycle_status = "active"
        if stats.rows % 500 == 0:
            session.flush()
            log.info("ingest: %s rows", stats.rows)
    # A style is discontinued only when every row seen for it this load is discontinued (never because one
    # old color is); a style with any live color stays, or becomes, active.
    styles_by_id = {e.id: e for e in cache.values() if e.level == "style"}
    for st_id, live in style_live.items():
        st = styles_by_id.get(st_id)
        if st is None:
            continue
        if not live:
            st.lifecycle_status = "discontinued"
        elif st.lifecycle_status == "discontinued":
            st.lifecycle_status = "active"
    # Promote "new" to "active" once ERP attributes exist, start launch workflows for new style-colors
    for sc in new_style_colors if launch else ():
        _start_launch_workflow(session, sc, stats, now)
    for ent in cache.values():
        if ent.lifecycle_status == "new" and ent.id not in {e.id for e in new_style_colors}:
            ent.lifecycle_status = "active"
    session.flush()
    refresh_snapshots(session, meta, list(touched_style_colors.values()))


SLICE_ATTEMPTS = 3
RESUME_WINDOW = timedelta(hours=48)


def _resumable_slices(session: Session, source_name: str, total: int) -> tuple[set[int], str | None]:
    """Slices a previous failed load already committed, so a re-run continues instead of starting over. Only the
    latest run counts, only when it failed (never after a later success) and only within RESUME_WINDOW."""
    prev = session.execute(select(IngestRun).where(IngestRun.source == source_name)
                           .order_by(IngestRun.started_at.desc()).limit(1)).scalar_one_or_none()
    if prev is None or prev.status != "failed" or utcnow() - prev.started_at > RESUME_WINDOW:
        return set(), None
    report = prev.report or {}
    if report.get("slices_total") != total:
        return set(), None
    return {int(i) for i in report.get("completed_slices", [])}, prev.id


def run_style_master_ingest(session: Session, source: SourceAdapter, requested_by: str = "job",
                            since: datetime | None = None, rows: Iterable[dict] | None = None,
                            resume: bool = True, launch_workflows: bool | None = None) -> IngestRun:
    """Load the Style Master. A source that offers `slice_ids()` and `read_slice(id, since)` (the Delta source) is
    loaded one slice at a time: each slice commits, is retried if the database connection drops, and is recorded in
    the run report so a failed load resumes where it stopped. Any other source loads as a single chunk.

    Launch workflows are for style-colors that appear after the catalog exists. The first successful load only builds
    the catalog (every style-color is new to it), so it starts none, unless `launch_workflows` says otherwise."""
    sliced = rows is None and hasattr(source, "slice_ids")
    if hasattr(source, "wanted_columns"):
        source.wanted_columns = _columns_read(load_metadata(session, force=True))
    slice_ids: list[int | None] = list(source.slice_ids()) if sliced else [None]
    done, resumed_from = _resumable_slices(session, getattr(source, "name", "bluecherry"), len(slice_ids)) \
        if sliced and resume else (set(), None)
    completed: list[int] = sorted(done)

    start_workflows: bool = False

    def report() -> dict:
        return {"slices_total": len(slice_ids) if sliced else 0, "completed_slices": list(completed),
                "resumed_from": resumed_from, "launch_workflows": start_workflows}

    run = IngestRun(source=getattr(source, "name", "bluecherry"), status="running", report=report())
    session.add(run)
    session.flush()
    change_set = new_change_set(session, "ingest", requested_by, "Style Master ingest", source_ref=run.id)
    if launch_workflows is None:
        start_workflows = session.execute(select(IngestRun.id).where(
            IngestRun.status == "succeeded", IngestRun.id != run.id).limit(1)).first() is not None
    else:
        start_workflows = launch_workflows
    run.report = report()
    session.commit()  # the run row and its change set outlive a later rollback, so a failure can be recorded on it
    stats = _Stats()
    now = utcnow()
    try:
        for sid in slice_ids:
            if sid in done:
                log.info("ingest: slice %s already loaded by run %s, skipped", sid, resumed_from)
                continue
            for attempt in range(1, SLICE_ATTEMPTS + 1):
                before = copy.deepcopy(stats)
                try:
                    meta = load_metadata(session, force=True)
                    if sid is not None and sliced:
                        chunk = source.read_slice(sid, since)
                    else:
                        chunk = rows if rows is not None else source.read_changes(since)
                    _ingest_rows(session, meta, change_set, chunk, stats, now, start_workflows)
                    if sliced:
                        completed.append(sid)
                        run.report = report()
                    session.commit()
                    break
                except OperationalError as exc:
                    # The database dropped the connection mid-slice: nothing from the slice was committed, so
                    # roll back, reconnect (the pool hands out a fresh connection) and read the slice again.
                    session.rollback()
                    stats = before
                    if not sliced or attempt == SLICE_ATTEMPTS:
                        raise
                    log.warning("ingest: slice %s hit a database error (attempt %s of %s), retrying: %s",
                                sid, attempt, SLICE_ATTEMPTS, str(exc)[:200])
            if sliced:
                log.info("ingest: slice %s of %s committed (%s rows so far)", len(completed), len(slice_ids), stats.rows)
        run.status = "succeeded"
        _finalize_run(run, stats, change_set.id)
        run.report = {**run.report, **report()}
        session.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("ingest failed")
        # Slices already committed stay (and are listed in the report for a resume); the slice in flight is rolled
        # back. The failure is recorded on the run row so it does not stay "running" forever (GOV-04).
        session.rollback()
        run.status = "failed"
        run.error = str(exc)[:2000]
        _finalize_run(run, stats, None)
        run.report = {**run.report, **report()}
        session.commit()
        raise
    return run


def _finalize_run(run: IngestRun, stats: _Stats, change_set_id: str | None) -> None:
    run.finished_at = utcnow()
    run.rows_read, run.created, run.updated = stats.rows, stats.created, stats.updated
    run.discontinued, run.placeholders_removed = stats.discontinued, stats.placeholders
    run.defects_found, run.workflows_started = stats.defects, stats.workflows
    run.report = {"placeholders_by_column": stats.placeholders_by_column, "unmapped_sizes": stats.unmapped_sizes,
                  "change_set_id": change_set_id}


def latest_successful_load(session: Session) -> IngestRun | None:
    return session.execute(select(IngestRun).where(IngestRun.status == "succeeded")
                           .order_by(IngestRun.finished_at.desc()).limit(1)).scalar_one_or_none()


def refresh_families(session: Session, source: SourceAdapter) -> dict[str, Any]:
    """Re-assign every loaded entity's family from the source, without loading the Style Master again. Reads only the
    columns the family rules need, works out one family per style (a style's first non-unassigned match) and
    updates the style and all of its style-colors and SKUs in bulk. Safe to repeat: entities already in the right
    family are not touched."""
    meta = load_metadata(session, force=True)
    if hasattr(source, "wanted_columns"):
        source.wanted_columns = _family_columns(meta)
    by_style: dict[str, str] = {}
    rows = 0
    for row in source.read_changes():
        rows += 1
        style = _s(row.get("style_number"))
        if not style:
            continue
        style = _normalized_style(style)
        fam = _family_for(meta, row) or "unassigned"
        if by_style.get(style, "unassigned") == "unassigned":
            by_style[style] = fam
    styles_by_family: dict[str, list[str]] = {}
    for style, fam in by_style.items():
        styles_by_family.setdefault(fam, []).append(style)
    changed = 0
    for fam, styles in styles_by_family.items():
        for i in range(0, len(styles), 1000):
            result = session.execute(update(ProductEntity).where(
                ProductEntity.style_number.in_(styles[i:i + 1000]),
                ProductEntity.family_code.is_distinct_from(fam)).values(family_code=fam))
            changed += result.rowcount or 0
    session.flush()
    return {"rows_read": rows, "styles": len(by_style), "entities_changed": changed,
            "styles_by_family": {f: len(v) for f, v in sorted(styles_by_family.items())}}
