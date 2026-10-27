"""A sliced Style Master load commits each slice, retries a dropped connection and resumes after a failure."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from pim.models import IngestRun, ProductEntity
from pim.services.ingest import run_style_master_ingest

BASE = {"product_type": "TOP", "division": "VITAMIN A", "sub_division": "VA CORE", "brand_name": "VIT A SWIM",
        "brand_classification": "NATIONAL BRAND", "style_description": "TEST TOP", "season": "R27"}


def _rows(style):
    return [{**BASE, "style_number": style, "color_code": "BLK", "size": "S", "sku": f"{style}-BLK-S",
             "color_description": "BLK", "style_status": "Active", "discontinued": ""}]


class SlicedSource:
    name = "test_sliced"

    def __init__(self, fail=None):
        self.slices = {0: "710001", 1: "710002", 2: "710003"}
        self.fail = dict(fail or {})  # slice -> exception raised once, when that slice is read
        self.read = []

    def slice_ids(self):
        return list(self.slices)

    def read_slice(self, k, since=None):
        self.read.append(k)
        if k in self.fail:
            raise self.fail.pop(k)
        return iter(_rows(self.slices[k]))

    def read_changes(self, since=None):
        raise AssertionError("a sliced source must be read slice by slice")


def _styles(session):
    return {e.style_number for e in session.execute(select(ProductEntity).where(ProductEntity.level == "style")).scalars()}


def _last_run(session):
    return session.execute(select(IngestRun).order_by(IngestRun.started_at.desc())).scalars().first()


def test_every_slice_commits_and_is_recorded(session):
    src = SlicedSource()
    run = run_style_master_ingest(session, src)
    assert run.status == "succeeded" and src.read == [0, 1, 2]
    assert run.report["slices_total"] == 3 and run.report["completed_slices"] == [0, 1, 2]
    assert _styles(session) == {"710001", "710002", "710003"}


def test_a_failure_keeps_the_committed_slices_and_the_next_run_resumes(session):
    first = SlicedSource(fail={1: RuntimeError("warehouse timeout")})
    with pytest.raises(RuntimeError):
        run_style_master_ingest(session, first)
    failed = _last_run(session)
    assert failed.status == "failed" and "warehouse timeout" in failed.error
    assert failed.report["completed_slices"] == [0]
    assert _styles(session) == {"710001"}  # slice 0 survived, slice 1 and 2 never started

    second = SlicedSource()
    run = run_style_master_ingest(session, second)
    assert second.read == [1, 2]  # slice 0 was not read again
    assert run.status == "succeeded" and run.report["completed_slices"] == [0, 1, 2]
    assert run.report["resumed_from"] == failed.id
    assert _styles(session) == {"710001", "710002", "710003"}


def test_fresh_load_ignores_an_earlier_failure(session):
    with pytest.raises(RuntimeError):
        run_style_master_ingest(session, SlicedSource(fail={1: RuntimeError("boom")}))
    src = SlicedSource()
    run_style_master_ingest(session, src, resume=False)
    assert src.read == [0, 1, 2]


def test_a_dropped_connection_retries_the_slice(session):
    drop = OperationalError("SELECT 1", {}, Exception("SSL error: unexpected eof while reading"))
    src = SlicedSource(fail={1: drop})
    run = run_style_master_ingest(session, src)
    assert run.status == "succeeded" and src.read == [0, 1, 1, 2]
    assert run.rows_read == 3  # the failed attempt is not double counted
    assert _styles(session) == {"710001", "710002", "710003"}


def _row(style, color, size, **extra):
    return {**BASE, "style_number": style, "color_code": color, "size": size, "sku": f"{style}-{color}-{size}",
            "color_description": color, "style_status": "Active", "discontinued": "", **extra}


class NoSource:
    name = "test_rows"

    def read_changes(self, since=None):
        return iter(())


def test_identical_erp_values_are_written_once_per_entity(session, monkeypatch):
    import pim.services.ingest as ingest

    writes = []
    real = ingest.set_value
    monkeypatch.setattr(ingest, "set_value", lambda session, meta, user, ent, attr, *a, **k: (
        writes.append((ent.id, attr.code)), real(session, meta, user, ent, attr, *a, **k))[1])
    rows = [_row("720001", c, z) for c in ("BLK", "RED") for z in ("S", "M", "L")]
    run_style_master_ingest(session, NoSource(), rows=rows)
    assert len(writes) == len(set(writes)) > 0  # 6 rows, but each entity's attribute is written exactly once


def test_a_different_value_on_a_later_row_still_wins_and_a_return_to_an_old_one_too(session):
    from pim.models import ProductValue

    rows = [_row("720002", "BLK", "S", color_description="A"), _row("720002", "BLK", "M", color_description="B"),
            _row("720002", "BLK", "L", color_description="A"), _row("720002", "BLK", "XL", color_description="A")]
    run_style_master_ingest(session, NoSource(), rows=rows)
    sc = session.execute(select(ProductEntity).where(ProductEntity.level == "style_color",
                                                     ProductEntity.style_number == "720002")).scalar_one()
    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == sc.id,
                                                    ProductValue.attribute_code == "erp_color_description")).scalar_one()
    assert pv.value_text == "A"  # A, then B, then back to A (the last value), not stuck on the first or the middle one
