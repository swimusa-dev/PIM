"""GOV-02 beyond single-attribute restore: restore a whole product to a point in time, list and roll back change
sets as a unit, and keep history hot in Lakebase for a configurable window (the Delta copy keeps everything)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from pim.auth.identity import CurrentUser
from pim.config import get_settings
from pim.models import ChangeSet, ProductEntity, ProductValue, ValueHistory
from pim.models._common import utcnow
from pim.services.metadata import Metadata
from pim.services.values import NA_SENTINEL, WriteOutcome, clear_value, new_change_set, set_value


def values_as_of(session: Session, entity_id: str, at: datetime, inclusive: bool = False) -> dict[tuple[str, str], dict | None]:
    """For every attribute that changed after `at`, the value the product held at `at` (None = no value then).
    The earliest history row after `at` carries that value as its old_value. `inclusive` also undoes changes made
    exactly at `at` (restoring to just before a given history row)."""
    cond = ValueHistory.set_at >= at if inclusive else ValueHistory.set_at > at
    rows = session.execute(select(ValueHistory).where(ValueHistory.entity_id == entity_id, cond)
                           .order_by(ValueHistory.set_at.asc())).scalars().all()
    out: dict[tuple[str, str], dict | None] = {}
    for h in rows:
        key = (h.attribute_code, h.channel_code or "")
        if key not in out:
            out[key] = h.old_value
    return out


def restore_to(session: Session, meta: Metadata, user: CurrentUser, entity: ProductEntity, at: datetime,
               attribute_codes: list[str] | None = None, inclusive: bool = False) -> dict:
    """Restore the product's values to what they were at `at` (or just before the change made at `at` when
    `inclusive`), as one change set (GOV-02 whole-product restore). Needs Approve rights on every touched group;
    attributes without rights are reported, not written."""
    target = values_as_of(session, entity.id, at, inclusive)
    if attribute_codes:
        target = {k: v for k, v in target.items() if k[0] in attribute_codes}
    cs: ChangeSet | None = None
    results: list[dict] = []
    for (code, channel), old in target.items():
        attr = meta.attributes.get(code)
        if attr is None:
            results.append({"attribute_code": code, "outcome": "skipped", "message": "attribute no longer exists"})
            continue
        group = meta.groups.get(attr.group_code)
        if attr.is_erp or (group is not None and group.read_only):
            # P1: the ERP is the system of record; a restore never puts stale ERP values back
            results.append({"attribute_code": code, "outcome": "skipped", "message": "owned by the ERP and read-only in the PIM"})
            continue
        if not user.can_approve_group(attr.group_code):
            results.append({"attribute_code": code, "outcome": "rejected", "message": "Restore requires Approve rights"})
            continue
        if cs is None:
            cs = new_change_set(session, "restore", user.email, f"restore {entity.label} to {at.isoformat()}", source_ref=entity.id)
        if old is None:
            res = clear_value(session, meta, user, entity, attr, channel or None, cs)
        else:
            raw = NA_SENTINEL if old.get("not_applicable") else old.get("value")
            res = set_value(session, meta, user, entity, attr, raw, channel_code=channel or None, source_type="user",
                            source_ref=f"restore_to:{at.isoformat()}", change_set=cs, force=True)
        results.append({"attribute_code": code, "channel_code": channel or None, "outcome": res.outcome, "message": res.message})
    restored = sum(1 for r in results if r["outcome"] in ("approved", "draft"))
    return {"change_set_id": cs.id if cs else None, "restored": restored, "results": results}


def list_change_sets(session: Session, kind: str | None = None, entity_id: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    q = select(ChangeSet)
    if kind:
        q = q.where(ChangeSet.kind == kind)
    if entity_id:
        ids = select(ValueHistory.change_set_id).where(ValueHistory.entity_id == entity_id).distinct()
        q = q.where(ChangeSet.id.in_(ids))
    total = session.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = session.execute(q.order_by(ChangeSet.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    counts = dict(session.execute(select(ValueHistory.change_set_id, func.count()).where(ValueHistory.change_set_id.in_([r.id for r in rows]))
                                  .group_by(ValueHistory.change_set_id)).all()) if rows else {}
    return {"rows": [change_set_out(r, counts.get(r.id, 0)) for r in rows], "total": total}


GENERIC_ROLLBACK_KINDS = ("edit", "restore", "rule", "approval", "ai", "rollback")  # import and bulk roll back from their own pages; ingest never


def change_set_out(cs: ChangeSet, changes: int | None = None) -> dict:
    return {"id": cs.id, "kind": cs.kind, "created_by": cs.created_by, "created_at": cs.created_at.isoformat(), "description": cs.description,
            "source_ref": cs.source_ref, "rolled_back_at": cs.rolled_back_at.isoformat() if cs.rolled_back_at else None, "changes": changes,
            "rollbackable": cs.rolled_back_at is None and cs.kind in GENERIC_ROLLBACK_KINDS}


def prune_history(session: Session, now: datetime | None = None, hot_years: float | None = None) -> int:
    """Delete history rows older than the hot window (PIM_HISTORY_HOT_YEARS, default 2). The caller runs this only
    after the rows have been copied to the Delta history table, so nothing is lost; the current value rows keep
    their own provenance regardless."""
    years = hot_years if hot_years is not None else get_settings().history_hot_years
    if years <= 0:
        return 0
    cutoff = (now or utcnow()) - timedelta(days=365.25 * years)
    res = session.execute(delete(ValueHistory).where(ValueHistory.set_at < cutoff))
    session.flush()
    return int(res.rowcount or 0)


def current_versions(session: Session, entity_id: str) -> int:
    return session.execute(select(func.coalesce(func.max(ProductValue.version), 0)).where(ProductValue.entity_id == entity_id)).scalar_one()


__all__ = ["WriteOutcome", "change_set_out", "current_versions", "list_change_sets", "prune_history", "restore_to", "values_as_of"]
