"""A sliced load is incremental: a style whose source rows are unchanged since the last load is skipped, a changed style
is processed whole, and `full` (or a new logic version) processes everything."""

from sqlalchemy import select

from pim.models import ProductEntity, ProductValue, SourceStyleHash
from pim.services import ingest
from pim.services.ingest import run_style_master_ingest

BASE = {"product_type": "TOP", "division": "VITAMIN A", "sub_division": "VA CORE", "brand_name": "VIT A SWIM",
        "brand_classification": "NATIONAL BRAND", "style_description": "TEST TOP", "season": "R27", "style_status": "Active"}


def _rows(style, colors=("BLK",), sizes=("S", "M"), desc="BLK", disc=None):
    out = []
    for c in colors:
        for z in sizes:
            out.append({**BASE, "style_number": style, "color_code": c, "color_description": desc if c == "BLK" else c,
                        "size": z, "sku": f"{style}-{c}-{z}", "discontinued": "Y" if disc == c else ""})
    return out


class Source:
    """Two slices; `data` maps slice -> rows and can change between runs."""
    name = "test_incremental"

    def __init__(self, data):
        self.data = data

    def slice_ids(self):
        return sorted(self.data)

    def read_slice(self, k, since=None):
        return iter([dict(r) for r in self.data[k]])

    def read_changes(self, since=None):
        raise AssertionError("sliced source")


def _label(session, style):
    return session.execute(select(ProductEntity.label).where(ProductEntity.level == "style_color",
                                                             ProductEntity.style_number == style)).scalar_one()


def test_a_second_identical_load_processes_nothing(session):
    src = Source({0: _rows("760001") + _rows("760002"), 1: _rows("760003")})
    first = run_style_master_ingest(session, src)
    assert first.report["styles_changed"] == 3 and first.report["styles_unchanged"] == 0
    second = run_style_master_ingest(session, src)
    assert second.report["styles_unchanged"] == 3 and second.report["styles_changed"] == 0
    assert second.rows_read == first.rows_read == 6 and second.created == 0 and second.updated == 0
    assert session.execute(select(SourceStyleHash)).scalars().all().__len__() == 3


def test_only_the_changed_style_is_processed(session):
    src = Source({0: _rows("760004") + _rows("760005")})
    run_style_master_ingest(session, src)
    src.data[0] = _rows("760004", desc="NEW NAME") + _rows("760005")
    run = run_style_master_ingest(session, src)
    assert run.report["styles_changed"] == 1 and run.report["styles_unchanged"] == 1
    assert run.updated > 0 and "NEW NAME" in _label(session, "760004")


def test_a_changed_style_is_processed_whole_so_the_rollup_stays_right(session):
    src = Source({0: _rows("760006", colors=("BLK", "RED"))})
    run_style_master_ingest(session, src)
    src.data[0] = _rows("760006", colors=("BLK", "RED"), disc="RED")  # only RED changes; BLK is still live
    run_style_master_ingest(session, src)
    style = session.execute(select(ProductEntity).where(ProductEntity.level == "style",
                                                        ProductEntity.style_number == "760006")).scalar_one()
    red = session.execute(select(ProductEntity).where(ProductEntity.level == "style_color",
                                                      ProductEntity.color_code == "RED",
                                                      ProductEntity.style_number == "760006")).scalar_one()
    assert red.lifecycle_status == "discontinued" and style.lifecycle_status != "discontinued"


def test_a_new_style_is_loaded(session):
    src = Source({0: _rows("760007")})
    run_style_master_ingest(session, src)
    src.data[0] = _rows("760007") + _rows("760008")
    run = run_style_master_ingest(session, src)
    assert run.report["styles_changed"] == 1 and run.report["styles_unchanged"] == 1 and run.created > 0


def test_full_processes_everything_and_records_the_baseline(session):
    src = Source({0: _rows("760009")})
    run_style_master_ingest(session, src, full=True)
    again = run_style_master_ingest(session, src)  # the full run left a baseline, so this one skips
    assert again.report["styles_unchanged"] == 1
    forced = run_style_master_ingest(session, src, full=True)
    assert forced.report["styles_changed"] == 1 and forced.report["styles_unchanged"] == 0


def test_a_new_logic_version_reprocesses_every_style(session, monkeypatch):
    src = Source({0: _rows("760010")})
    run_style_master_ingest(session, src)
    monkeypatch.setattr(ingest, "LOGIC_VERSION", "2")
    run = run_style_master_ingest(session, src)
    assert run.report["styles_changed"] == 1 and run.report["styles_unchanged"] == 0


def test_an_unchanged_load_writes_no_values(session):
    src = Source({0: _rows("760011")})
    run_style_master_ingest(session, src)
    before = session.execute(select(ProductValue.id)).scalars().all()
    run_style_master_ingest(session, src)
    assert session.execute(select(ProductValue.id)).scalars().all() == before
