"""Re-check every loaded SKU's size against the current size scales (DM-14).

The ingest flags a size that is in no scale and records an ERP defect for it, but it only ever adds those. When a scale
gains a value (a seed change, applied by the bootstrap job), the SKUs already loaded keep their flag and their open
defect until this runs, so the bootstrap job calls it after the seeds load instead of re-reading the whole Style Master."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from pim.models import ErpDefect, ProductEntity
from pim.models._common import utcnow
from pim.services.metadata import PREPACK_SIZES, load_metadata

CHUNK = 1000


def _chunks(ids: list[str]):
    for i in range(0, len(ids), CHUNK):
        yield ids[i:i + CHUNK]


def reevaluate_sizes(session: Session) -> dict[str, int]:
    """Clear the flag and resolve the defect of every SKU whose size now matches a scale (or is a prepack marker),
    flag the ones that no longer match, and mark prepack-sized SKUs as prepacks. Returns what changed."""
    meta = load_metadata(session, force=True)
    now = utcnow()
    verdict: dict[str, bool] = {}  # size -> matches a scale, one lookup per distinct size

    def matches(size: str) -> bool:
        if size not in verdict:
            verdict[size] = size.strip().upper() in PREPACK_SIZES or meta.size_scale_entry(size) is not None
        return verdict[size]

    open_defects: dict[str, list[str]] = {}
    for entity_id, defect_id in session.execute(select(ErpDefect.entity_id, ErpDefect.id).where(
            ErpDefect.attribute_code == "size", ErpDefect.reason == "not_in_scale", ErpDefect.resolved_at.is_(None))):
        open_defects.setdefault(entity_id, []).append(defect_id)

    clear: list[str] = []
    flag: list[str] = []
    prepack: list[str] = []
    resolve: list[str] = []
    rows: Any = session.execute(select(ProductEntity.id, ProductEntity.size, ProductEntity.size_unmapped,
                                       ProductEntity.entity_type).where(ProductEntity.level == "sku",
                                                                         ProductEntity.size.is_not(None)))
    for entity_id, size, unmapped, entity_type in rows:
        if size.strip().upper() in PREPACK_SIZES and entity_type != "prepack":
            prepack.append(entity_id)
        if matches(size):
            if unmapped:
                clear.append(entity_id)
            resolve.extend(open_defects.get(entity_id, ()))
        elif not unmapped:
            flag.append(entity_id)

    for part in _chunks(clear):
        session.execute(update(ProductEntity).where(ProductEntity.id.in_(part)).values(size_unmapped=False))
    for part in _chunks(flag):
        session.execute(update(ProductEntity).where(ProductEntity.id.in_(part)).values(size_unmapped=True))
    for part in _chunks(prepack):
        session.execute(update(ProductEntity).where(ProductEntity.id.in_(part)).values(entity_type="prepack"))
    for part in _chunks(resolve):
        session.execute(update(ErpDefect).where(ErpDefect.id.in_(part)).values(resolved_at=now))
    return {"sizes_now_mapped": len(clear), "sizes_now_unmapped": len(flag), "prepacks_marked": len(prepack),
            "size_defects_resolved": len(resolve)}
