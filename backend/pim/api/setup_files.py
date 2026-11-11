"""Product Information Setup File export: a new setup file for pasted styles or a saved view, or an uploaded setup
file filled in with PIM values. Both return the workbook directly; a JSON summary rides in X-Setup-File-Summary."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from pim.api.deps import CurrentUser, Metadata, Session, get_meta, get_session
from pim.api.packages import safe_filename
from pim.auth.identity import require_permission
from pim.export.setup_file import (
    XLSX_MEDIA_TYPE,
    SetupFileError,
    SetupFileResult,
    build_setup_workbook,
    fill_setup_workbook,
    parse_style_keys,
    style_colors_for,
)
from pim.services.bulk import resolve_entities

router = APIRouter(prefix="/api/setup-file", tags=["setup-file"])

MAX_UPLOAD_BYTES = 100 * 1024 * 1024


class SetupFileBody(BaseModel):
    styles: list[str] | str | None = Field(default=None, description="Style numbers, optionally with a color code: 6000150, 6000150-MBU")
    entity_ids: list[str] = Field(default_factory=list)
    view_id: str | None = None
    file_name: str | None = None


def _response(result: SetupFileResult, extra: dict | None = None) -> Response:
    summary = {**result.summary, **(extra or {})}
    return Response(content=result.content, media_type=XLSX_MEDIA_TYPE, headers={
        "Content-Disposition": f'attachment; filename="{result.file_name}"',
        "X-Setup-File-Summary": json.dumps(summary, ensure_ascii=True),
        "Access-Control-Expose-Headers": "X-Setup-File-Summary, Content-Disposition",
    })


@router.post("")
def new_setup_file(body: SetupFileBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                   user: CurrentUser = Depends(require_permission("export"))) -> Response:
    missing: list[str] = []
    if body.styles:
        ents, missing = style_colors_for(session, user, parse_style_keys(body.styles))
    elif body.entity_ids or body.view_id:
        sel = {"entity_ids": body.entity_ids} if body.entity_ids else {"view_id": body.view_id}
        ents = resolve_entities(session, meta, user, {**sel, "level": "style_color"})
    else:
        raise HTTPException(400, "Give style numbers, entity ids or a saved view")
    if not ents:
        raise HTTPException(404, "None of those styles are in the PIM (or in your brand scope)")
    ents.sort(key=lambda e: (e.style_number, e.color_code or ""))
    stem = safe_filename(body.file_name, "PIM_Product_Information_Setup_File").removesuffix(".xlsx")
    result = build_setup_workbook(session, meta, user, ents, title=stem)
    return _response(result, {"styles_not_found": missing})


@router.post("/fill")
async def fill_setup_file(file: UploadFile = File(...), keep_file_values: bool = Form(False),
                          session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                          user: CurrentUser = Depends(require_permission("export"))) -> Response:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The file is larger than 100 MB")
    name = safe_filename(file.filename, "setup_file.xlsx")
    if not name.lower().endswith(".xlsx"):
        raise HTTPException(400, "Upload the setup file as .xlsx")
    try:
        result = fill_setup_workbook(session, meta, user, content, name, keep_file_values=keep_file_values)
    except SetupFileError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _response(result)
