"""API smoke tests through FastAPI with Databricks identity headers (P7, D7)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pim.main import app
from pim.models import ProductEntity, UserRole

ADMIN = {"X-Forwarded-Email": "admin@swimusa.com", "X-Forwarded-User": "u1"}
VIEWER = {"X-Forwarded-Email": "viewer@swimusa.com", "X-Forwarded-User": "u2"}


@pytest.fixture
def client(session, ingested):
    for email, role in (("admin@swimusa.com", "pim_admin"), ("viewer@swimusa.com", "viewer")):
        if not session.execute(select(UserRole).where(UserRole.email == email, UserRole.role_code == role)).first():
            session.add(UserRole(email=email, role_code=role, brand_scopes=[]))
    session.commit()
    return TestClient(app)


def test_health_and_me(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["erp_last_load_at"] and h["erp_stale"] is False
    me = client.get("/api/me", headers=ADMIN).json()
    assert "pim_admin" in me["roles"] and me["data_rights"]["erp"] == "view" and me["data_rights"]["cost"] == "none"


def test_metadata_endpoints(client):
    attrs = client.get("/api/metadata/attributes?level=style_color", headers=ADMIN).json()
    assert any(a["code"] == "customer_color_name" for a in attrs)
    assert client.get("/api/metadata/groups", headers=ADMIN).status_code == 200
    lists = client.get("/api/metadata/option-lists", headers=ADMIN).json()
    assert any(o["kind"] == "size_scale" for o in lists)
    chans = client.get("/api/metadata/channels", headers=ADMIN).json()
    shop = next(c for c in chans if c["code"] == "shopify-vitamina")
    assert any("product_recommendation" in p for p in shop["protected_fields"])


def test_query_detail_values_and_history(client, session):
    res = client.post("/api/products/query", json={"level": "style_color", "page": 1, "page_size": 10,
                                                   "columns": ["style_number", "attr:customer_color_name", "completeness:shopify-vitamina"],
                                                   "filters": [{"field": "style_number", "op": "eq", "value": "200809"}]}, headers=ADMIN).json()
    assert res["total"] == 2 and "customer_color_name" in res["rows"][0]["values"]
    eid = res["rows"][0]["entity_id"]
    put = client.put(f"/api/products/{eid}/values", json={"values": {"customer_color_name": "Festival Pink", "seo_title": "x" * 80}}, headers=ADMIN).json()
    outcomes = {r["attribute_code"]: r["outcome"] for r in put["results"]}
    assert outcomes == {"customer_color_name": "approved", "seo_title": "rejected"}
    detail = client.get(f"/api/products/{eid}", headers=ADMIN).json()
    assert detail["entity"]["values"]["customer_color_name"]["value"] == "Festival Pink"
    assert detail["groups"] and detail["ancestors"][0]["level"] == "style"
    hist = client.get(f"/api/products/{eid}/history?attribute_code=customer_color_name", headers=ADMIN).json()
    assert hist["total"] == 1
    tree = client.get(f"/api/products/{eid}/tree", headers=ADMIN).json()
    assert tree["root"]["level"] == "style" and tree["nodes"][0]["children"]
    # viewer cannot write (server-side enforcement, P7)
    put2 = client.put(f"/api/products/{eid}/values", json={"values": {"customer_color_name": "Nope"}}, headers=VIEWER).json()
    assert put2["results"][0]["outcome"] == "rejected"
    # unauthenticated in databricks mode would 401; locally the dev fallback applies, so just check headers path works
    assert client.get(f"/api/products/{eid}", headers=VIEWER).status_code == 200


def test_views_dashboard_admin_reports(client):
    v = client.post("/api/views", json={"name": "My colors", "level": "style_color", "shared_with": "everyone",
                                        "definition": {"filters": [{"field": "style_number", "op": "eq", "value": "200809"}], "columns": ["style_number"]}},
                    headers=ADMIN).json()
    assert client.get("/api/views", headers=VIEWER).json()[0]["name"] == "My colors"
    assert client.put(f"/api/views/{v['id']}", json={"is_default": True}, headers=ADMIN).json()["is_default"] is True
    assert client.put(f"/api/views/{v['id']}", json={"name": "Hijack"}, headers=VIEWER).status_code == 403
    q = client.post("/api/products/query", json={"level": "style_color", "view_id": v["id"]}, headers=ADMIN).json()
    assert q["total"] == 2
    d = client.get("/api/dashboard", headers=ADMIN).json()
    assert d["recent_ingest"] and any(r["channel_code"] == "shopify-vitamina" for r in d["readiness_by_channel"])
    defects = client.get("/api/admin/erp-defects", headers=ADMIN).json()
    assert defects["total"] >= 2 and defects["rows"][0]["issue"]
    usage = client.get("/api/admin/attribute-usage", headers=ADMIN).json()
    assert any(u["code"] == "erp_closure" and u["filled"] > 0 for u in usage)
    assert client.get("/api/admin/attribute-usage", headers=VIEWER).status_code == 403
    roles = client.get("/api/admin/user-roles", headers=ADMIN).json()
    assert isinstance(roles, list) and roles[0]["role"]
    assert client.get("/api/admin/telemetry", headers=ADMIN).json()["ai_spend"]["calls"] == 0
    assert client.get("/api/images/queue?kind=candidates", headers=ADMIN).json()["kind"] == "candidates"
    assert client.get("/api/approvals", headers=ADMIN).json()["groups"] == []


def test_reference_entity_impact_then_confirm(client, session):
    created = client.post("/api/reference-entities/fabric", json={"values": {"fabric_name": "EcoRib", "fabric_story": "Ribbed."}}, headers=ADMIN).json()
    assert created["label"] == "EcoRib"
    sc = session.execute(select(ProductEntity).where(ProductEntity.level == "style_color")).scalars().first()
    client.put(f"/api/products/{sc.id}/values", json={"values": {"fabric": created["id"]}}, headers=ADMIN)
    dry = client.put(f"/api/reference-entities/fabric/{created['id']}", json={"values": {"fabric_story": "New story"}}, headers=ADMIN).json()
    assert dry["saved"] is False and dry["impact"]["products"] == 1
    saved = client.put(f"/api/reference-entities/fabric/{created['id']}?confirm=true", json={"values": {"fabric_story": "New story"}}, headers=ADMIN).json()
    assert saved["saved"] is True and saved["values"]["fabric_story"]["value"] == "New story"
    detail = client.get(f"/api/products/{sc.id}", headers=ADMIN).json()
    assert detail["entity"]["values"]["fabric"]["display"] == "EcoRib"


def test_package_via_csv_snapshot(client, session):
    created = client.post("/api/packages", json={"channel_code": "shopify-vitamina", "selection": {"changed_since": "2000-01-01T00:00:00"},
                                                 "snapshot": {"mode": "csv_upload"}}, headers=ADMIN).json()
    assert created["status"] == "pending"
    from tests.conftest import FIXTURES

    with open(FIXTURES / "shopify_products_export.csv", "rb") as fh:
        up = client.post(f"/api/packages/{created['id']}/snapshot-upload", files={"file": ("export.csv", fh, "text/csv")}, headers=ADMIN).json()
    assert up["status"] == "ready" and up["snapshot_at"]
    assert client.get(f"/api/packages/{created['id']}", headers=ADMIN).json()["summary"]["skipped"]
    assert client.post("/api/packages", json={"channel_code": "shopify-vitamina", "selection": {}, "snapshot": {"mode": "csv_upload"}}, headers=VIEWER).status_code == 403
