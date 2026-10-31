"""D-15: channel eligibility and brand scopes edited in the app: validation, impact preview, permissions, and applying a
change to products already loaded."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pim.main import app
from pim.models import BrandScope, Channel, ProductEntity, ReadinessSnapshot, UserRole
from pim.services import eligibility as svc

ADMIN = {"X-Forwarded-Email": "admin@swimusa.com", "X-Forwarded-User": "u1"}
VIEWER = {"X-Forwarded-Email": "viewer@swimusa.com", "X-Forwarded-User": "u2"}


@pytest.fixture(autouse=True)
def restore_seeded_rules(engine):
    """Channels and brand scopes are seed data, which the per-test cleanup does not reset: put them back after each test."""
    from sqlalchemy.orm import sessionmaker

    from pim.services.metadata import invalidate

    factory = sessionmaker(bind=engine)
    with factory() as s:
        channels = {c.code: (c.eligibility, c.version) for c in s.execute(select(Channel)).scalars()}
        scopes = {b.code: (b.label, b.rules, b.enabled) for b in s.execute(select(BrandScope)).scalars()}
    yield
    with factory() as s:
        for c in s.execute(select(Channel)).scalars():
            if c.code in channels:
                c.eligibility, c.version = channels[c.code]
        for b in s.execute(select(BrandScope)).scalars():
            if b.code in scopes:
                b.label, b.rules, b.enabled = scopes[b.code]
            else:
                s.delete(b)
        s.commit()
    invalidate()


@pytest.fixture
def client(session, ingested):
    for email, role in (("admin@swimusa.com", "pim_admin"), ("viewer@swimusa.com", "viewer")):
        if not session.execute(select(UserRole).where(UserRole.email == email, UserRole.role_code == role)).first():
            session.add(UserRole(email=email, role_code=role, brand_scopes=[]))
    session.commit()
    return TestClient(app)


def _eligible(session, channel_code):
    return {r.entity_id for r in session.execute(select(ReadinessSnapshot).where(
        ReadinessSnapshot.channel_code == channel_code, ReadinessSnapshot.eligible.is_(True))).scalars()}


# ---- validation -----------------------------------------------------------------------------------------------------

def test_scope_rules_are_validated_and_normalized():
    rules = svc.validate_scope_rules([[{"field": "division", "op": "in", "value": "MIRACLESUIT, MAGICSUIT"}],
                                      [{"field": "brand_name", "value": " X "}]])
    assert rules == [[{"field": "division", "op": "in", "value": ["MIRACLESUIT", "MAGICSUIT"]}],
                     [{"field": "brand_name", "op": "eq", "value": "X"}]]
    for bad in ([], [[]], [[{"field": "colour", "op": "eq", "value": "x"}]], [[{"field": "division", "op": "like", "value": "x"}]],
                [[{"field": "division", "op": "eq", "value": ""}]], "division"):
        with pytest.raises(svc.EligibilityError):
            svc.validate_scope_rules(bad)


def test_eligibility_is_validated_and_empty_values_are_dropped():
    out = svc.validate_eligibility({"brand_scopes": [], "exclude_classifications": ["Private_Label"], "exclude_lifecycle": ["discontinued"],
                                    "exclude_entity_types": []}, {"vitamin_a"}, {"private_label", "exclusive_brand"})
    assert out == {"exclude_classifications": ["private_label"], "exclude_lifecycle": ["discontinued"]}
    for bad in ({"brand_scopes": ["nope"]}, {"exclude_classifications": ["nope"]}, {"exclude_lifecycle": ["gone"]},
                {"surprise": []}, {"allow_classifications_for_subdivision": {"x": "TARGET"}}, "text"):
        with pytest.raises(svc.EligibilityError):
            svc.validate_eligibility(bad, {"vitamin_a"}, {"private_label"})


# ---- API ------------------------------------------------------------------------------------------------------------

def test_options_list_the_scopes_classifications_and_fields(client):
    o = client.get("/api/metadata/eligibility-options", headers=ADMIN).json()
    assert {"vitamin_a", "ralph_lauren_swim"} <= {s["code"] for s in o["brand_scopes"]}
    assert {c["code"] for c in o["classifications"]} >= {"national_brand", "private_label"}
    assert "division" in o["fields"] and "in" in o["ops"] and "prepack" in o["entity_types"]


def test_saving_a_channel_eligibility_updates_it_and_asks_for_a_recompute(client, session):
    r = client.put("/api/metadata/channels/shopify-vitamina/eligibility", headers=ADMIN,
                   json={"eligibility": {"exclude_lifecycle": ["discontinued"]}})
    assert r.status_code == 200 and r.json()["recompute_needed"] is True
    session.expire_all()
    ch = session.get(Channel, "shopify-vitamina")
    assert ch.eligibility == {"exclude_lifecycle": ["discontinued"]}  # brand scope removed: open to every brand
    assert r.json()["channel"]["version"] == ch.version


def test_a_bad_eligibility_is_refused_and_nothing_changes(client, session):
    before = session.get(Channel, "walmart-mp").eligibility
    r = client.put("/api/metadata/channels/walmart-mp/eligibility", headers=ADMIN, json={"eligibility": {"brand_scopes": ["nope"]}})
    assert r.status_code == 422 and "Unknown brand scope" in r.json()["detail"]
    session.expire_all()
    assert session.get(Channel, "walmart-mp").eligibility == before


def test_only_an_admin_can_edit_eligibility_or_scopes(client):
    body = {"eligibility": {}}
    assert client.put("/api/metadata/channels/walmart-mp/eligibility", headers=VIEWER, json=body).status_code == 403
    assert client.post("/api/metadata/channels/walmart-mp/eligibility/preview", headers=VIEWER, json=body).status_code == 403
    rules = [[{"field": "division", "op": "eq", "value": "X"}]]
    assert client.put("/api/metadata/brand-scopes/x_scope", headers=VIEWER, json={"label": "X", "rules": rules}).status_code == 403
    assert client.delete("/api/metadata/brand-scopes/vitamin_a", headers=VIEWER).status_code == 403
    assert client.post("/api/metadata/eligibility/recompute", headers=VIEWER).status_code == 403


def test_preview_shows_what_a_change_would_do_without_saving_it(client, session):
    before = session.get(Channel, "shopify-vitamina").eligibility
    r = client.post("/api/metadata/channels/shopify-vitamina/eligibility/preview", headers=ADMIN,
                    json={"eligibility": {"exclude_lifecycle": ["discontinued"]}}).json()
    assert r["total"] > 0 and r["eligible_after"] >= r["eligible_now"] and r["newly_ineligible"] == 0
    assert r["newly_eligible"] == r["eligible_after"] - r["eligible_now"]
    session.expire_all()
    assert session.get(Channel, "shopify-vitamina").eligibility == before


def test_scope_crud_with_preview_and_in_use_protection(client, session):
    rules = [[{"field": "division", "op": "eq", "value": "VITAMIN A"}]]
    preview = client.post("/api/metadata/brand-scopes/preview", headers=ADMIN, json={"rules": rules}).json()
    assert preview["style_colors"] > 0 and preview["divisions"][0]["division"] == "VITAMIN A"
    saved = client.put("/api/metadata/brand-scopes/test_scope", headers=ADMIN, json={"label": "Test scope", "rules": rules})
    assert saved.status_code == 200 and saved.json()["scope"]["used_by"] == []
    assert any(s["code"] == "test_scope" for s in client.get("/api/metadata/brand-scopes", headers=ADMIN).json())
    assert client.put("/api/metadata/brand-scopes/Bad Code", headers=ADMIN, json={"label": "x", "rules": rules}).status_code in (404, 422)
    assert client.put("/api/metadata/brand-scopes/ok_code", headers=ADMIN, json={"label": "x", "rules": []}).status_code == 422
    # a scope a channel uses cannot be deleted; an unused one can
    assert client.delete("/api/metadata/brand-scopes/vitamin_a", headers=ADMIN).status_code == 409
    assert client.delete("/api/metadata/brand-scopes/test_scope", headers=ADMIN).status_code == 200
    session.expire_all()
    assert session.get(BrandScope, "test_scope") is None


# ---- applying a change to products already loaded -------------------------------------------------------------------

def test_recompute_applies_a_new_scope_and_open_channel_to_loaded_products(client, session):
    shopify = "shopify-vitamina"
    before = _eligible(session, shopify)
    assert before  # the fixture has Vitamin A style-colors
    total = len(session.execute(select(ProductEntity.id).where(ProductEntity.level == "style_color")).scalars().all())
    assert len(before) < total  # and other brands, which are outside the channel's scope

    # open the channel to every brand, then apply
    assert client.put(f"/api/metadata/channels/{shopify}/eligibility", headers=ADMIN, json={"eligibility": {}}).status_code == 200
    r = client.post("/api/metadata/eligibility/recompute", headers=ADMIN).json()
    assert r["style_colors_recomputed"] == total
    session.expire_all()
    assert len(_eligible(session, shopify)) >= len(before) and before <= _eligible(session, shopify)


def test_recompute_rederives_brand_scopes_from_the_stored_erp_fields(client, session):
    style_colors = session.execute(select(ProductEntity).where(ProductEntity.level == "style_color")).scalars().all()
    other = next(e for e in style_colors if "vitamin_a" not in (e.brand_scopes or []))
    division = other.erp_fields["division"]
    sku = session.execute(select(ProductEntity).where(ProductEntity.parent_id == other.id)).scalars().first()
    rules = [[{"field": "division", "op": "eq", "value": division}]]
    assert client.put("/api/metadata/brand-scopes/new_brand", headers=ADMIN, json={"label": "New brand", "rules": rules}).status_code == 200
    assert "new_brand" not in (other.brand_scopes or [])
    assert client.post("/api/metadata/eligibility/recompute", headers=ADMIN).json()["scopes_changed"] > 0
    session.expire_all()
    other = session.get(ProductEntity, other.id)
    assert "new_brand" in other.brand_scopes
    if sku is not None:
        assert "new_brand" in session.get(ProductEntity, sku.id).brand_scopes  # SKUs follow their style-color
