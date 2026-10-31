"""Families (1.3): assigned from the Style Master's Body Type, in priority order, and refreshed without a full load."""

import itertools

import pytest
from sqlalchemy import select

from pim.models import ProductEntity, ReadinessSnapshot
from pim.services.ingest import _family_for, _style_family, refresh_families, run_style_master_ingest

CASES = [
    ("1 PC MISSY", "one_piece"), ("1 PC MISSY SWIMDRESS", "one_piece"), ("1PC CONTEMPORARY", "one_piece"),
    ("DNU - 1 PIECE", "one_piece"), ("SWIM 1 PC", "one_piece"), ("1 PC KIDS W COVER", "one_piece"),
    ("MISSY SEPARATE TOP TANKINI", "swim_top"), ("MISSY SEPARATE TOP BIKINI", "swim_top"), ("BRALETTE", "swim_top"),
    ("MISSY RASHGUARD", "swim_top"), ("SWIM TOP", "swim_top"), ("MISSY SEPARATE TOP SHIRT", "swim_top"),
    ("MISSY SEPARATE BOTTOM", "swim_bottom"), ("BOTTOM", "swim_bottom"), ("HIGH WAIST", "swim_bottom"),
    ("MISSY SEPARATE SKIRTED BOTTOM", "swim_bottom"), ("MENS WATERSHORT", "swim_bottom"),
    ("COVER UP BOTTOM", "cover_up"), ("COVER UP DRESS", "cover_up"), ("DRESS", "cover_up"), ("COVERUP TUNIC", "cover_up"),
    ("SARONG", "cover_up"), ("1 PC SWIMDRESS FULL SCALE", "one_piece"),
    ("2 PC MISSY SET", "swim_set"), ("2 PC KIDS TANKINI SET", "swim_set"), ("3 PC BIKINI SET", "swim_set"),
    ("COVERUP SET", "cover_up"), ("SWEATERS", "apparel"), ("SHORTS", "apparel"), ("DNU - TOP - L/S", "apparel"),
    ("SHAPING PANTIES", "apparel"),
    ("NO DESC", "unassigned"), ("NOT REQUIRED", "unassigned"), ("RANGE", "unassigned"), ("MENS", "unassigned"),
    ("BAG", "unassigned"), ("HATS", "unassigned"), ("CLEANSER", "unassigned"), ("", "unassigned"),
]


@pytest.mark.parametrize("body_type,family", CASES)
def test_body_type_maps_to_family(meta, body_type, family):
    assert _family_for(meta, {"body_type": body_type}) == family


def test_a_source_with_product_type_still_works(meta):
    assert _family_for(meta, {"product_type": "BRALETTE"}) == "swim_top"
    assert _family_for(meta, {"product_type": "ONE PIECE"}) == "one_piece"


BASE = {"division": "VITAMIN A", "sub_division": "VA CORE", "brand_name": "VIT A SWIM", "brand_classification": "NATIONAL BRAND",
        "style_description": "TEST", "season": "R27", "style_status": "Active", "discontinued": ""}


class NoSource:
    name = "test_families"

    def read_changes(self, since=None):
        return iter(())


class RowsSource:
    name = "test_families_rows"

    def __init__(self, rows):
        self.rows = rows
        self.wanted_columns = None

    def read_changes(self, since=None):
        return iter(self.rows)


def _rows(style, body_type=None):
    extra = {"body_type": body_type} if body_type else {}
    return [{**BASE, **extra, "style_number": style, "color_code": "BLK", "color_description": "BLK", "size": z,
             "sku": f"{style}-BLK-{z}"} for z in ("S", "M")]


def _families(session, style):
    return {e.level: e.family_code for e in session.execute(
        select(ProductEntity).where(ProductEntity.style_number == style)).scalars()}


def test_ingest_assigns_the_family_from_body_type(session):
    run_style_master_ingest(session, NoSource(), rows=_rows("750001", "MISSY SEPARATE TOP TANKINI"))
    assert _families(session, "750001") == {"style": "swim_top", "style_color": "swim_top", "sku": "swim_top"}


