"""IMG-01 snapshot, IMG-03 tiers 1 and 2, IMG-05 queue inputs."""

from sqlalchemy import select
from tests.conftest import FIXTURES

from pim.models import Asset, AssetLink, FilenamePattern, ProductEntity
from pim.services.images import parse_filename, run_matching, upsert_assets


def _load_assets():
    items = []
    for i, line in enumerate((FIXTURES / "air_filenames.txt").read_text().splitlines()):
        if not line or line.startswith("#"):
            continue
        name, tags, fields = line.split("|")
        cf = dict(p.split("=", 1) for p in fields.split(";") if "=" in p)
        items.append({"id": f"asset-{i}", "version_id": "v1", "filename": name, "board_path": "Vitamin A / Resort 27",
                      "tags": [t for t in tags.split(",") if t], "custom_fields": cf, "smart_tags": [], "width": 3000, "height": 3750,
                      "thumbnail_url": None, "air_created_at": None})
    return items


def test_tier1_filename_parsing(session, meta):
    patterns = session.execute(select(FilenamePattern)).scalars().all()
    p = parse_filename("200809-FVP_front_01.jpg", patterns)
    assert p and p.style == "200809" and p.color == "FVP" and p.shot == "front" and p.seq == 1
    p2 = parse_filename("200809FVP_3.jpg", patterns)
    assert p2 and p2.shot == "side"
    assert parse_filename("DSC_0001.jpg", patterns) is None


def test_img01_snapshot_detects_changes(session):
    items = _load_assets()
    s1 = upsert_assets(session, items)
    assert s1["new"] == len(items)
    items[0]["version_id"] = "v2"
    s2 = upsert_assets(session, items)
    assert s2["changed"] == 1 and s2["unchanged"] == len(items) - 1


def test_img03_matching_tiers_and_unparsed_queue(session, meta, ingested):
    upsert_assets(session, _load_assets())
    stats = run_matching(session, meta)
    assert stats["tier1"] == 4 and stats["tier2"] == 2 and stats["unparsed"] == 2
    links = session.execute(select(AssetLink)).scalars().all()
    fvp = session.execute(select(ProductEntity).where(ProductEntity.level == "style_color", ProductEntity.style_number == "200809",
                                                      ProductEntity.color_code == "FVP")).scalar_one()
    fvp_links = [lk for lk in links if lk.entity_id == fvp.id]
    assert {lk.shot_type for lk in fvp_links} == {"front", "back", "side"}
    assert all(lk.status == "confirmed" and lk.tier == 1 for lk in fvp_links)
    tier2 = [lk for lk in links if lk.tier == 2]
    assert all(lk.status == "confirmed" for lk in tier2)  # shot type came from Air fields
    unparsed = session.execute(select(Asset).where(Asset.parse_status == "unparsed")).scalars().all()
    assert {a.filename for a in unparsed} == {"DSC_0001.jpg", "waterlily_campaign_01.jpg"}
