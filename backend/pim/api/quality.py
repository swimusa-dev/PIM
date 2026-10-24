"""GOV-03 data quality score API: settings, recompute, per-product scores, dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.api.schemas import QualitySettingsBody, RecomputeBody
from pim.models import ProductEntity
from pim.models._common import utcnow
from pim.services import quality

router = APIRouter(prefix="/api", tags=["quality"])


@router.get("/quality/settings")
def get_settings_(session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    out = quality.settings_out(quality.settings_row(session))
    session.commit()
    return out


@router.put("/quality/settings")
def put_settings(body: QualitySettingsBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                 user: CurrentUser = Depends(get_current_user)) -> dict:
    if not user.can("admin_metadata"):
        raise HTTPException(403, "PIM Admin only")
    bad = [c for c in body.enabled_checks if c not in quality.CHECKS]
    if bad:
        raise HTTPException(400, f"Unknown checks: {', '.join(bad)}")
    unknown_groups = [g for g in body.excluded_groups if g not in meta.groups]
    if unknown_groups:
        raise HTTPException(400, f"Unknown groups: {', '.join(unknown_groups)}")
    bands = {**quality.DEFAULTS["grade_bands"], **body.grade_bands}
    if not (100 >= bands["A"] > bands["B"] > bands["C"] > bands["D"] >= 0):
        raise HTTPException(400, "Grade bands must descend from A to D within 0 to 100")
    if any(w < 0 for w in body.weights.values()):
        raise HTTPException(400, "Weights must be zero or positive")
    row = quality.settings_row(session)
    row.excluded_groups, row.enabled_checks, row.weights, row.grade_bands, row.updated_by = body.excluded_groups, body.enabled_checks, body.weights, bands, user.email
    row.updated_at = utcnow()
    session.commit()
    return quality.settings_out(row)


@router.post("/quality/recompute")
def recompute(body: RecomputeBody | None = None, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
              user: CurrentUser = Depends(get_current_user)) -> dict:
    if not user.can("admin_metadata"):
        raise HTTPException(403, "PIM Admin only")
    ids = (body.entity_ids if body else None) or []
    if ids:
        # an explicit recompute is authoritative: it rebuilds the duplicate index instead of carrying the last result
        ents = session.execute(select(ProductEntity).where(ProductEntity.id.in_(ids))).scalars().all()
        n = quality.refresh_quality(session, meta, ents, quality.duplicate_index(session, meta))
        session.commit()
        return {"computed": n}
    from pim.services.jobs import trigger_job

    job = trigger_job(session, "quality", user.email, {"user": user.email})
    if job.databricks_run_id:
        session.commit()
        return {"computed": 0, "status": "started", "job_run_id": job.id}
    n = quality.recompute_all(session, meta)
    job.status, job.finished_at, job.report = "succeeded", utcnow(), {"computed": n}
    session.commit()
    return {"computed": n}


@router.get("/products/{entity_id}/quality")
def product_quality(entity_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                    user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = session.get(ProductEntity, entity_id)
    if ent is None or not user.in_brand_scope(ent.brand_scopes or []):
        raise HTTPException(404, "Product not found")
    target = ent if ent.level == "style_color" else (session.get(ProductEntity, ent.parent_id) if ent.level == "sku" and ent.parent_id else None)
    if target is None:
        kids = session.execute(select(ProductEntity.id).where(ProductEntity.parent_id == ent.id, ProductEntity.level == "style_color")).scalars().all()
        snaps = quality.scores_for(session, list(kids))
        rows = [quality.snapshot_out(s) for per in snaps.values() for s in per.values()]
        return {"scores": rows, "aggregated": True}
    snaps = quality.scores_for(session, [target.id]).get(target.id, {})
    if not snaps:
        quality.refresh_quality(session, meta, [target])
        session.commit()
        snaps = quality.scores_for(session, [target.id]).get(target.id, {})
    return {"scores": [quality.snapshot_out(s) for s in sorted(snaps.values(), key=lambda x: (x.channel_code != "", x.channel_code))], "aggregated": False}


@router.get("/quality/dashboard")
def quality_dashboard(by: str = "family", session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                      user: CurrentUser = Depends(get_current_user)) -> dict:
    if by not in ("family", "season", "channel"):
        raise HTTPException(400, "by must be family, season or channel")
    return {"by": by, "rows": quality.dashboard(session, meta, by)}
