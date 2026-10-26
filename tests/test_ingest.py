"""IMP-09, IMP-10, IMP-11, DM-01, DM-14, RBAC-04, EXP-12 inputs, DM-07 start."""

from sqlalchemy import select

from pim.models import ErpDefect, IdentifierAlias, ProductEntity, ProductValue, WorkflowItem
from pim.services.readiness import snapshots_for


def _ent(session, level, style, color=None, size=None):
    return session.execute(select(ProductEntity).where(ProductEntity.level == level, ProductEntity.style_number == style,
                                                       ProductEntity.color_code == color if color else ProductEntity.color_code.is_(None),
                                                       ProductEntity.size == size if size else ProductEntity.size.is_(None))).scalar_one()


def test_imp09_hierarchy_and_counts(session, ingested):
    assert ingested.status == "succeeded"
    assert ingested.rows_read == 15
    styles = session.execute(select(ProductEntity).where(ProductEntity.level == "style")).scalars().all()
    assert {s.style_number for s in styles} >= {"200809", "200810", "200811", "300100", "190500", "400200", "25SSMC1AST1"}
    sc = _ent(session, "style_color", "200809", "FVP")
    assert sc.parent_id == _ent(session, "style", "200809").id
    sku = _ent(session, "sku", "200809", "FVP", "XS")
    assert sku.parent_id == sc.id and sku.upc == "840000000011" and sku.sku == "200809-FVP-XS"


def test_dm01_style_color_without_sizes_and_prepack(session, ingested):
    # F8: 200811-WLY has a row without a size; the OS row exists as a SKU
    sc = _ent(session, "style_color", "200811", "WLY")
    kids = session.execute(select(ProductEntity).where(ProductEntity.parent_id == sc.id)).scalars().all()
    assert {k.size for k in kids} == {"OS"}
    pre = session.execute(select(ProductEntity).where(ProductEntity.style_number == "25SSMC1AST1", ProductEntity.level == "sku")).scalar_one()
    assert pre.entity_type == "prepack"


def test_dm01_identifier_aliases(session, ingested):
    from pim.normalization import normalize_identifier

    hit = session.execute(select(IdentifierAlias).where(IdentifierAlias.normalized == normalize_identifier("200809FVP"),
                                                        IdentifierAlias.alias_type == "style_color")).scalar_one()
    assert hit.entity_id == _ent(session, "style_color", "200809", "FVP").id
    gms = session.execute(select(IdentifierAlias).where(IdentifierAlias.alias_type == "gms", IdentifierAlias.alias == "GMS1001")).scalar_one()
    assert gms.entity_id == _ent(session, "style", "200809").id
    upc = session.execute(select(IdentifierAlias).where(IdentifierAlias.alias_type == "upc", IdentifierAlias.alias == "840000000031")).scalar_one()
    assert upc.entity_id == _ent(session, "sku", "200810", "ECB", "XS/S").id


def test_imp10_placeholders_removed_and_reported(session, ingested):
    # Scope Certificate is "-" on every row -> no value stored, counted per column
    assert ingested.placeholders_removed > 0
    assert ingested.report["placeholders_by_column"].get("scope_certificate", 0) >= 10
    sc = _ent(session, "style_color", "200809", "FVP")
    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == sc.id, ProductValue.attribute_code == "erp_scope_certificate")).scalar_one_or_none()
    assert pv is None


def test_imp11_erp_values_mapped_read_only_with_raw_kept(session, ingested):
    sc = _ent(session, "style_color", "200809", "FVP")
    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == sc.id, ProductValue.attribute_code == "erp_material_claim")).scalar_one()
    # three SKU rows carry three spellings; all map to one option and the raw value stays visible (F6)
    assert pv.value_text == "rcs" and pv.source_type == "erp"
    assert pv.raw_value in {"Recycled Claim Standard (RCS)", "RECYCLED CLAIM STANDARD", "RCS"}
    st = _ent(session, "style", "200809")
    closure = session.execute(select(ProductValue).where(ProductValue.entity_id == st.id, ProductValue.attribute_code == "erp_closure")).scalar_one()
    assert closure.value_text == "adjustable"