def test_refresh_updates_loaded_entities_without_an_ingest(session):
    run_style_master_ingest(session, NoSource(), rows=_rows("750002") + _rows("750003") + _rows("750004"))
    assert set(_families(session, "750002").values()) == {"unassigned"}
    source = RowsSource(_rows("750002", "1 PC MISSY") + _rows("750003", "2 PC MISSY SET") + _rows("750004", "NO DESC"))
    result = refresh_families(session, source)
    assert set(_families(session, "750002").values()) == {"one_piece"}
    assert set(_families(session, "750003").values()) == {"swim_set"}
    assert set(_families(session, "750004").values()) == {"unassigned"}
    assert result["styles"] == 3 and result["entities_changed"] == 8  # 4 entities (style, style-color, 2 SKUs) for each of two styles
    assert result["styles_by_family"] == {"one_piece": 1, "swim_set": 1, "unassigned": 1}
    assert source.wanted_columns == {"body_type", "product_type"}


def test_refresh_is_safe_to_repeat(session):
    run_style_master_ingest(session, NoSource(), rows=_rows("750005"))
    source = RowsSource(_rows("750005", "SWIM TOP"))
    assert refresh_families(session, source)["entities_changed"] == 4
    assert refresh_families(session, source)["entities_changed"] == 0


def _computed(session, style):
    ids = [e.id for e in session.execute(select(ProductEntity).where(
        ProductEntity.style_number == style, ProductEntity.level == "style_color")).scalars()]
    return {r.channel_code: r.computed_at for r in session.execute(
        select(ReadinessSnapshot).where(ReadinessSnapshot.entity_id.in_(ids))).scalars()}


def test_refresh_recomputes_readiness_only_for_style_colors_that_move(session):
    run_style_master_ingest(session, NoSource(), rows=_rows("750006") + _rows("750007"))
    before_moved, before_kept = _computed(session, "750006"), _computed(session, "750007")
    assert before_moved and before_kept
    source = RowsSource(_rows("750006", "SWIM TOP") + _rows("750007"))  # 750007 stays unassigned
    result = refresh_families(session, source)
    assert result["snapshots_refreshed"] == 1
    after_moved, after_kept = _computed(session, "750006"), _computed(session, "750007")
    assert all(after_moved[c] > before_moved[c] for c in before_moved)
    assert after_kept == before_kept


def test_all_snapshots_recomputes_even_when_nothing_moves(session):
    run_style_master_ingest(session, NoSource(), rows=_rows("750008"))
    source = RowsSource(_rows("750008"))
    before = _computed(session, "750008")
    assert refresh_families(session, source)["snapshots_refreshed"] == 0
    assert refresh_families(session, source, all_snapshots=True)["snapshots_refreshed"] == 1
    assert all(_computed(session, "750008")[c] > before[c] for c in before)


def test_style_family_is_the_majority_and_ignores_order(meta):
    rows = ["swim_top", "swim_top", "swim_set", "unassigned", None]
    assert {_style_family(meta, list(p)) for p in itertools.permutations(rows)} == {"swim_top"}


def test_a_tie_goes_to_the_family_with_the_lower_rule_priority(meta):
    # swim_set (priority 15) beats swim_top (priority 40) at two rows each, in either order
    assert _style_family(meta, ["swim_top", "swim_top", "swim_set", "swim_set"]) == "swim_set"
    assert _style_family(meta, ["swim_set", "swim_set", "swim_top", "swim_top"]) == "swim_set"


def test_unassigned_only_when_no_row_matched(meta):
    assert _style_family(meta, ["unassigned", "unassigned"]) == "unassigned"
    assert _style_family(meta, ["unassigned", "swim_top"]) == "swim_top"
    assert _style_family(meta, []) == "unassigned"


def _mixed(style, order):
    kinds = {"a": "SWIM TOP", "b": "SWIM TOP", "c": "2 PC MISSY SET"}
    return [{**BASE, "body_type": kinds[k], "style_number": style, "color_code": "BLK", "color_description": "BLK",
             "size": f"S{i}", "sku": f"{style}-BLK-S{i}"} for i, k in enumerate(order)]


def test_ingest_gives_a_mixed_style_the_same_family_in_any_row_order(session):
    for n, order in enumerate(itertools.permutations("abc")):
        style = f"7600{n:02d}"
        run_style_master_ingest(session, NoSource(), rows=_mixed(style, order))
        assert set(_families(session, style).values()) == {"swim_top"}, order


def test_refresh_gives_a_mixed_style_the_same_family_in_any_row_order(session):
    run_style_master_ingest(session, NoSource(), rows=_rows("760100"))
    for order in itertools.permutations("abc"):
        refresh_families(session, RowsSource(_mixed("760100", order)))
        assert set(_families(session, "760100").values()) == {"swim_top"}, order
