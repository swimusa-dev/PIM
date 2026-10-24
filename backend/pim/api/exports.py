"""Phase 3 channel export API: target schemas (EXP-02), mappings and transforms (EXP-01), dry runs and validation
(EXP-04), publishes, feedback and health (EXP-05), delta and schedules (EXP-06), eligibility overrides (EXP-12)."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select

from pim.adapters.base import NotConfigured
from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.api.packages import safe_filename
from pim.api.schemas import EligibilityOverrideBody, MappingBody, RunBody, ScheduleBody
from pim.export import publishing
from pim.export.schema_loaders import SchemaLoadError, TargetSchema, diff_schemas, load_for_adapter
from pim.models import AppEvent, Channel, EligibilityOverride, ProductEntity, PublishItem, PublishRecord
from pim.models._common import utcnow
from pim.services.metadata import invalidate, load_metadata
from pim.services.readiness import check_eligibility, refresh_snapshots

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["exports"])


def _channel(session: Session, code: str) -> Channel:
    ch = session.get(Channel, code)
    if ch is None:
        raise HTTPException(404, "Unknown channel")
    return ch


def _require_edit_profile(user: CurrentUser, code: str) -> None:
    if not (user.can("admin_metadata") or (user.can("manage_channels") and user.channel_right(code, "edit_profile"))):
        raise HTTPException(403, "No right to edit this channel profile (RBAC-03)")


def _require_run(user: CurrentUser, code: str) -> None:
    if not (user.channel_right(code, "run") or user.can("admin_metadata")):
        raise HTTPException(403, "No right to run exports for this channel (RBAC-03)")


def publish_out(r: PublishRecord) -> dict:
    return {"id": r.id, "channel_code": r.channel_code, "channel_version": r.channel_version, "kind": r.kind, "mode": r.mode,
            "status": r.status, "created_by": r.created_by, "created_at": r.created_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None, "product_count": r.product_count,
            "valid_count": r.valid_count, "invalid_count": r.invalid_count, "selection": r.selection or {},
            "files": [{"name": f["name"], "size": f["size"], "kind": f["kind"]} for f in (r.files or [])],
            "summary": r.summary or {}, "external_batch_id": r.external_batch_id, "error": r.error, "package_id": r.package_id}


def item_out(i: PublishItem, label: str) -> dict:
    return {"id": i.id, "entity_id": i.entity_id, "label": label, "external_id": i.external_id, "status": i.status,
            "issues": i.issues or [], "errors": i.errors or [], "updated_at": i.updated_at.isoformat()}


# ---------------------------------------------------------------------------------------------------
# Schema (EXP-02)
# ---------------------------------------------------------------------------------------------------
@router.get("/channels/{code}/schema")
def get_schema(code: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    return TargetSchema.from_dict(_channel(session, code).target_schema).as_dict()


@router.post("/channels/{code}/schema/refresh")
async def refresh_schema(code: str, file: UploadFile | None = None, product_type: str | None = None,
                         session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    _require_edit_profile(user, code)
    ch = _channel(session, code)
    files: dict[str, bytes] = {}
    if file is not None:
        files[safe_filename(file.filename, "schema.bin")] = await file.read()
    try:
        schema = load_for_adapter(ch.adapter, files, product_type)
    except SchemaLoadError as exc:
        raise HTTPException(400, str(exc)) from exc
    before = TargetSchema.from_dict(ch.target_schema) if ch.target_schema else None
    diff = diff_schemas(before, schema)
    ch.target_schema = schema.as_dict()
    ch.last_schema_diff = {**diff, "at": utcnow().isoformat(), "by": user.email}
    if ch.adapter == "walmart_mp" and files:
        import json

        try:
            ch.config = {**(ch.config or {}), "raw_schema": json.loads(next(iter(files.values())).decode("utf-8-sig"))}
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    ch.version += 1
    session.add(AppEvent(kind="schema_refresh", source="exports", user_email=user.email, payload={"channel": code, "added": len(diff["added"]),
                                                                           "removed": len(diff["removed"]), "source": schema.source}))
    session.commit()
    invalidate()
    return {"schema": schema.as_dict(), "diff": diff}


@router.get("/channels/{code}/schema/diff")
def get_schema_diff(code: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    d = _channel(session, code).last_schema_diff or {}
    return {"added": d.get("added", []), "removed": d.get("removed", []), "required_changed": d.get("required_changed", []),
            "enum_changed": d.get("enum_changed", []), "at": d.get("at"), "by": d.get("by")}


# ---------------------------------------------------------------------------------------------------
# Mapping (EXP-01)
# ---------------------------------------------------------------------------------------------------
def mapping_out(meta: Metadata, ch: Channel) -> dict:
    schema = TargetSchema.from_dict(ch.target_schema)
    names = schema.by_name()
    mapping = ch.attribute_mapping or {}
    value_mappings = []
    for source in mapping:
        attr = meta.attributes.get(source.split(".", 1)[0])
        if attr and attr.data_type in ("single_select", "multi_select") and attr.option_list_code:
            ol = meta.option_lists.get(attr.option_list_code)
            opts = list(ol.values) if ol else []
            unmapped = [o.code for o in opts if not (o.channel_mappings or {}).get(ch.code)]
            codes = [o.code for o in opts]
            value_mappings.append({"attribute_code": attr.code, "list_code": attr.option_list_code, "mapped": len(codes) - len(unmapped),
                                   "unmapped": unmapped[:50]})
    mapped_targets = {t for t in mapping.values() if t}
    gaps = {"required_fields_unmapped": [f.name for f in schema.fields if f.required and f.name not in mapped_targets],
            "mapped_fields_missing_in_schema": sorted(t for t in mapped_targets if names and t not in names)}
    return {"attribute_mapping": mapping, "transforms": ch.transforms or [], "image_profile": ch.image_profile or {},
            "value_mappings": value_mappings, "gaps": gaps, "version": ch.version}


@router.get("/channels/{code}/mapping")
def get_mapping(code: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                user: CurrentUser = Depends(get_current_user)) -> dict:
    return mapping_out(meta, _channel(session, code))


@router.put("/channels/{code}/mapping")
def put_mapping(code: str, body: MappingBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                user: CurrentUser = Depends(get_current_user)) -> dict:
    _require_edit_profile(user, code)
    ch = _channel(session, code)
    for source in body.attribute_mapping:
        base = source.split(".", 1)[0]
        if base not in meta.attributes and not source.startswith(("core.", "erp.")) and base not in ("style_number", "color_code", "size", "sku", "upc"):
            raise HTTPException(400, f"Unknown attribute in mapping: {source}")
    for tr in body.transforms:
        if tr.get("op") not in ("concatenate", "format", "unit_convert", "conditional", "case", "truncate", "value_map") or not tr.get("target"):
            raise HTTPException(400, f"Invalid transform: {tr}")
    ch.attribute_mapping = body.attribute_mapping
    ch.transforms = body.transforms
    if body.image_profile is not None:
        bad = [s for s in body.image_profile.get("shot_types", []) if s not in meta.shot_types]
        if bad:
            raise HTTPException(400, f"Unknown shot types: {', '.join(bad)}")
        ch.image_profile = body.image_profile
    ch.version += 1
    session.commit()
    invalidate()
    return mapping_out(load_metadata(session, force=True), ch)


# ---------------------------------------------------------------------------------------------------
# Runs (EXP-04, EXP-05)
# ---------------------------------------------------------------------------------------------------
def _run(session: Session, meta: Metadata, user: CurrentUser, code: str, body: RunBody, kind: str) -> dict:
    ch = _channel(session, code)
    if body.mode not in ("delta", "full"):
        raise HTTPException(400, "mode must be delta or full")
    if not body.selection or not any(body.selection.get(k) for k in ("view_id", "entity_ids", "changed_since")):
        raise HTTPException(400, "selection needs view_id, entity_ids or changed_since")
    if kind == "publish" and publishing.running_run(session, code):
        raise HTTPException(409, "A run for this channel is already in progress")
    rec = publishing.start_run(session, ch, kind, body.mode, user.email, body.selection)
    session.commit()
    publishing.execute_run(session, meta, ch, rec, preview=max(0, min(body.preview, 50)), send=(kind == "publish"), user=user)
    session.commit()
    return publish_out(rec)


@router.post("/channels/{code}/dry-run")
def dry_run(code: str, body: RunBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
            user: CurrentUser = Depends(get_current_user)) -> dict:
    if not (user.channel_right(code, "run") or user.channel_right(code, "edit_profile") or user.can("admin_metadata")):
        raise HTTPException(403, "No right to run exports for this channel (RBAC-03)")
    return _run(session, meta, user, code, body, "dry_run")


@router.post("/channels/{code}/publish")
def publish(code: str, body: RunBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
            user: CurrentUser = Depends(get_current_user)) -> dict:
    _require_run(user, code)
    return _run(session, meta, user, code, body, "publish")


@router.get("/publishes")
def list_publishes(channel: str | None = None, kind: str | None = None, page: int = 1, page_size: int = 50,
                   session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    q = select(PublishRecord)
    if channel:
        q = q.where(PublishRecord.channel_code == channel)
    if kind:
        q = q.where(PublishRecord.kind == kind)
    total = session.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = session.execute(q.order_by(PublishRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"rows": [publish_out(r) for r in rows], "total": total}


def _labels(session: Session, items: list[PublishItem]) -> dict[str, str]:
    ids = {i.entity_id for i in items}
    return {e.id: e.label for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_(ids))).scalars()} if ids else {}


@router.get("/publishes/{publish_id}")
def get_publish(publish_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    rec = session.get(PublishRecord, publish_id)
    if rec is None:
        raise HTTPException(404, "Publish not found")
    items = session.execute(select(PublishItem).where(PublishItem.publish_id == rec.id).order_by(PublishItem.status, PublishItem.entity_id).limit(500)).scalars().all()
    labels = _labels(session, items)
    return {**publish_out(rec), "items": [item_out(i, labels.get(i.entity_id, i.entity_id)) for i in items]}


@router.get("/publishes/{publish_id}/items")
def publish_items(publish_id: str, status: str | None = None, page: int = 1, page_size: int = 100,
                  session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    q = select(PublishItem).where(PublishItem.publish_id == publish_id)
    if status:
        q = q.where(PublishItem.status == status)
    total = session.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    items = session.execute(q.order_by(PublishItem.entity_id).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    labels = _labels(session, items)
    return {"rows": [item_out(i, labels.get(i.entity_id, i.entity_id)) for i in items], "total": total}


@router.get("/publishes/{publish_id}/files/{name}")
def publish_file(publish_id: str, name: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)):
    rec = session.get(PublishRecord, publish_id)
    if rec is None:
        raise HTTPException(404, "Publish not found")
    f = next((x for x in (rec.files or []) if x["name"] == name), None)
    if f is None or not f.get("path"):
        raise HTTPException(404, "File not found")
    data = publishing.storage().read(f["path"])
    media = {"json": "application/json", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}.get(name.rsplit(".", 1)[-1], "text/csv")
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{safe_filename(name, "file")}"'})


@router.post("/publishes/{publish_id}/feedback")
async def publish_feedback(publish_id: str, file: UploadFile | None = None, session: Session = Depends(get_session),
                           meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    rec = session.get(PublishRecord, publish_id)
    if rec is None:
        raise HTTPException(404, "Publish not found")
    ch = _channel(session, rec.channel_code)
    _require_run(user, ch.code)
    try:
        if file is not None:
            rows = publishing.parse_feedback_file(safe_filename(file.filename, "feedback.csv"), await file.read())
            result = publishing.apply_feedback(session, meta, ch, rec, rows, source=f"file:{user.email}")
        else:
            result = publishing.poll_feedback(session, meta, ch, rec)
    except NotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, f"Could not read the feedback file: {exc}") from exc
    session.commit()
    return result


@router.get("/channels/{code}/health")
def channel_health(code: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    return publishing.channel_health(session, _channel(session, code))


# ---------------------------------------------------------------------------------------------------
# Delta and schedule (EXP-06)
# ---------------------------------------------------------------------------------------------------
@router.get("/channels/{code}/delta")
def channel_delta(code: str, view_id: str | None = None, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                  user: CurrentUser = Depends(get_current_user)) -> dict:
    ch = _channel(session, code)
    base = publishing.resolve_selection(session, {"view_id": view_id}) if view_id else None
    rows = publishing.delta_candidates(session, meta, ch, base)
    return {"changed": len(rows), "sample": rows[:50], "since": (lambda d: d.isoformat() if d else None)(publishing.last_success_at(session, code))}


@router.get("/channels/{code}/schedule")
def get_schedule(code: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    return publishing.schedule_out(_channel(session, code))


@router.put("/channels/{code}/schedule")
def put_schedule(code: str, body: ScheduleBody, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    _require_edit_profile(user, code)
    ch = _channel(session, code)
    if body.mode not in ("delta", "full"):
        raise HTTPException(400, "mode must be delta or full")
    if body.enabled and not body.every_hours and body.at_hour is None:
        raise HTTPException(400, "Set every_hours or at_hour to enable the schedule")
    if body.at_hour is not None and not 0 <= body.at_hour <= 23:
        raise HTTPException(400, "at_hour must be 0 to 23")
    ch.schedule = {**publishing.schedule_out(ch), **body.model_dump()}
    session.commit()
    invalidate()
    return publishing.schedule_out(ch)


@router.post("/channels/{code}/schedule/run-now")
def run_now(code: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
            user: CurrentUser = Depends(get_current_user)) -> dict:
    _require_run(user, code)
    ch = _channel(session, code)
    from pim.services.jobs import trigger_job

    run = trigger_job(session, "channel_export", user.email, {"channel_code": code, "force": "true"})
    if run.status == "running" and run.databricks_run_id:
        session.commit()
        return {"status": "started", "job_run_id": run.id}
    result = publishing.run_scheduled(session, meta, ch, requested_by=user.email, force=True)
    run.status = "succeeded" if result["status"] == "started" else "skipped"
    run.finished_at, run.report = utcnow(), result
    session.commit()
    return result


# ---------------------------------------------------------------------------------------------------
# Eligibility (EXP-12)
# ---------------------------------------------------------------------------------------------------
def override_out(o: EligibilityOverride) -> dict:
    return {"id": o.id, "entity_id": o.entity_id, "channel_code": o.channel_code, "reason": o.reason, "approved_by": o.approved_by,
            "created_at": o.created_at.isoformat(), "expires_at": o.expires_at.isoformat() if o.expires_at else None}


@router.get("/products/{entity_id}/eligibility")
def product_eligibility(entity_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                        user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = session.get(ProductEntity, entity_id)
    if ent is None or not user.in_brand_scope(ent.brand_scopes or []):
        raise HTTPException(404, "Product not found")
    style = session.get(ProductEntity, ent.parent_id) if ent.parent_id else None
    now = utcnow()
    overrides = {o.channel_code: o for o in session.execute(select(EligibilityOverride).where(EligibilityOverride.entity_id == ent.id)).scalars()}
    out = {}
    for ch in meta.channels.values():
        reasons = check_eligibility(ch, ent, style)
        o = overrides.get(ch.code)
        active = o is not None and (o.expires_at is None or o.expires_at > now)
        out[ch.code] = {"eligible": not reasons or active, "reasons": reasons, "override": override_out(o) if o else None,
                        "override_active": active}
    return {"channels": out}


@router.post("/products/{entity_id}/eligibility-override")
def create_override(entity_id: str, body: EligibilityOverrideBody, session: Session = Depends(get_session),
                    meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    if not user.can("admin_metadata"):
        raise HTTPException(403, "Forcing eligibility needs a PIM Admin (EXP-12)")
    ent = session.get(ProductEntity, entity_id)
    if ent is None:
        raise HTTPException(404, "Product not found")
    if body.channel_code not in meta.channels:
        raise HTTPException(404, "Unknown channel")
    if len(body.reason.strip()) < 5:
        raise HTTPException(400, "A reason is required")
    expires = None
    if body.expires_at:
        try:
            expires = datetime.fromisoformat(body.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(400, "expires_at must be an ISO date") from exc
    o = session.execute(select(EligibilityOverride).where(EligibilityOverride.entity_id == ent.id,
                                                          EligibilityOverride.channel_code == body.channel_code)).scalar_one_or_none()
    if o is None:
        o = EligibilityOverride(entity_id=ent.id, channel_code=body.channel_code)
        session.add(o)
    o.reason, o.approved_by, o.expires_at, o.created_at = body.reason.strip(), user.email, expires, utcnow()
    session.add(AppEvent(kind="eligibility_override", source="exports", user_email=user.email,
                         payload={"entity_id": ent.id, "label": ent.label, "channel": body.channel_code, "reason": o.reason}))
    session.flush()
    refresh_snapshots(session, meta, [ent])
    session.commit()
    return override_out(o)


@router.delete("/eligibility-overrides/{override_id}")
def delete_override(override_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                    user: CurrentUser = Depends(get_current_user)) -> dict:
    if not user.can("admin_metadata"):
        raise HTTPException(403, "PIM Admin only")
    o = session.get(EligibilityOverride, override_id)
    if o is None:
        raise HTTPException(404, "Override not found")
    ent = session.get(ProductEntity, o.entity_id)
    session.add(AppEvent(kind="eligibility_override_removed", source="exports", user_email=user.email, payload={"entity_id": o.entity_id, "channel": o.channel_code}))
    session.delete(o)
    session.flush()
    if ent:
        refresh_snapshots(session, meta, [ent])
    session.commit()
    return {"deleted": True}
