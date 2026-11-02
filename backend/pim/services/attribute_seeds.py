"""Fill empty PIM-owned attributes from a warehouse view (seeds/attribute_seeds.yml).

The view is read once for (key, value) pairs; `apply_seed` is pure database work so it is tested without a warehouse.
A value is written only where the entity has none, so a person's edit, an earlier import or an earlier seed always
wins, and running the seed again changes nothing."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.models import ProductEntity, ProductValue
from pim.services.ingest import _normalized_style
from pim.services.metadata import Metadata
from pim.services.readiness import refresh_snapshots
from pim.services.values import new_change_set, set_value


def _q(name: str) -> str:
    return "`" + name.replace("`", "") + "`"


def seed_sql(spec: dict) -> str:
    """Distinct (key, value) pairs; the filter value is quoted as a string literal."""
    where = ""
    flt = spec.get("filter")
    if flt:
        where = f" WHERE {_q(flt['column'])} = '{str(flt['equals']).replace(chr(39), chr(39) * 2)}'"
    return (f"SELECT DISTINCT {_q(spec['key_column'])} AS k, trim(cast({_q(spec['value_column'])} AS string)) AS v "
            f"FROM {spec['table']}{where}")


def read_seed_rows(spec: dict, warehouse_id: str | None = None) -> list[tuple[str, str | None]]:
    from databricks.sdk import WorkspaceClient

    from pim.adapters.bluecherry_source import DeltaStyleMasterSource

    src = DeltaStyleMasterSource(table=spec["table"], warehouse_id=warehouse_id)
    _, rows = src._execute(WorkspaceClient(), seed_sql(spec))
    return [(str(r[0]), r[1]) for r in rows if r[0] is not None]


def apply_seed(session: Session, meta: Metadata, spec: dict, rows: list[tuple[str, str | None]], user_email: str = "seed") -> dict[str, Any]:
    attr = meta.attributes[spec["attribute"]]
    value_map = {str(k).strip().upper(): v for k, v in (spec.get("value_map") or {}).items()}
    level = spec.get("level", attr.level)
    unmapped = object()
    by_key: dict[str, set] = {}
    stats: Counter = Counter()
    for key, raw in rows:
        value = value_map.get(str(raw or "").strip().upper(), unmapped)
        by_key.setdefault(_normalized_style(key), set()).add(value)
    entities = {e.style_number: e for e in session.execute(select(ProductEntity).where(
        ProductEntity.level == level, ProductEntity.style_number.in_(list(by_key)))).scalars()}
    have = {pv.entity_id for pv in session.execute(select(ProductValue).where(
        ProductValue.attribute_code == attr.code, ProductValue.channel_code == "",
        ProductValue.entity_id.in_([e.id for e in entities.values()]))).scalars()}
    cs = new_change_set(session, "import", user_email, f"seed {spec['code']}", source_ref=spec["code"])
    touched: list[ProductEntity] = []
    for key, seen in by_key.items():
        ent = entities.get(key)
        if ent is None:
            stats["not_in_pim"] += 1
            continue
        if unmapped in seen or len(seen) != 1:
            stats["skipped_conflicting_or_unmapped"] += 1
            continue
        if ent.id in have:
            stats["already_has_value"] += 1
            continue
        res = set_value(session, meta, None, ent, attr, next(iter(seen)), source_type="import", source_ref=spec["source_ref"],
                        change_set=cs, force=True, approval_state="approved")
        stats["written" if res.outcome == "approved" else f"not_written_{res.outcome}"] += 1
        if res.outcome == "approved":
            touched.append(ent)
    session.flush()
    refresh_snapshots(session, meta, touched)
    return {"seed": spec["code"], "attribute": attr.code, "keys_in_source": len(by_key), "change_set_id": cs.id, **dict(stats)}
