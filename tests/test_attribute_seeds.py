"""Seeding empty PIM-owned attributes from a warehouse view: fills only empty values, skips disagreement, never overwrites."""

from pathlib import Path

import yaml
from sqlalchemy import select

from pim.models import ProductEntity, ProductValue
from pim.services.attribute_seeds import apply_seed, seed_sql
from pim.services.values import set_value

SPEC = yaml.safe_load((Path(__file__).parent.parent / "seeds" / "attribute_seeds.yml").read_text())["attribute_seeds"][0]


def _style(session, number):
    return session.execute(select(ProductEntity).where(ProductEntity.level == "style", ProductEntity.style_number == number)).scalar_one()


def _pv(session, ent):
    return session.execute(select(ProductValue).where(ProductValue.entity_id == ent.id, ProductValue.attribute_code == "underwire",
                                                      ProductValue.channel_code == "")).scalar_one_or_none()


def test_seed_sql_quotes_and_filters():
    sql = seed_sql(SPEC)
    assert "`Style #`" in sql and "`Underwire? Y/N`" in sql and "WHERE `Division Name` = 'VITAMIN A'" in sql
    assert "''" in seed_sql({**SPEC, "filter": {"column": "Division Name", "equals": "O'Neil"}})


def test_seed_fills_only_empty_and_skips_disagreement(session, meta, admin, ingested):
    style = _style(session, "200809")
    assert _pv(session, style) is None
    rows = [("200809", "YES"), ("200809", "YES"), ("NOSUCH", "NO")]
    out = apply_seed(session, meta, SPEC, rows)
    assert out["written"] == 1 and out["not_in_pim"] == 1
    pv = _pv(session, style)
    assert pv.value_bool is True and pv.source_type == "import" and pv.source_ref == "image_relay_merge"
    # running it again changes nothing
    again = apply_seed(session, meta, SPEC, rows)
    assert again["already_has_value"] == 1 and "written" not in again


def test_seed_never_overwrites_a_person_and_skips_conflicts(session, meta, admin, ingested):
    style = _style(session, "200809")
    set_value(session, meta, admin, style, meta.attributes["underwire"], "false")
    session.flush()
    out = apply_seed(session, meta, SPEC, [("200809", "YES")])
    assert out["already_has_value"] == 1
    assert _pv(session, style).value_bool is False and _pv(session, style).source_type == "user"


def test_seed_skips_styles_whose_colors_disagree_and_unlisted_values(session, meta, ingested):
    out = apply_seed(session, meta, SPEC, [("200809", "YES"), ("200809", "NO")])
    assert out["skipped_conflicting_or_unmapped"] == 1 and _pv(session, _style(session, "200809")) is None
    out = apply_seed(session, meta, SPEC, [("200809", "MAYBE")])
    assert out["skipped_conflicting_or_unmapped"] == 1 and _pv(session, _style(session, "200809")) is None


def test_seed_maps_not_applicable(session, meta, ingested):
    apply_seed(session, meta, SPEC, [("200809", "N/A")])
    pv = _pv(session, _style(session, "200809"))
    assert pv is not None and pv.not_applicable is True
