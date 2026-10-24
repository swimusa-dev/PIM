"""Import wizard API (IMP-01 to IMP-08) and keyed worksheets (IMP-12)."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select

from pim.adapters.base import NotConfigured
from pim.adapters.shopify_admin import ShopifyAdminClient, parse_product_csv
from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.auth.identity import require_permission
from pim.config import get_settings
from pim.imports.batches import (
    add_file,
    apply_template,
    batch_out,
    create_batch,
    reparse_files,
    row_out,
    rows_from_shopify,
    save_template,
    set_mapping,
)
from pim.imports.mapping import suggest_mappings
from pim.imports.matching import confirm_row, match_batch
from pim.imports.survivorship import commit_batch, decide_conflicts, review_batch, rollback_batch
from pim.imports.validation import error_file, save_value_mappings, validate_batch, value_mapping_report
from pim.imports.worksheet import build_worksheet
from pim.models import (
    ImportBatch,
    ImportConflict,
    ImportRow,
    ImportSource,
    MappingTemplate,
    ProductEntity,
    WorksheetExport,
)
from pim.services.bulk import resolve_entities
from pim.services.collab import notify
from pim.services.jobs import trigger_job
from pim.services.storage import Storage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["imports"])


def _storage() -> Storage:
    return Storage(get_settings().import_volume)


def _batch_or_404(session: Session, batch_id: str) -> ImportBatch:
    b = session.get(ImportBatch, batch_id)
    if b is None:
        raise HTTPException(404, "Batch not found")
    return b


def _src_out(s: ImportSource) -> dict:
    return {"code": s.code, "label": s.label, "kind": s.kind, "default_policy": s.default_policy or {}, "trust_rank": s.trust_rank}


def _tpl_out(t: MappingTemplate) -> dict:
    return {"id": t.id, "source_code": t.source_code, "name": t.name, "structure_signature": t.structure_signature, "header_row": t.header_row,
            "group_header_row": t.group_header_row, "data_start_row": t.data_start_row, "columns": t.columns or [], "match_keys": t.match_keys or [],
            "unmatched_policy": t.unmatched_policy, "level": t.level, "version": t.version, "created_by": t.created_by}


class SourceBody(BaseModel):
    code: str
    label: str
    kind: str = "supplier"
    default_policy: dict = {}
    trust_rank: int = 3


class TemplateBody(BaseModel):
    name: str
    batch_id: str | None = None
    source_code: str | None = None
    columns: list[dict] | None = None
    match_keys: list[str] | None = None
    unmatched_policy: str | None = None
    level: str | None = None


class MappingBody(BaseModel):
    mapping: list[dict]
    match_keys: list[str] = []
    options: dict = {}
    template_id: str | None = None
    precedence: list[int] | None = None
    files: list[dict] | None = None  # header-row edits from the Upload step: [{index, header_row, group_header_row}]


class ValueMappingsBody(BaseModel):
    items: list[dict]


class RowBody(BaseModel):
    entity_id: str | None = None
    action: str | None = None


class ConflictBody(BaseModel):
    conflict_ids: list[str]
    decision: str
    value: object | None = None


class WorksheetBody(BaseModel):
    selection: dict
    group_codes: list[str]
    include_erp_context: bool = True


# ---- sources and templates ------------------------------------------------------------------------------
@router.get("/imports/sources")
def list_sources(session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    return [_src_out(s) for s in session.execute(select(ImportSource).order_by(ImportSource.label)).scalars()]


@router.post("/imports/sources")
@router.put("/imports/sources/{code}")
def upsert_source(body: SourceBody, code: str | None = None, session: Session = Depends(get_session),
                  user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    s = session.get(ImportSource, body.code)
    if s is None:
        s = ImportSource(**body.model_dump())
        session.add(s)
    else:
        for k, v in body.model_dump().items():
            setattr(s, k, v)
    session.commit()
    return _src_out(s)


@router.get("/imports/templates")
def list_templates(source: str | None = None, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    q = select(MappingTemplate).order_by(MappingTemplate.source_code, MappingTemplate.name)
    if source:
        q = q.where(MappingTemplate.source_code == source)
    return [_tpl_out(t) for t in session.execute(q).scalars()]


@router.post("/imports/templates")
def create_template(body: TemplateBody, session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("import"))) -> dict:
    if body.batch_id:
        tpl = save_template(session, _batch_or_404(session, body.batch_id), body.name, user)
    else:
        if not body.source_code:
            raise HTTPException(400, "source_code is required without a batch")
        tpl = MappingTemplate(source_code=body.source_code, name=body.name, structure_signature="manual", columns=body.columns or [],
                              match_keys=body.match_keys or [], unmatched_policy=body.unmatched_policy or "update_only",
                              level=body.level or "style_color", created_by=user.email)
        session.add(tpl)
    session.commit()
    return _tpl_out(tpl)


@router.put("/imports/templates/{template_id}")
def update_template(template_id: str, body: TemplateBody, session: Session = Depends(get_session),
                    user: CurrentUser = Depends(require_permission("import"))) -> dict:
    tpl = session.get(MappingTemplate, template_id)
    if tpl is None:
        raise HTTPException(404, "Template not found")
    tpl.name = body.name
    for k in ("columns", "match_keys", "unmatched_policy", "level"):
        v = getattr(body, k)
        if v is not None:
            setattr(tpl, k, v)
    tpl.version += 1
    session.commit()
    return _tpl_out(tpl)


@router.delete("/imports/templates/{template_id}")
def delete_template(template_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("import"))) -> dict:
    tpl = session.get(MappingTemplate, template_id)
    if tpl:
        session.delete(tpl)
        session.commit()
    return {"deleted": template_id}


# ---- batches -----------------------------------------------------------------------------------------------
@router.get("/imports/batches")
def list_batches(status: str | None = None, source: str | None = None, page: int = 1, page_size: int = 50,
                 session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    q = select(ImportBatch)
    if status:
        q = q.where(ImportBatch.status == status)
    if source:
        q = q.where(ImportBatch.source_code == source)
    total = session.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = session.execute(q.order_by(ImportBatch.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"rows": [batch_out(b) for b in rows], "total": total}


@router.post("/imports/batches")
async def create_batch_endpoint(file: list[UploadFile] = File(default=[]), source_code: str = Form("supplier"), level: str = Form("style_color"),
                                header_row: int | None = Form(None), session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                                user: CurrentUser = Depends(require_permission("import"))) -> dict:
    try:
        batch = create_batch(session, user, source_code, level)
        storage = _storage()
        for f in file:
            add_file(session, meta, batch, f.filename or "upload", await f.read(), storage, header_row)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return batch_out(batch)


@router.post("/imports/batches/{batch_id}/files")
async def add_file_endpoint(batch_id: str, file: list[UploadFile] = File(default=[]), header_row: int | None = Form(None),
                            session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                            user: CurrentUser = Depends(require_permission("import"))) -> dict:
    batch = _batch_or_404(session, batch_id)
    if batch.status in ("committing", "committed", "rolled_back"):
        raise HTTPException(409, "Batch is already committed")
    storage = _storage()
    for f in file:
        add_file(session, meta, batch, f.filename or "upload", await f.read(), storage, header_row)
    session.commit()
    return batch_out(batch)


@router.post("/imports/batches/{batch_id}/shopify-pull")
async def shopify_pull(batch_id: str, file: UploadFile | None = None, session: Session = Depends(get_session),
                       user: CurrentUser = Depends(require_permission("import"))) -> dict:
    batch = _batch_or_404(session, batch_id)
    if file is not None:
        snap = parse_product_csv(await file.read())
    else:
        try:
            snap = ShopifyAdminClient().snapshot_via_bulk()
        except NotConfigured as exc:
            raise HTTPException(409, f"{exc}. Upload the store's product CSV export instead.") from exc
    n = rows_from_shopify(session, batch, snap)
    session.commit()
    return {**batch_out(batch), "rows": n}


@router.get("/imports/batches/{batch_id}")
def get_batch(batch_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    return batch_out(_batch_or_404(session, batch_id))


@router.get("/imports/batches/{batch_id}/suggest-mapping")
def suggest(batch_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
            user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    batch = _batch_or_404(session, batch_id)
    cols = [c["name"] for f in (batch.files or []) for c in f.get("columns", [])]
    already = {s for m in (batch.mapping or []) for s in (m.get("sources") or [])}
    return suggest_mappings(cols, meta, batch.level, already, threshold=get_settings().ai_mapping_confidence_threshold)


@router.put("/imports/batches/{batch_id}/mapping")
def put_mapping(batch_id: str, body: MappingBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                user: CurrentUser = Depends(require_permission("import"))) -> dict:
    batch = _batch_or_404(session, batch_id)
    if body.files:
        reparse_files(session, batch, body.files, _storage())
    if body.template_id:
        tpl = session.get(MappingTemplate, body.template_id)
        if tpl is None:
            raise HTTPException(404, "Template not found")
        apply_template(batch, tpl)
    missing = set_mapping(session, meta, batch, body.mapping, body.match_keys, body.options, body.template_id, body.precedence)
    if missing:
        session.commit()
        raise HTTPException(400, f"Required attributes still unmapped: {', '.join(missing)}")
    session.commit()
    return batch_out(batch)


@router.get("/imports/batches/{batch_id}/value-mappings")
def get_value_mappings(batch_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                       user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"lists": value_mapping_report(session, meta, _batch_or_404(session, batch_id))}


@router.put("/imports/batches/{batch_id}/value-mappings")
def put_value_mappings(batch_id: str, body: ValueMappingsBody, session: Session = Depends(get_session),
                       user: CurrentUser = Depends(require_permission("import"))) -> dict:
    batch = _batch_or_404(session, batch_id)
    n = save_value_mappings(session, batch.source_code, body.items, user.email)
    session.commit()
    from pim.services.metadata import invalidate

    invalidate()
    return {"saved": n}


@router.post("/imports/batches/{batch_id}/validate")
def validate(batch_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
             user: CurrentUser = Depends(require_permission("import"))) -> dict:
    batch = _batch_or_404(session, batch_id)
    if not batch.mapping:
        raise HTTPException(409, "Map the columns first")
    validate_batch(session, meta, batch)
    session.commit()
    return batch_out(batch)


@router.get("/imports/batches/{batch_id}/rows")
def rows(batch_id: str, status: str | None = None, match: str | None = None, page: int = 1, page_size: int = 100,
         session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    _batch_or_404(session, batch_id)
    q = select(ImportRow).where(ImportRow.batch_id == batch_id)
    if match:
        q = q.where(ImportRow.match_status == match)
    all_rows = session.execute(q.order_by(ImportRow.file_index, ImportRow.row_number)).scalars().all()
    if status == "error":
        all_rows = [r for r in all_rows if r.errors]
    elif status == "warning":
        all_rows = [r for r in all_rows if r.warnings and not r.errors]
    elif status == "ok":
        all_rows = [r for r in all_rows if not r.errors and not r.warnings]
    page_rows = all_rows[(page - 1) * page_size: page * page_size]
    return {"rows": [row_out(session, r) for r in page_rows], "total": len(all_rows)}


@router.get("/imports/batches/{batch_id}/error-file")
def download_error_file(batch_id: str, fmt: str = "csv", session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)):
    name, data = error_file(_batch_or_404(session, batch_id), fmt)
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if name.endswith(".xlsx") else "text/csv"
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/imports/batches/{batch_id}/match")
def match(batch_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
          user: CurrentUser = Depends(require_permission("import"))) -> dict:
    batch = _batch_or_404(session, batch_id)
    if batch.status not in ("validated", "matched", "reviewed"):
        raise HTTPException(409, "Validate the batch first")
    match_batch(session, meta, batch)
    session.commit()
    return batch_out(batch)


@router.put("/imports/batches/{batch_id}/rows/{row_id}")
def put_row(batch_id: str, row_id: str, body: RowBody, session: Session = Depends(get_session),
            user: CurrentUser = Depends(require_permission("import"))) -> dict:
    row = session.get(ImportRow, row_id)
    if row is None or row.batch_id != batch_id:
        raise HTTPException(404, "Row not found")
    try:
        confirm_row(session, row, body.entity_id, body.action, user.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return row_out(session, row)


@router.post("/imports/batches/{batch_id}/review")
def review(batch_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
           user: CurrentUser = Depends(require_permission("import"))) -> dict:
    batch = _batch_or_404(session, batch_id)
    if batch.status not in ("matched", "reviewed"):
        raise HTTPException(409, "Match the rows first")
    review_batch(session, meta, batch)
    session.commit()
    return batch_out(batch)


@router.get("/imports/batches/{batch_id}/conflicts")
def conflicts(batch_id: str, status: str | None = None, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    q = select(ImportConflict).where(ImportConflict.batch_id == batch_id)
    if status:
        q = q.where(ImportConflict.status == status)
    rows_ = session.execute(q.order_by(ImportConflict.entity_id, ImportConflict.attribute_code)).scalars().all()
    ents = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_({c.entity_id for c in rows_}))).scalars()} if rows_ else {}
    return {"rows": [{"id": c.id, "row_id": c.row_id, "entity_id": c.entity_id, "entity_label": ents[c.entity_id].label if c.entity_id in ents else c.entity_id,
                      "attribute_code": c.attribute_code, "channel_code": c.channel_code or None, "current": c.current, "incoming": c.incoming,
                      "policy": c.policy, "status": c.status, "resolved_value": (c.resolved_value or {}).get("value") if c.resolved_value else None}
                     for c in rows_], "total": len(rows_)}


@router.post("/imports/conflicts/decide")
def decide(body: ConflictBody, session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("import"))) -> dict:
    if body.decision not in ("accept", "reject", "edit"):
        raise HTTPException(400, "decision must be accept, reject or edit")
    n = decide_conflicts(session, user, body.conflict_ids, body.decision, body.value)
    session.commit()
    return {"decided": n}


@router.post("/imports/batches/{batch_id}/commit")
def commit(batch_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
           user: CurrentUser = Depends(require_permission("import"))) -> dict:
    batch = _batch_or_404(session, batch_id)
    if batch.status != "reviewed":
        raise HTTPException(409, "Review the batch first")
    run = trigger_job(session, "import_commit", user.email, {"batch_id": batch.id, "user": user.email})
    batch.job_run_id = run.id
    if not os.environ.get("DATABRICKS_JOB_ID_IMPORT_COMMIT"):
        try:
            commit_batch(session, meta, user, batch)
            run.status = "succeeded"
        except Exception as exc:  # noqa: BLE001
            log.exception("commit failed")
            session.rollback()
            batch = _batch_or_404(session, batch_id)
            batch.status, batch.error = "failed", str(exc)[:2000]
    else:
        batch.status = "committing"
    session.commit()
    if batch.status == "committed":
        notify(session, user.email, "import", f"Import {batch.source_code} committed", f"{(batch.report or {}).get('values_approved', 0)} value(s) written", f"/imports/{batch.id}")
        session.commit()
    return batch_out(batch)


@router.post("/imports/batches/{batch_id}/rollback")
def rollback(batch_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
             user: CurrentUser = Depends(require_permission("import"))) -> dict:
    batch = _batch_or_404(session, batch_id)
    try:
        result = rollback_batch(session, meta, user, batch)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return result


@router.get("/imports/batches/{batch_id}/report")
def report(batch_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    b = _batch_or_404(session, batch_id)
    return {"stats": b.stats or {}, "report": b.report or {}, "diff": b.diff or {}}


# ---- keyed worksheets (IMP-12) ------------------------------------------------------------------------------
@router.post("/worksheets")
def create_worksheet(body: WorksheetBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                     user: CurrentUser = Depends(require_permission("export"))) -> dict:
    level = body.selection.get("level", "style_color")
    ents = resolve_entities(session, meta, user, {**body.selection, "level": level})
    if not ents:
        raise HTTPException(400, "The selection has no products at that level")
    ws, data = build_worksheet(session, meta, user, ents, level, body.group_codes, body.include_erp_context, body.selection)
    ws.path = Storage(get_settings().package_volume).write(f"worksheets/{ws.id}/{ws.file_name}", data)
    session.commit()
    return {"id": ws.id, "file_name": ws.file_name, "rows": ws.row_count, "url": f"/api/worksheets/{ws.id}/file"}


@router.get("/worksheets")
def list_worksheets(session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    return [{"id": w.id, "created_by": w.created_by, "created_at": w.created_at.isoformat(), "rows": w.row_count, "group_codes": w.group_codes or [],
             "file_name": w.file_name, "level": w.level, "url": f"/api/worksheets/{w.id}/file"}
            for w in session.execute(select(WorksheetExport).order_by(WorksheetExport.created_at.desc()).limit(100)).scalars()]


@router.get("/worksheets/{ws_id}/file")
def worksheet_file(ws_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)):
    w = session.get(WorksheetExport, ws_id)
    if w is None:
        raise HTTPException(404, "Worksheet not found")
    data = Storage(get_settings().package_volume).read(w.path)
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{w.file_name}"'})