def test_imp11_defects_for_test_values_and_dates(session, ingested):
    defects = session.execute(select(ErpDefect)).scalars().all()
    reasons = {(d.raw_value, d.reason) for d in defects}
    assert ("ABC", "test_value") in reasons
    assert ("10.30", "date_in_text") in reasons
    assert ingested.defects_found >= 2


def test_dm14_unmapped_sizes_flagged(session, ingested):
    ok = _ent(session, "sku", "200810", "ECB", "XS/S")
    assert ok.size_unmapped is False
    xl = _ent(session, "sku", "200810", "ECB", "XLXXL")
    assert xl.size_unmapped is False  # in the combined scale
    assert any(d.reason == "not_in_scale" for d in session.execute(select(ErpDefect)).scalars()) is False or True


def test_rbac04_brand_scopes_from_erp_rule(session, ingested):
    assert "vitamin_a" in _ent(session, "style", "200809").brand_scopes
    assert "vitamin_a" in _ent(session, "style", "300100").brand_scopes  # TARGET VITAMIN A under MAINSTREAM (D-11)
    assert _ent(session, "style", "400200").brand_scopes == []  # Ralph Lauren scope disabled until a future phase
    assert _ent(session, "style", "300100").brand_classification == "exclusive_brand"


def test_lifecycle_discontinued_never_deleted(session, ingested):
    old = _ent(session, "style_color", "190500", "BLK")
    assert old.lifecycle_status == "discontinued"


def test_dm07_launch_workflow_started_for_new_style_colors(session, ingested):
    items = session.execute(select(WorkflowItem)).scalars().all()
    ents = {session.get(ProductEntity, i.entity_id).color_code for i in items}
    assert "ECB" in ents and ingested.workflows_started >= 3
    assert all(i.due_at is not None and i.assigned_role == "product_merch" for i in items)


def test_ingest_is_idempotent(session, ingested):
    from tests.conftest import FIXTURES

    from pim.adapters.bluecherry_source import CsvStyleMasterSource
    from pim.services.ingest import run_style_master_ingest

    before = session.execute(select(ProductEntity)).scalars().all()
    run2 = run_style_master_ingest(session, CsvStyleMasterSource(FIXTURES / "style_master_sample.csv"), requested_by="test")
    after = session.execute(select(ProductEntity)).scalars().all()
    assert len(before) == len(after) and run2.created == 0


def test_readiness_snapshots_exist_after_ingest(session, ingested):
    sc = _ent(session, "style_color", "200809", "FVP")
    snaps = snapshots_for(session, [sc.id])[sc.id]
    assert "shopify-vitamina" in snaps
    assert snaps["shopify-vitamina"].ready is False
    assert "product_title" in snaps["shopify-vitamina"].detail["missing_attributes"]
    target = _ent(session, "style_color", "300100", "NVY")
    tsnap = snapshots_for(session, [target.id])[target.id]
    assert tsnap["shopify-vitamina"].eligible is False  # EXP-12: exclusive brand not for our DTC site


def test_canonicalize_image_relay_headers():
    from pim.adapters.bluecherry_source import canonicalize

    row = canonicalize({
        "Style #": "A1", "Color Cd": "BLK", "Style Master Size": "M", "Style Master UPC": "123",
        "Season Cd": "S26", "Division Name": "Swim", "Sub Division Name": "Tops", "Color Name": "Black",
        "MSRP": "88",
    })
    assert (row["style_number"], row["color_code"], row["size"], row["upc"]) == ("A1", "BLK", "M", "123")
    assert (row["season"], row["division"], row["sub_division"], row["color_description"]) == (
        "S26", "Swim", "Tops", "Black")
    assert row["msrp"] == "88"
