"""EXP-13 Shopify update packages (and EXP-05 history)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select

from pim.adapters.base import NotConfigured
from pim.adapters.shopify_admin import ShopifyAdminClient, ShopifySnapshot, parse_product_csv
from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.api.schemas import PackageBody, SandboxRunBody
from pim.config import get_settings
from pim.export.shopify_package import apply_review_workbook, build_package, reconcile
from pim.models import UpdatePackage
from pim.models._common import utcnow
from pim.services.storage import Storage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/packages", tags=["packages"])


def _storage() -> Storage:
    return Storage(get_settings().package_volume)


def _pkg_out(p: UpdatePackage, with_rows: bool = False) -> dict:
    d = {"id": p.id, "channel_code": p.channel_code, "version": p.version, "status": p.status, "created_by": p.created_by,
         "created_at": p.created_at.isoformat(), "snapshot_mode": p.snapshot_mode,
         "snapshot_at": p.snapshot_at.isoformat() if p.snapshot_at else None, "products": p.product_count,
         "changes": p.change_count, "files": [{"name": f["name"], "size": f["size"], "kind": f["kind"]} for f in (p.files or [])],
         "summary": _summary_out(p.summary or {}), "selection": p.selection or {}, "error": p.error,
         "reconciled_at": p.reconciled_at.isoformat() if p.reconciled_at else None, "downloads": p.downloads or [],
         "sandbox_report": (p.summary or {}).get("sandbox_report")}
    if with_rows:
        d["rows"] = [{"id": r.id, "entity_id": r.entity_id, "handle": r.handle, "title": r.title, "scope": r.scope,
                      "variant_key": r.variant_key, "field": r.field, "attribute_code": r.attribute_code,
                      "current_value": r.current_value, "proposed_value": r.proposed_value, "is_clear": r.is_clear,
                      "source_type": r.source_type, "approval_state": r.approval_state, "ai_generated": r.ai_generated,
                      "include": r.include, "note": r.note, "reconcile_status": r.reconcile_status,
                      "reconcile_result": r.reconcile_status,
                      "reconcile_value": r.reconcile_value} for r in p.rows]
    return d


def safe_filename(name: str | None, default: str) -> str:
    """Client-supplied filenames are untrusted: keep the basename and a conservative character set."""
    import re
    from pathlib import PurePosixPath

    base = PurePosixPath(name or "").name.replace("\\", "_")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return cleaned or default


def _summary_out(summary: dict) -> dict:
    out = dict(summary)
    if isinstance(summary.get("by_field"), dict):
        out["by_field"] = [{"field": k, "count": v} for k, v in summary["by_field"].items()]
    if isinstance(summary.get("by_product"), dict):
        out["by_product"] = [{"handle": k, "count": v} for k, v in summary["by_product"].items()]
    out["skipped"] = [{"handle": s.get("label"), **s} for s in summary.get("skipped", [])]
    return out


def _require_run_right(user: CurrentUser, channel_code: str) -> None:
    if not (user.channel_right(channel_code, "run") or user.can("admin_metadata")):
        raise HTTPException(403, "No right to run exports for this channel (RBAC-03)")


def _snapshot_for(pkg: UpdatePackage, storage: Storage) -> ShopifySnapshot:
    if pkg.snapshot_mode == "csv_upload":
        if not pkg.snapshot_path:
            raise HTTPException(409, "Upload the store's Shopify product CSV export first (snapshot-upload)")
        return parse_product_csv(storage.read(pkg.snapshot_path))
    try:
        return ShopifyAdminClient().snapshot_via_bulk()
    except NotConfigured as exc:
        raise HTTPException(409, f"{exc}. Use snapshot mode csv_upload instead.") from exc


@router.get("")
def list_packages(channel: str | None = None, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    q = select(UpdatePackage).order_by(UpdatePackage.created_at.desc()).limit(200)
    if channel:
        q = q.where(UpdatePackage.channel_code == channel)
    return [_pkg_out(p) for p in session.execute(q).scalars()]


@router.post("")
def create_package(body: PackageBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                   user: CurrentUser = Depends(get_current_user)) -> dict:
    if body.channel_code not in meta.channels:
        raise HTTPException(404, "Unknown channel")
    _require_run_right(user, body.channel_code)
    mode = body.snapshot.get("mode", "api")
    pkg = UpdatePackage(channel_code=body.channel_code, created_by=user.email, selection=body.selection, snapshot_mode=mode)
    session.add(pkg)
    session.flush()
    if mode == "api":
        _run_build(session, meta, user, pkg)
    session.commit()
    return _pkg_out(pkg)


def _run_build(session: Session, meta: Metadata, user: CurrentUser, pkg: UpdatePackage) -> None:
    storage = _storage()
    try:
        snap = _snapshot_for(pkg, storage)
        pkg.snapshot_at = utcnow()
        build_package(session, meta, user, pkg, snap, storage)
    except HTTPException:
        pkg.status = "pending"
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("package build failed")
        pkg.status, pkg.error = "failed", str(exc)[:2000]


@router.get("/{package_id}")
def get_package(package_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    pkg = session.get(UpdatePackage, package_id)
    if pkg is None:
        raise HTTPException(404, "Package not found")
    return _pkg_out(pkg, with_rows=True)


@router.get("/{package_id}/files/{name}")
def download_file(package_id: str, name: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)):
    pkg = session.get(UpdatePackage, package_id)
    if pkg is None:
        raise HTTPException(404, "Package not found")
    f = next((x for x in (pkg.files or []) if x["name"] == name), None)
    if f is None:
        raise HTTPException(404, "File not found")
    data = _storage().read(f["path"])
    pkg.downloads = [*(pkg.downloads or []), {"by": user.email, "at": utcnow().isoformat(), "file": name}]
    session.commit()
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if name.endswith(".xlsx") else "text/csv"
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/{package_id}/snapshot-upload")
async def snapshot_upload(package_id: str, file: UploadFile, session: Session = Depends(get_session),
                          meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    pkg = session.get(UpdatePackage, package_id)
    if pkg is None:
        raise HTTPException(404, "Package not found")
    _require_run_right(user, pkg.channel_code)
    content = await file.read()
    storage = _storage()
    pkg.snapshot_path = storage.write(f"{pkg.id}/snapshot/{safe_filename(file.filename, 'products_export.csv')}", content)
    pkg.snapshot_mode = "csv_upload"
    _run_build(session, meta, user, pkg)
    session.commit()
    return _pkg_out(pkg)


@router.post("/{package_id}/review-upload")
async def review_upload(package_id: str, file: UploadFile, session: Session = Depends(get_session),
                        user: CurrentUser = Depends(get_current_user)) -> dict:
    pkg = session.get(UpdatePackage, package_id)
    if pkg is None:
        raise HTTPException(404, "Package not found")
    _require_run_right(user, pkg.channel_code)
    storage = _storage()
    snap = _snapshot_for(pkg, storage) if pkg.snapshot_mode == "csv_upload" else ShopifySnapshot()
    changed = apply_review_workbook(session, pkg, await file.read(), snap, storage)
    session.commit()
    return {"rows_changed": changed, **_pkg_out(pkg)}


@router.post("/{package_id}/reconcile")
async def reconcile_package(package_id: str, file: UploadFile | None = None, session: Session = Depends(get_session),
                            user: CurrentUser = Depends(get_current_user)) -> dict:
    pkg = session.get(UpdatePackage, package_id)
    if pkg is None:
        raise HTTPException(404, "Package not found")
    _require_run_right(user, pkg.channel_code)
    if file is not None:
        fresh = parse_product_csv(await file.read())
    else:
        try:
            fresh = ShopifyAdminClient().snapshot_via_bulk()
        except NotConfigured as exc:
            raise HTTPException(409, f"{exc}. Upload a fresh Shopify product CSV to reconcile.") from exc
    counts = reconcile(pkg, fresh)
    session.commit()
    return {"counts": counts, **_pkg_out(pkg, with_rows=True)}


@router.post("/{package_id}/sandbox-run")
def sandbox_run(package_id: str, body: SandboxRunBody | None = None, session: Session = Depends(get_session),
                meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> dict:
    """D-03: exercise the EXP-07 write path (targeted mutations, protected fields untouched) against the sandbox
    store only. The production flag stays off; `plan_only` never calls Shopify."""
    pkg = session.get(UpdatePackage, package_id)
    if pkg is None:
        raise HTTPException(404, "Package not found")
    _require_run_right(user, pkg.channel_code)
    channel = meta.channels.get(pkg.channel_code)
    protected = list(channel.protected_fields or []) if channel else []
    rows = [{"handle": r.handle, "scope": r.scope, "field": r.field, "proposed_value": r.proposed_value, "is_clear": r.is_clear,
             "variant_key": r.variant_key, "include": r.include} for r in pkg.rows]
    plan = ShopifyAdminClient.plan_mutations(rows, protected)
    plan_only = body.plan_only if body else True
    report = {"store": None, "mode": "plan" if plan_only else "executed", "products": len({m["handle"] for m in plan}), "mutations": plan,
              "protected_check": [], "errors": [], "at": utcnow().isoformat()}
    if plan_only:
        report["store"] = get_settings().shopify_sandbox_domain
        pkg.summary = {**(pkg.summary or {}), "sandbox_report": report}
        session.commit()
        return report
    try:
        client = ShopifyAdminClient.sandbox_client()
    except NotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    report["store"] = client.store
    handles = sorted({m["handle"] for m in plan})
    before = {h: client.read_protected(h, protected) for h in handles}
    try:
        client.execute_plan(plan)
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"{type(exc).__name__}: {str(exc)[:300]}")
    after = {h: client.read_protected(h, protected) for h in handles}
    for h in handles:
        for key in sorted(set(before[h]) | set(after[h])):
            report["protected_check"].append({"handle": h, "field": key, "before": before[h].get(key), "after": after[h].get(key),
                                              "unchanged": before[h].get(key) == after[h].get(key)})
    report["errors"] += [f"{m['handle']}: {m['kind']} {m.get('message')}" for m in plan if m["status"] == "error"]
    pkg.summary = {**(pkg.summary or {}), "sandbox_report": report}
    session.commit()
    return report
