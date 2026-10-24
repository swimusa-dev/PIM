"""DM-10 role dashboard and IMG-05 queues."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.models import (
    Asset,
    AssetLink,
    IngestRun,
    ProductEntity,
    ProductValue,
    ReadinessSnapshot,
    UpdatePackage,
    ValueDraft,
    WorkflowItem,
)
from pim.models._common import utcnow

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
              user: CurrentUser = Depends(get_current_user)) -> dict:
    now = utcnow()
    open_q = select(func.count()).select_from(WorkflowItem).where(WorkflowItem.state == "open")
    if user.roles:
        open_q = open_q.where(WorkflowItem.assigned_role.in_(user.roles))
    open_tasks = session.execute(open_q).scalar_one()
    overdue = session.execute(select(func.count()).select_from(WorkflowItem).where(
        WorkflowItem.state == "open", WorkflowItem.due_at < now)).scalar_one()
    ai_pending = session.execute(select(func.count()).select_from(ValueDraft).where(
        ValueDraft.state.in_(["draft", "proposed"]), ValueDraft.ai_generated.is_(True))).scalar_one()
    drafts_pending = session.execute(select(func.count()).select_from(ValueDraft).where(ValueDraft.state.in_(["draft", "proposed"]))).scalar_one()

    # Launches in the next 30 days (ecomm launch date attribute or ERP delivery date) that are not ready somewhere
    horizon = (now + timedelta(days=30)).date()
    launch_attr = next((a for a in meta.attributes.values() if a.code == "ecomm_launch_date"), None)
    blocking = []
    if launch_attr:
        rows = session.execute(select(ProductValue.entity_id, ProductValue.value_date).where(
            ProductValue.attribute_code == launch_attr.code, ProductValue.value_date.isnot(None),
            ProductValue.value_date <= horizon).order_by(ProductValue.value_date).limit(200)).all()
        ids = [r.entity_id for r in rows]
        snaps = session.execute(select(ReadinessSnapshot).where(ReadinessSnapshot.entity_id.in_(ids), ReadinessSnapshot.ready.is_(False),
                                                                ReadinessSnapshot.eligible.is_(True))).scalars().all() if ids else []
        not_ready: dict[str, list[str]] = {}
        for s in snaps:
            not_ready.setdefault(s.entity_id, []).append(s.channel_code)
        ents = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_(list(not_ready)))).scalars()} if not_ready else {}
        for r in rows:
            if r.entity_id in not_ready and r.entity_id in ents:
                blocking.append({"entity_id": r.entity_id, "label": ents[r.entity_id].label, "launch_date": r.value_date.isoformat(),
                                 "days_left": (r.value_date - now.date()).days, "channels_not_ready": not_ready[r.entity_id]})
    readiness = []
    for ch in meta.channels.values():
        agg = session.execute(select(ReadinessSnapshot.ready, ReadinessSnapshot.eligible, func.count())
                              .where(ReadinessSnapshot.channel_code == ch.code).group_by(ReadinessSnapshot.ready, ReadinessSnapshot.eligible)).all()
        ready = sum(n for r, e, n in agg if r)
        inel = sum(n for r, e, n in agg if not e)
        notready = sum(n for r, e, n in agg if e and not r)
        readiness.append({"channel_code": ch.code, "label": ch.label, "ready": ready, "not_ready": notready, "ineligible": inel})
    ingests = session.execute(select(IngestRun).order_by(IngestRun.started_at.desc()).limit(5)).scalars().all()
    pkgs = session.execute(select(UpdatePackage).order_by(UpdatePackage.created_at.desc()).limit(5)).scalars().all()
    return {
        "open_tasks": open_tasks, "overdue": overdue, "ai_pending": ai_pending, "conflicts_open": drafts_pending,
        "blocking_launches": blocking[:50], "readiness_by_channel": readiness,
        "recent_ingest": [{"id": i.id, "started_at": i.started_at.isoformat(), "finished_at": i.finished_at.isoformat() if i.finished_at else None,
                           "status": i.status, "rows_read": i.rows_read, "created": i.created, "updated": i.updated,
                           "discontinued": i.discontinued, "placeholders_removed": i.placeholders_removed,
                           "defects_found": i.defects_found, "workflows_started": i.workflows_started} for i in ingests],
        "recent_packages": [{"id": p.id, "channel_code": p.channel_code, "created_at": p.created_at.isoformat(), "status": p.status,
                             "products": p.product_count, "changes": p.change_count} for p in pkgs],
    }


@router.get("/images/queue")
def image_queue(kind: str = "candidates", channel: str | None = None, page: int = 1, page_size: int = 50,
                session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                user: CurrentUser = Depends(get_current_user)) -> dict:
    if kind == "candidates":
        q = select(AssetLink).where(AssetLink.status == "proposed").order_by(AssetLink.confidence.desc(), AssetLink.created_at)
        total = session.execute(select(func.count()).select_from(q.subquery())).scalar_one()
        links = session.execute(q.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        ents = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_({lk.entity_id for lk in links}))).scalars()} if links else {}
        return {"kind": kind, "total": total, "rows": [{"id": lk.id, "asset_id": lk.asset_id, "entity_id": lk.entity_id,
                                          "product_label": ents[lk.entity_id].label if lk.entity_id in ents else lk.entity_id,
                                          "proposed_label": ents[lk.entity_id].label if lk.entity_id in ents else lk.entity_id,
                                          "proposed_entity_id": lk.entity_id, "sort_order": lk.sort_order,
                                          "shot_type": lk.shot_type, "tier": lk.tier, "confidence": lk.confidence, "status": lk.status,
                                          "filename": lk.asset.filename if lk.asset else "", "thumbnail_url": lk.asset.thumbnail_url if lk.asset else None,
                                          "evidence": lk.evidence} for lk in links]}
    if kind == "unparsed":
        q = select(Asset).where(Asset.parse_status == "unparsed").order_by(Asset.air_created_at.desc().nullslast())
        total = session.execute(select(func.count()).select_from(q.subquery())).scalar_one()
        assets = session.execute(q.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return {"kind": kind, "total": total, "rows": [{"asset_id": a.id, "filename": a.filename, "board_path": a.board_path,
                                          "thumbnail_url": a.thumbnail_url, "tags": a.tags,
                                          "reason": "No filename pattern or Air field resolved to a style-color"} for a in assets]}
    if kind == "missing":
        chan = channel or next(iter(meta.channels), None)
        q = select(ReadinessSnapshot).where(ReadinessSnapshot.channel_code == chan, ReadinessSnapshot.eligible.is_(True))
        rows = []
        snaps = session.execute(q).scalars().all()
        missing = [s for s in snaps if s.detail.get("missing_shots")]
        total = len(missing)
        page_items = missing[(page - 1) * page_size: page * page_size]
        ents = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_({s.entity_id for s in page_items}))).scalars()} if page_items else {}
        for s in page_items:
            e = ents.get(s.entity_id)
            rows.append({"entity_id": s.entity_id, "label": e.label if e else s.entity_id, "style_number": e.style_number if e else "",
                         "color_code": e.color_code if e else None, "missing_shots": s.detail.get("missing_shots", []), "channel_code": chan})
        return {"kind": kind, "total": total, "rows": rows}
    if kind == "failing_rules":
        from pim.services.images_phase3 import failing_rules_queue  # IMG-05

        return failing_rules_queue(session, meta, channel, page, page_size)
    return {"kind": kind, "total": 0, "rows": []}
