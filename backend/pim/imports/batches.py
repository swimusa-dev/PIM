"""IMP-01 batch orchestration: upload and stage files, auto-apply mapping templates by structure signature (IMP-02),
recognize keyed worksheets (IMP-12), build rows from a Shopify snapshot (IMP-08), and keep every step short of
commit free of writes to product data."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pim.adapters.shopify_admin import ShopifySnapshot
from pim.auth.identity import CurrentUser
from pim.imports.parsers import ParsedFile, parse_upload
from pim.imports.transforms import map_row
from pim.imports.worksheet import verify_worksheet_rows, worksheet_mapping
from pim.models import ImportBatch, ImportRow, ImportSource, MappingTemplate, WorksheetExport
from pim.services.metadata import Metadata
from pim.services.storage import Storage

SHOPIFY_COLUMNS = ["Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type", "Tags", "SEO Title", "SEO Description",
                   "Variant SKU", "Variant Barcode", "Option1 Value", "Option2 Value"]


def create_batch(session: Session, user: CurrentUser, source_code: str, level: str) -> ImportBatch:
    src = session.get(ImportSource, source_code)
    if src is None:
        raise ValueError("Unknown import source")
    batch = ImportBatch(source_code=source_code, level=level, created_by=user.email, status="uploaded",
                        options={"on_error": (src.default_policy or {}).get("on_error", "skip_value"),
                                 "unmatched_policy": (src.default_policy or {}).get("unmatched", "update_only")},
                        match_keys=["upc", "sku", "style_color", "style", "vendor_style"])
    session.add(batch)
    session.flush()
    return batch


def add_file(session: Session, meta: Metadata, batch: ImportBatch, filename: str, content: bytes, storage: Storage,
             header_row: int | None = None) -> list[dict]:
    """Parse and stage one upload (every sheet becomes a file entry). Rows are stored raw; mapping comes later."""
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in filename)[:120] or "upload"
    path = storage.write(f"{batch.id}/{len(batch.files or [])}_{safe}", content)
    parsed = parse_upload(filename, content, header_row)
    added = []
    for pf in parsed:
        idx = len(batch.files or [])
        entry = _stage_file(session, batch, idx, pf, path, precedence=idx)
        batch.files = [*(batch.files or []), entry]
        added.append(entry)
        if pf.worksheet_meta:
            _apply_worksheet(session, meta, batch, pf)
    session.flush()
    session.refresh(batch)
    if batch.status == "uploaded" and not batch.worksheet_id:
        _auto_apply_template(session, batch)
    batch.storage_path = storage.path(batch.id)
    return added


def _stage_file(session: Session, batch: ImportBatch, idx: int, pf: ParsedFile, path: str, precedence: int) -> dict:
    """Store one parsed sheet as rows of the batch and return its file entry."""
    for i, raw in enumerate(pf.rows, start=pf.data_start_row):
        session.add(ImportRow(batch_id=batch.id, file_index=idx, row_number=i, raw=raw, mapped={}))
    entry = pf.as_dict(idx, precedence)
    entry["path"] = path
    return entry


def reparse_files(session: Session, batch: ImportBatch, edits: list[dict], storage: Storage) -> bool:
    """Re-parse staged files with person-chosen header, group header, and data start rows (the detector is a guess).

    Called from its own endpoint when the person leaves the Upload step, before any mapping exists against the
    new column names. Keyed worksheets have a fixed layout and are refused. Returns True when anything changed."""
    if batch.status not in ("uploaded", "mapped"):
        raise ValueError("Header rows can only change before validation")
    files = list(batch.files or [])
    changed = False
    for e in edits:
        idx = int(e["index"])
        if not (0 <= idx < len(files)):
            raise ValueError(f"No file at index {idx}")
        f = files[idx]
        if f.get("worksheet_meta") or batch.worksheet_id:
            raise ValueError("A keyed worksheet has a fixed layout; its header rows cannot change")
        if not f.get("path"):
            raise ValueError("This file was not uploaded (for example a Shopify pull) and cannot be re-parsed")
        header = int(e.get("header_row") or f["header_row"])
        group = e.get("group_header_row", f.get("group_header_row"))
        group = int(group) if group else None
        data_start = int(e.get("data_start_row") or 0) or None
        if header == f["header_row"] and group == f.get("group_header_row") and (data_start is None or data_start == f.get("data_start_row")):
            continue
        content = storage.read(f["path"])
        try:
            parsed = parse_upload(f["name"], content, header, group, data_start, only_sheet=f.get("sheet"))
        except ValueError as exc:
            raise ValueError(f"{f['name']}: {exc}") from exc
        if not parsed:
            raise ValueError(f"{f['name']}: sheet {f.get('sheet')} not found")
        session.execute(delete(ImportRow).where(ImportRow.batch_id == batch.id, ImportRow.file_index == idx))
        files[idx] = _stage_file(session, batch, idx, parsed[0], f["path"], f.get("precedence", idx))
        changed = True
    if not changed:
        return False
    batch.files = files
    # column names changed: drop mapping entries whose sources no longer exist and re-evaluate the template
    names = {c["name"] for f in files for c in f.get("columns", [])}
    kept = [m for m in (batch.mapping or []) if any(s in names for s in (m.get("sources") or []))]
    if len(kept) != len(batch.mapping or []):
        batch.mapping = kept
    if batch.template_id:
        tpl = session.get(MappingTemplate, batch.template_id)
        if tpl is None or tpl.structure_signature != files[0].get("signature"):
            batch.template_id, batch.mapping = None, []
            batch.status = "uploaded"
            _auto_apply_template(session, batch)
    session.flush()
    session.expire(batch, ["rows"])
    return True


def _apply_worksheet(session: Session, meta: Metadata, batch: ImportBatch, pf: ParsedFile) -> None:
    ws_id = str(pf.worksheet_meta.get("worksheet_id"))
    ws_export = session.get(WorksheetExport, ws_id)
    if ws_export is None:
        batch.error = "This file looks like a PIM worksheet but its id is unknown; it is treated as a plain file"
        return
    batch.worksheet_id = ws_id
    batch.level = ws_export.level
    mapping, keys = worksheet_mapping(meta, pf.worksheet_meta, [c.name for c in pf.columns])
    batch.mapping, batch.match_keys = mapping, keys
    batch.options = {**(batch.options or {}), "unmatched_policy": "update_only", "worksheet": True}
    session.flush()
    rows = session.execute(select(ImportRow).where(ImportRow.batch_id == batch.id)).scalars().all()
    rejected = verify_worksheet_rows(session, rows, ws_export)
    batch.stats = {**(batch.stats or {}), "worksheet_rows_rejected": rejected}
    batch.status = "mapped"


def _auto_apply_template(session: Session, batch: ImportBatch) -> MappingTemplate | None:
    if not batch.files:
        return None
    sig = batch.files[0].get("signature")
    tpl = session.execute(select(MappingTemplate).where(MappingTemplate.structure_signature == sig)
                          .order_by(MappingTemplate.source_code == batch.source_code, MappingTemplate.updated_at.desc())).scalars().first()
    if tpl is None:
        return None
    apply_template(batch, tpl)
    return tpl


def apply_template(batch: ImportBatch, tpl: MappingTemplate) -> None:
    batch.template_id, batch.mapping, batch.match_keys = tpl.id, list(tpl.columns or []), list(tpl.match_keys or [])
    batch.level = tpl.level
    batch.options = {**(batch.options or {}), "unmatched_policy": tpl.unmatched_policy}
    batch.status = "mapped"


def set_mapping(session: Session, meta: Metadata, batch: ImportBatch, mapping: list[dict], match_keys: list[str],
                options: dict, template_id: str | None, precedence: list[int] | None) -> list[str]:
    """Returns the list of required targets still unmapped (blocks progress, IMP-02)."""
    required = [m["target"] for m in mapping if m.get("required") and m.get("target") and not m.get("skip")]
    mapped = {m.get("target") for m in mapping if m.get("target") and not m.get("skip")}
    missing = [r for r in required if r not in mapped]
    batch.mapping, batch.match_keys = mapping, match_keys or batch.match_keys
    batch.options = {**(batch.options or {}), **(options or {})}
    batch.template_id = template_id
    if precedence:
        files = list(batch.files or [])
        for rank, idx in enumerate(precedence):
            if 0 <= idx < len(files):
                files[idx]["precedence"] = rank
        batch.files = files
    for row in batch.rows:
        row.mapped = map_row(row.raw, mapping)
    batch.status = "mapped"
    return missing


def save_template(session: Session, batch: ImportBatch, name: str, user: CurrentUser) -> MappingTemplate:
    sig = (batch.files[0].get("signature") if batch.files else "") or ""
    f = batch.files[0] if batch.files else {}
    tpl = MappingTemplate(source_code=batch.source_code, name=name, structure_signature=sig, header_row=f.get("header_row", 1),
                          group_header_row=f.get("group_header_row"), data_start_row=f.get("data_start_row", 2), level=batch.level,
                          columns=batch.mapping or [], match_keys=batch.match_keys or [],
                          unmatched_policy=(batch.options or {}).get("unmatched_policy", "update_only"), created_by=user.email)
    session.add(tpl)
    session.flush()
    batch.template_id = tpl.id
    return tpl


def rows_from_shopify(session: Session, batch: ImportBatch, snap: ShopifySnapshot) -> int:
    """IMP-08 Shopify backfill: one staged row per variant with product columns and metafields flattened."""
    for r in list(batch.rows):
        session.delete(r)
    n = 0
    columns = set(SHOPIFY_COLUMNS)
    for p in snap.products.values():
        base = {"Handle": p.get("handle"), "Title": p.get("title"), "Body (HTML)": p.get("body_html"), "Vendor": p.get("vendor"),
                "Product Category": p.get("category"), "Type": p.get("product_type"), "Tags": ", ".join(p.get("tags") or []),
                "SEO Title": p.get("seo_title"), "SEO Description": p.get("seo_description")}
        for k, v in (p.get("metafields") or {}).items():
            base[f"metafield:{k}"] = v
            columns.add(f"metafield:{k}")
        variants = p.get("variants") or [{}]
        for v in variants:
            opts = list((v.get("options") or {}).values())
            raw = {**base, "Variant SKU": v.get("sku"), "Variant Barcode": v.get("barcode"),
                   "Option1 Value": opts[0] if opts else None, "Option2 Value": opts[1] if len(opts) > 1 else None}
            n += 1
            session.add(ImportRow(batch_id=batch.id, file_index=0, row_number=n, raw={k: ("" if val is None else str(val)) for k, val in raw.items()}, mapped={}))
    batch.files = [{"index": 0, "name": "shopify snapshot", "sheet": None, "header_row": 1, "group_header_row": None, "data_start_row": 2,
                    "rows": n, "columns": [{"name": c, "group": None, "samples": []} for c in sorted(columns)], "precedence": 0}]
    if not batch.mapping:
        batch.mapping = [{"target": "sku", "sources": ["Variant SKU"], "transforms": []},
                         {"target": "upc", "sources": ["Variant Barcode"], "transforms": []}]
        batch.match_keys = ["sku", "upc"]
    batch.options = {**(batch.options or {}), "unmatched_policy": "update_only"}
    batch.status = "uploaded"
    session.flush()
    session.expire(batch, ["rows"])
    return n


def batch_out(batch: ImportBatch) -> dict[str, Any]:
    return {"id": batch.id, "status": batch.status, "source_code": batch.source_code, "template_id": batch.template_id, "level": batch.level,
            "created_by": batch.created_by, "created_at": batch.created_at.isoformat(), "files": batch.files or [], "mapping": batch.mapping or [],
            "match_keys": batch.match_keys or [], "options": batch.options or {}, "stats": batch.stats or {}, "diff": batch.diff or {},
            "worksheet_id": batch.worksheet_id, "change_set_id": batch.change_set_id, "error": batch.error, "report": batch.report or {},
            "committed_at": batch.committed_at.isoformat() if batch.committed_at else None}


def row_out(session: Session, row: ImportRow) -> dict[str, Any]:
    from pim.models import ProductEntity

    label = None
    if row.entity_id:
        ent = session.get(ProductEntity, row.entity_id)
        label = ent.label if ent else None
    return {"id": row.id, "file_index": row.file_index, "row_number": row.row_number, "raw": row.raw, "mapped": row.mapped,
            "match_status": row.match_status, "match_key_used": row.match_key_used, "entity_id": row.entity_id, "entity_label": label,
            "candidates": row.candidates or [], "errors": row.errors or [], "warnings": row.warnings or [], "action": row.action}
