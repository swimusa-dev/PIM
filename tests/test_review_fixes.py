"""Regression tests for the code review findings on PR #1."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pim.adapters.shopify_admin import ShopifySnapshot
from pim.export.shopify_package import find_handle
from pim.main import app, resolve_static
from pim.models import IdentifierAlias, ProductEntity, UserRole, ValueDraft
from pim.services.ingest import run_style_master_ingest
from pim.services.storage import Storage
from pim.services.values import set_value


def test_spa_static_path_never_escapes_static_dir(tmp_path):
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text("<html></html>")
    (tmp_path / "static" / "app.js").write_text("ok")
    (tmp_path / "secret.txt").write_text("secret")
    assert resolve_static("app.js", tmp_path / "static") == (tmp_path / "static" / "app.js").resolve()
    assert resolve_static("../secret.txt", tmp_path / "static") is None
    assert resolve_static("..%2Fsecret.txt", tmp_path / "static") is None
    assert resolve_static("", tmp_path / "static") is None


def test_storage_path_rejects_traversal(tmp_path):
    s = Storage(str(tmp_path))
    assert s.path("pkg", "snapshot/file.csv") == f"{tmp_path}/pkg/snapshot/file.csv"
    with pytest.raises(ValueError):
        s.path("pkg", "../../etc/x")


def test_safe_filename():
    from pim.api.packages import safe_filename

    assert safe_filename("../../etc/cron.d/x", "d.csv") == "x"
    assert safe_filename("Products Export (1).csv", "d.csv") == "Products_Export_1_.csv"
    assert safe_filename(None, "d.csv") == "d.csv"


def test_history_is_scoped_by_data_rights(session, ingested):
    for email, role in (("admin@swimusa.com", "pim_admin"), ("viewer@swimusa.com", "viewer"), ("fin@swimusa.com", "finance")):
        if not session.execute(select(UserRole).where(UserRole.email == email, UserRole.role_code == role)).first():
            session.add(UserRole(email=email, role_code=role, brand_scopes=[]))
    session.commit()
    client = TestClient(app)
    sku = session.execute(select(ProductEntity).where(ProductEntity.sku == "200809-FVP-XS")).scalar_one()
    for email in ("viewer@swimusa.com", "admin@swimusa.com"):
        r = client.get(f"/api/products/{sku.id}/history?attribute_code=erp_standard_cost", headers={"X-Forwarded-Email": email}).json()
        assert r["total"] == 0, email
    r = client.get(f"/api/products/{sku.id}/history?attribute_code=erp_standard_cost", headers={"X-Forwarded-Email": "fin@swimusa.com"}).json()
    assert r["total"] == 1 and r["rows"][0]["new_value"]["value"] == 9.5


def test_one_open_draft_per_value(session, meta, merch, ingested):
    sc = session.execute(select(ProductEntity).where(ProductEntity.level == "style_color", ProductEntity.color_code == "FVP")).scalar_one()
    merch.data_rights["style_details"] = "edit"
    attr = meta.attributes["customer_color_name"]
    for v in ("Festival Pink", "Festival Pnk", "Festival Pink"):
        assert set_value(session, meta, merch, sc, attr, v).outcome == "draft"
    session.flush()
    drafts = session.execute(select(ValueDraft).where(ValueDraft.entity_id == sc.id, ValueDraft.attribute_code == attr.code)).scalars().all()
    assert len(drafts) == 1 and drafts[0].proposed["value"] == "Festival Pink"


def _rows(*specs):
    base = {"product_type": "TOP", "division": "VITAMIN A", "sub_division": "VA CORE", "brand_name": "VIT A SWIM",
            "brand_classification": "NATIONAL BRAND", "style_description": "TEST TOP", "season": "R27"}
    out = []
    for style, color, size, disc in specs:
        out.append({**base, "style_number": style, "color_code": color, "size": size, "sku": f"{style}-{color}-{size}",
                    "color_description": color, "style_status": "Discontinued" if disc else "Active", "discontinued": "Y" if disc else ""})
    return out


def test_style_lifecycle_follows_its_colors(session):
    class Src:
        name = "test"

        def read_changes(self, since=None):
            return iter(())

    run_style_master_ingest(session, Src(), rows=_rows(("900001", "BLK", "S", True), ("900001", "RED", "S", False),
                                                        ("900002", "BLK", "S", True)))
    session.commit()
    live = session.execute(select(ProductEntity).where(ProductEntity.level == "style", ProductEntity.style_number == "900001")).scalar_one()
    dead = session.execute(select(ProductEntity).where(ProductEntity.level == "style", ProductEntity.style_number == "900002")).scalar_one()
    assert live.lifecycle_status == "active" and dead.lifecycle_status == "discontinued"
    # reactivation in the ERP brings the color and the style back
    run_style_master_ingest(session, Src(), rows=_rows(("900002", "BLK", "S", False)))
    session.commit()
    session.refresh(dead)
    sc = session.execute(select(ProductEntity).where(ProductEntity.level == "style_color", ProductEntity.style_number == "900002")).scalar_one()
    assert dead.lifecycle_status == "active" and sc.lifecycle_status == "active"


def test_find_handle_shares_one_shopify_product_between_style_colors(session, ingested):
    snap = ShopifySnapshot()
    snap.add({"handle": "skylar-top", "title": "Skylar Top", "metafields": {}, "variants": [
        {"sku": "200809-FVP-XS", "options": {"Color": "Festival Pink", "Size": "XS"}, "metafields": {}},
        {"sku": "200809-ECB-XS", "options": {"Color": "Eco Black", "Size": "XS"}, "metafields": {}}]})
    assert snap.by_sku("200809-ecb-xs")[1]["sku"] == "200809-ECB-XS"
    for color in ("FVP", "ECB"):
        sc = session.execute(select(ProductEntity).where(ProductEntity.level == "style_color", ProductEntity.style_number == "200809", ProductEntity.color_code == color)).scalar_one()
        skus = session.execute(select(ProductEntity).where(ProductEntity.parent_id == sc.id)).scalars().all()
        assert find_handle(session, snap, sc, skus, None) == "skylar-top"
    session.flush()
    owners = session.execute(select(IdentifierAlias).where(IdentifierAlias.alias_type == "shopify_handle")).scalars().all()
    assert len(owners) == 1
