"""Admin reports and operations: IMP-11 ERP defects, GOV-07 attribute usage, RBAC user roles, GOV-04 telemetry, jobs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.api.schemas import UserRoleBody
from pim.auth.identity import require_permission
from pim.models import AppEvent, BrandScope, ErpDefect, JobRun, ProductEntity, ProductValue, Role, UserRole
from pim.services.jobs import trigger_job

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/admin/erp-defects")
def erp_defects(page: int = 1, page_size: int = 100, attribute_code: str | None = None, session: Session = Depends(get_session),
                user: CurrentUser = Depends(get_current_user)) -> dict:
    q = select(ErpDefect).where(ErpDefect.resolved_at.is_(None))
    if attribute_code:
        q = q.where(ErpDefect.attribute_code == attribute_code)
    total = session.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = session.execute(q.order_by(ErpDefect.attribute_code, ErpDefect.raw_value).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    ents = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_({d.entity_id for d in rows}))).scalars()} if rows else {}
    summary = session.execute(select(ErpDefect.attribute_code, ErpDefect.reason, func.count()).where(ErpDefect.resolved_at.is_(None))
                              .group_by(ErpDefect.attribute_code, ErpDefect.reason)).all()
    return {"total": total, "summary": [{"attribute_code": a, "reason": r, "count": n} for a, r, n in summary],
            "rows": [{"id": d.id, "entity_id": d.entity_id, "label": ents[d.entity_id].label if d.entity_id in ents else d.entity_id,
                      "style_number": ents[d.entity_id].style_number if d.entity_id in ents else None,
                      "color_code": ents[d.entity_id].color_code if d.entity_id in ents else None,
                      "attribute_code": d.attribute_code, "erp_column": d.erp_column, "raw_value": d.raw_value, "reason": d.reason,
                      "issue": d.reason, "seen_at": d.last_seen_at.isoformat(),
                      "first_seen_at": d.first_seen_at.isoformat(), "last_seen_at": d.last_seen_at.isoformat()} for d in rows],
            "page": page, "page_size": page_size}


@router.get("/admin/attribute-usage")
def attribute_usage(session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                    user: CurrentUser = Depends(require_permission("admin_metadata"))) -> list[dict]:
    totals = dict(session.execute(select(ProductEntity.level, func.count()).group_by(ProductEntity.level)).all())
    stats = session.execute(select(ProductValue.attribute_code, func.count(), func.count(func.distinct(ProductValue.value_text)),
                                   func.max(ProductValue.set_at)).where(ProductValue.channel_code == "")
                            .group_by(ProductValue.attribute_code)).all()
    by_code = {code: (n, distinct, last) for code, n, distinct, last in stats}
    out = []
    for a in meta.attributes.values():
        n, distinct, last = by_code.get(a.code, (0, 0, None))
        denom = totals.get(a.level, 0) or 0
        mapped = [c for c, ch in meta.channels.items() if a.code in (ch.attribute_mapping or {}) or any(k.startswith(a.code + ".") for k in (ch.attribute_mapping or {}))]
        out.append({"code": a.code, "label": a.label, "level": a.level, "group_code": a.group_code, "status": a.status,
                    "fill_rate": round(100 * n / denom, 1) if denom else 0, "filled": n, "entities": denom, "total": denom,
                    "distinct_values": distinct, "is_constant": n > 1 and distinct <= 1, "mapped_channels": mapped,
                    "used_by_channels": mapped, "last_edit": last.isoformat() if last else None,
                    "last_set_at": last.isoformat() if last else None})
    return sorted(out, key=lambda x: x["fill_rate"])


@router.get("/admin/user-roles")
def list_user_roles(session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("manage_users"))) -> list[dict]:
    rows = session.execute(select(UserRole).order_by(UserRole.email)).scalars().all()
    return [{"id": r.id, "email": r.email, "role": r.role_code, "role_code": r.role_code, "brand_scopes": r.brand_scopes or []} for r in rows]


@router.get("/admin/roles")
def list_roles(session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("manage_users"))) -> dict:
    roles = session.execute(select(Role)).scalars().all()
    scopes = session.execute(select(BrandScope)).scalars().all()
    return {"roles": [{"code": r.code, "label": r.label, "permissions": r.permissions, "data_rights": r.data_rights,
                       "channel_rights": r.channel_rights} for r in roles],
            "brand_scopes": [{"code": s.code, "label": s.label, "enabled": s.enabled, "rules": s.rules} for s in scopes]}


@router.post("/admin/user-roles")
def add_user_role(body: UserRoleBody, session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("manage_users"))) -> dict:
    role_code = body.role_code or body.role
    if not role_code or session.get(Role, role_code) is None:
        raise HTTPException(404, "Unknown role")
    existing = session.execute(select(UserRole).where(UserRole.email == body.email.lower(), UserRole.role_code == role_code)).scalar_one_or_none()
    if existing:
        existing.brand_scopes = body.brand_scopes
        row = existing
    else:
        row = UserRole(email=body.email.lower(), role_code=role_code, brand_scopes=body.brand_scopes)
        session.add(row)
    session.commit()
    return {"id": row.id, "email": row.email, "role": row.role_code, "role_code": row.role_code, "brand_scopes": row.brand_scopes}


@router.delete("/admin/user-roles")
def delete_user_role_body(body: UserRoleBody, session: Session = Depends(get_session),
                          user: CurrentUser = Depends(require_permission("manage_users"))) -> dict:
    r = session.get(UserRole, body.id) if body.id else None
    if r is None:
        role_code = body.role_code or body.role
        r = session.execute(select(UserRole).where(UserRole.email == body.email.lower(), UserRole.role_code == role_code)).scalar_one_or_none()
    if r:
        session.delete(r)
        session.commit()
    return {"deleted": r.id if r else None}


@router.delete("/admin/user-roles/{assignment_id}")
def delete_user_role(assignment_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("manage_users"))) -> dict:
    r = session.get(UserRole, assignment_id)
    if r:
        session.delete(r)
        session.commit()
    return {"deleted": assignment_id}


@router.get("/admin/telemetry")
def telemetry(session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    runs = session.execute(select(JobRun).order_by(JobRun.created_at.desc()).limit(50)).scalars().all()
    events = session.execute(select(AppEvent.kind, AppEvent.source, func.count()).group_by(AppEvent.kind, AppEvent.source)).all()
    ai_events = session.execute(select(AppEvent.payload).where(AppEvent.kind == "ai_call")).scalars().all()
    ai_tokens = sum(int((p or {}).get("prompt_tokens", 0)) + int((p or {}).get("completion_tokens", 0)) for p in ai_events)
    return {"job_runs": [{"id": r.id, "kind": r.kind, "status": r.status, "requested_by": r.requested_by, "created_at": r.created_at.isoformat(),
                          "started_at": (r.started_at or r.created_at).isoformat(), "message": r.error,
                          "finished_at": r.finished_at.isoformat() if r.finished_at else None, "databricks_run_id": r.databricks_run_id,
                          "report": r.report, "error": r.error} for r in runs],
            "events": [{"kind": k, "source": s, "count": n} for k, s, n in events],
            "adapter_errors": [{"adapter": e.source or "", "at": e.at.isoformat(), "message": str((e.payload or {}).get("error", ""))}
                               for e in session.execute(select(AppEvent).where(AppEvent.kind == "adapter_error")
                                                        .order_by(AppEvent.at.desc()).limit(50)).scalars()],
            "ai_spend": {"calls": len(ai_events),
                         "input_tokens": sum(int((p or {}).get("prompt_tokens", 0)) for p in ai_events),
                         "output_tokens": sum(int((p or {}).get("completion_tokens", 0)) for p in ai_events)},
            "ai": {"calls": len(ai_events), "tokens": ai_tokens}}


@router.get("/jobs/runs")
def job_runs(kind: str | None = None, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    q = select(JobRun).order_by(JobRun.created_at.desc()).limit(100)
    if kind:
        q = q.where(JobRun.kind == kind)
    return [{"id": r.id, "kind": r.kind, "status": r.status, "created_at": r.created_at.isoformat(),
             "started_at": (r.started_at or r.created_at).isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None,
             "report": r.report, "error": r.error, "message": r.error} for r in session.execute(q).scalars()]


@router.post("/jobs/ingest/run")
def run_ingest(session: Session = Depends(get_session), user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    run = trigger_job(session, "ingest", user.email, {})
    session.commit()
    return {"id": run.id, "kind": run.kind, "status": run.status, "databricks_run_id": run.databricks_run_id,
            "started_at": (run.started_at or run.created_at).isoformat(), "message": run.error}
