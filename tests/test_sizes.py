"""DM-14: Style Master sizes against the size scales. Aliases, prepack markers, the plus and bra scales, and the
re-check that clears flags and defects once a scale gains a value."""

from sqlalchemy import select

from pim.models import ErpDefect, OptionList, OptionValue, ProductEntity
from pim.services.ingest import run_style_master_ingest
from pim.services.metadata import invalidate
from pim.services.sizes import reevaluate_sizes

BASE = {"product_type": "TOP", "division": "VITAMIN A", "sub_division": "VA CORE", "brand_name": "VIT A SWIM",
        "brand_classification": "NATIONAL BRAND", "style_description": "TEST TOP", "season": "R27",
        "style_status": "Active", "discontinued": ""}


class NoSource:
    name = "test_sizes"

    def read_changes(self, since=None):
        return iter(())


def _load(session, style, sizes):
    rows = [{**BASE, "style_number": style, "color_code": "BLK", "color_description": "BLK", "size": z,
             "sku": f"{style}-BLK-{z}"} for z in sizes]
    return run_style_master_ingest(session, NoSource(), rows=rows)


def _sku(session, style, size):
    return session.execute(select(ProductEntity).where(ProductEntity.level == "sku", ProductEntity.style_number == style,
                                                       ProductEntity.size == size)).scalar_one()


def _open_size_defects(session, style):
    ids = [e.id for e in session.execute(select(ProductEntity).where(ProductEntity.style_number == style)).scalars()]
    return session.execute(select(ErpDefect).where(ErpDefect.entity_id.in_(ids), ErpDefect.attribute_code == "size",
                                                   ErpDefect.resolved_at.is_(None))).scalars().all()


def test_the_new_scales_and_aliases_match(session):
    sizes = ["16", "18", "26", "18W", "26W", "1X", "6X", "34C", "38DDD", "A", "DD", "LG", "SM", "MD", "NOSIZ", "NS"]
    _load(session, "730001", sizes)
    assert _open_size_defects(session, "730001") == []
    assert not any(_sku(session, "730001", z).size_unmapped for z in sizes)


def test_a_size_in_no_scale_is_still_a_defect(session):
    _load(session, "730002", ["ZZ"])
    assert _sku(session, "730002", "ZZ").size_unmapped
    assert [d.raw_value for d in _open_size_defects(session, "730002")] == ["ZZ"]


def test_pp_is_a_prepack_with_no_size_defect(session):
    _load(session, "730003", ["PP"])
    sku = _sku(session, "730003", "PP")
    assert sku.entity_type == "prepack" and not sku.size_unmapped
    assert _open_size_defects(session, "730003") == []


def test_reevaluate_clears_what_a_new_scale_value_now_matches(session):
    _load(session, "730004", ["ZZ", "YY"])
    assert len(_open_size_defects(session, "730004")) == 2
    scale = session.execute(select(OptionList).where(OptionList.code == "size_numeric")).scalar_one()
    scale.values.append(OptionValue(code="ZZ", label="ZZ", sort_order=900, channel_mappings={}))
    session.flush()
    invalidate()
    result = reevaluate_sizes(session)
    session.expire_all()
    assert result["sizes_now_mapped"] >= 1 and result["size_defects_resolved"] >= 1
    assert not _sku(session, "730004", "ZZ").size_unmapped and _sku(session, "730004", "YY").size_unmapped
    assert [d.raw_value for d in _open_size_defects(session, "730004")] == ["YY"]


def test_reevaluate_marks_existing_pp_skus_as_prepacks(session):
    _load(session, "730005", ["S"])
    sku = _sku(session, "730005", "S")
    sku.size = "PP"
    sku.size_unmapped = True
    session.flush()
    result = reevaluate_sizes(session)
    session.expire_all()
    sku = _sku(session, "730005", "PP")
    assert result["prepacks_marked"] >= 1 and sku.entity_type == "prepack" and not sku.size_unmapped
