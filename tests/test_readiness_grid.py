"""DM-02 server-side grid, DM-05 completeness, EXP-03 readiness, EXP-12 eligibility, DM-14 size sort."""

from sqlalchemy import select

from pim.models import ProductEntity
from pim.services.grid import GridQuery, run_grid_query
from pim.services.readiness import compute_readiness, refresh_snapshots
from pim.services.values import set_value


def _sc(session, style, color):
    return session.execute(select(ProductEntity).where(ProductEntity.level == "style_color", ProductEntity.style_number == style,
                                                       ProductEntity.color_code == color)).scalar_one()


def test_exp03_readiness_reasons_and_completeness_progression(session, meta, admin, ingested):
    sc = _sc(session, "200809", "FVP")
    ch = meta.channels["shopify-vitamina"]
    r0 = compute_readiness(session, meta, sc, ch)
    assert not r0.ready and r0.required_total == 9 and r0.completeness_pct < 50
    st = session.get(ProductEntity, sc.parent_id)
    set_value(session, meta, admin, st, meta.attributes["product_description"], "Meet the Skylar Top in EcoRib.")
    for code, val in {"product_title": "Skylar Top", "customer_color_name": "Festival Pink", "seo_title": "Skylar Top",
                      "seo_description": "A longline bralette."}.items():
        assert set_value(session, meta, admin, sc, meta.attributes[code], val).outcome == "approved"
    session.flush()
    r1 = compute_readiness(session, meta, sc, ch)
    assert r1.completeness_pct > r0.completeness_pct
    assert "fabric" in r1.missing_attributes and set(r1.missing_shots) == {"front", "back", "on_model_front"}
    assert any("mapping" in x for x in r1.reasons) is False  # all required attrs are mapped for Shopify


def test_exp12_eligibility_before_readiness(session, meta, ingested):
    target = _sc(session, "300100", "NVY")
    r = compute_readiness(session, meta, target, meta.channels["shopify-vitamina"])
    assert r.eligible is False and "retailer" in " ".join(r.reasons).lower()
    r_t = compute_readiness(session, meta, target, meta.channels["targetplus"])
    assert r_t.eligible is True
    disc = _sc(session, "190500", "BLK")
    assert compute_readiness(session, meta, disc, meta.channels["shopify-vitamina"]).eligible is False


def test_dm02_grid_paging_filters_and_inherited_attribute_filter(session, meta, admin, ingested):
    res = run_grid_query(session, meta, admin, GridQuery(level="sku", page=1, page_size=5, sort=[{"field": "sku", "dir": "asc"}]))
    assert res["total"] >= 14 and len(res["rows"]) == 5
    res2 = run_grid_query(session, meta, admin, GridQuery(level="sku", page=2, page_size=5, sort=[{"field": "sku", "dir": "asc"}]))
    assert res2["rows"][0]["entity_id"] != res["rows"][0]["entity_id"]
    # filter SKUs by a style-level ERP attribute (inherited two levels up)
    res3 = run_grid_query(session, meta, admin, GridQuery(level="sku", filters=[{"field": "attr:erp_closure", "op": "eq", "value": "adjustable"}],
                                                          columns=["erp_closure", "erp_style_content"]))
    assert res3["total"] == 5 and all(r["values"]["erp_closure"]["value"] == "adjustable" for r in res3["rows"])
    assert all(r["values"]["erp_closure"]["inherited_from"]["level"] == "style" for r in res3["rows"])
    # search by identifier without separators
    res4 = run_grid_query(session, meta, admin, GridQuery(level="style_color", search="200809FVP"))
    assert res4["total"] == 1


def test_dm02_readiness_and_completeness_filters(session, meta, admin, ingested):
    res = run_grid_query(session, meta, admin, GridQuery(level="style_color", filters=[{"field": "readiness:shopify-vitamina", "op": "eq", "value": "false"}]))
    assert res["total"] >= 1 and all(r["readiness"]["shopify-vitamina"]["ready"] is False for r in res["rows"])
    res2 = run_grid_query(session, meta, admin, GridQuery(level="style_color", filters=[{"field": "completeness:shopify-vitamina", "op": "lt", "value": 100}]))
    assert res2["total"] == res["total"] or res2["total"] >= 1
    styles = run_grid_query(session, meta, admin, GridQuery(level="style", filters=[{"field": "readiness:shopify-vitamina", "op": "eq", "value": "false"}]))
    assert styles["total"] >= 1 and "shopify-vitamina" in styles["rows"][0]["completeness"]


def test_dm14_sizes_sort_by_scale_order(session, meta, admin, ingested):
    res = run_grid_query(session, meta, admin, GridQuery(level="sku", filters=[{"field": "style_number", "op": "eq", "value": "200810"}],
                                                         sort=[{"field": "size", "dir": "asc"}]))
    assert [r["size"] for r in res["rows"]] == ["XS/S", "M/L", "XLXXL"]


def test_rbac04_brand_scope_restricts_grid(session, meta, ingested):
    from tests.conftest import make_user

    scoped = make_user(session, "scoped@swimusa.com", ["viewer"], ["vitamin_a"])
    res = run_grid_query(session, meta, scoped, GridQuery(level="style"))
    assert all("vitamin_a" in r["brand_scopes"] for r in res["rows"]) and res["total"] >= 5
    assert not any(r["style_number"] == "400200" for r in res["rows"])


def test_refresh_snapshots_after_style_edit_updates_children(session, meta, admin, ingested):
    st = session.execute(select(ProductEntity).where(ProductEntity.level == "style", ProductEntity.style_number == "200809")).scalar_one()
    before = run_grid_query(session, meta, admin, GridQuery(level="style_color", filters=[{"field": "style_number", "op": "eq", "value": "200809"}]))
    set_value(session, meta, admin, st, meta.attributes["product_description"], "Copy")
    refresh_snapshots(session, meta, [st])
    after = run_grid_query(session, meta, admin, GridQuery(level="style_color", filters=[{"field": "style_number", "op": "eq", "value": "200809"}]))
    assert after["rows"][0]["completeness"]["shopify-vitamina"] > before["rows"][0]["completeness"]["shopify-vitamina"]
