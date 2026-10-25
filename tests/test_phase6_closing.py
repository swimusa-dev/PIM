"""Phase 6, the closing phase: DM-13 relationships, GOV-02 whole-product restore, change-set rollback and history
retention, DM-07/DM-09 digest email, IMP-02 AI mapping suggester, GOV-04 adapter error rates, ARC-05 resolved stubs."""

from __future__ import annotations

import copy
import json
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.conftest import make_user

from pim.adapters.base import NotConfigured
from pim.adapters.mirakl_seller import MiraklSellerAdapter
from pim.adapters.target_plus import TargetPlusAdapter
from pim.config import get_settings
from pim.export.payloads import build_payloads
from pim.imports.ai_mapping import ai_suggester, parse_suggestions
from pim.imports.mapping import suggest_mappings
from pim.models import (
    AppEvent,
    Channel,
    ProductEntity,
    ProductRelationship,
    PublishRecord,
    ReadinessSnapshot,
    RelationshipType,
    UserRole,
    UserSetting,
    ValueHistory,
)
from pim.models._common import utcnow
from pim.services import collab, history
from pim.services import relationships as rel
from pim.services.changesets import rollback_change_set
from pim.services.collab import notify, send_digest
from pim.services.readiness import refresh_snapshots
from pim.services.telemetry import adapter_error_rates, record_adapter_error, scrub
from pim.services.values import set_value

ADMIN = {"X-Forwarded-Email": "admin@swimusa.com", "X-Forwarded-User": "u1"}
VIEWER = {"X-Forwarded-Email": "viewer@swimusa.com", "X-Forwarded-User": "u2"}
CHANNEL_STATE = ("target_schema", "attribute_mapping", "transforms", "image_profile", "config", "enabled", "version")


@pytest.fixture(autouse=True)
def _restore_seeded(session):
    saved = {c.code: {k: copy.deepcopy(getattr(c, k)) for k in CHANNEL_STATE} for c in session.execute(select(Channel)).scalars()}
    types = {t.code: {"label": t.label, "enabled": t.enabled, "direction": t.direction} for t in session.execute(select(RelationshipType)).scalars()}
    yield
    session.rollback()
    for c in session.execute(select(Channel)).scalars():
        for k, v in saved.get(c.code, {}).items():
            setattr(c, k, v)
    for t in session.execute(select(RelationshipType)).scalars():
        for k, v in types.get(t.code, {}).items():
            setattr(t, k, v)
    session.commit()


@pytest.fixture
def client(session, ingested):
    from pim.main import app

    for email, role in (("admin@swimusa.com", "pim_admin"), ("viewer@swimusa.com", "viewer")):
        if not session.execute(select(UserRole).where(UserRole.email == email, UserRole.role_code == role)).first():
            session.add(UserRole(email=email, role_code=role, brand_scopes=[]))
    session.commit()
    return TestClient(app)


def _sc(session, style="200809", color="FVP"):
    return session.execute(select(ProductEntity).where(ProductEntity.level == "style_color", ProductEntity.style_number == style,
                                                       ProductEntity.color_code == color)).scalar_one()


def _style(session, style="200809"):
    return session.execute(select(ProductEntity).where(ProductEntity.level == "style", ProductEntity.style_number == style)).scalar_one()


# ---------------------------------------------------------------------------------------------------
# DM-13 relationships
# ---------------------------------------------------------------------------------------------------
def test_dm13_types_seeded_links_are_directional_validated_and_inherited(session, meta, admin, ingested):
    codes = [t.code for t in rel.types(session)]
    assert codes == ["goes_great_with", "you_may_also_like", "set_pairs_with", "replaced_by"]
    fvp, ecb = _sc(session), _sc(session, "200809", "ECB")
    # two-way: the pasted list resolves style-colors in any format; the mirror row is written
    res = rel.add(session, admin, fvp, "goes_great_with", rel.parse_targets("200809-ECB, 200809 ECB, 999999-ZZZ"))
    assert len(res.created) == 1 and [s["reason"] for s in res.skipped] == ["already linked", "not found"]
    assert {r.from_entity_id for r in session.execute(select(ProductRelationship)).scalars()} == {fvp.id, ecb.id}
    assert [lk["target"]["entity_id"] for lk in rel.links_for(session, ecb)] == [fvp.id]
    # one-way stays one-way, and a product never relates to itself
    res = rel.add(session, admin, fvp, "you_may_also_like", [ecb.id, fvp.id])
    assert len(res.created) == 1 and res.skipped[0]["reason"] == "a product cannot relate to itself"
    assert [lk["type_code"] for lk in rel.links_for(session, ecb)] == ["goes_great_with"]
    # level is enforced: Replaced By is a style relationship, and colors inherit it
    with pytest.raises(rel.RelationshipError):
        rel.add(session, admin, fvp, "replaced_by", ["200810"])
    res = rel.add(session, admin, _style(session), "replaced_by", ["200810"])
    assert len(res.created) == 1
    inherited = [lk for lk in rel.links_for(session, fvp) if lk["inherited"]]
    assert inherited and inherited[0]["type_code"] == "replaced_by" and inherited[0]["target"]["style_number"] == "200810"
    # quantity only where the type allows it; discontinued targets are refused
    with pytest.raises(rel.RelationshipError):
        rel.add(session, admin, fvp, "you_may_also_like", [ecb.id], quantity=2)
    ecb.lifecycle_status = "discontinued"
    session.flush()
    res = rel.add(session, admin, fvp, "set_pairs_with", [ecb.id], quantity=2)
    assert res.created == [] and res.skipped[0]["reason"] == "is discontinued"
    # removing a two-way link removes its mirror
    own = [r for r in session.execute(select(ProductRelationship).where(ProductRelationship.from_entity_id == fvp.id,
                                                                        ProductRelationship.type_code == "goes_great_with")).scalars()]
    assert rel.remove(session, own[0]) == 2
    assert session.execute(select(ProductRelationship).where(ProductRelationship.type_code == "goes_great_with")).scalars().all() == []


def test_dm13_feed_source_and_broken_links_in_readiness(session, meta, admin, ingested):
    fvp, ecb = _sc(session), _sc(session, "200809", "ECB")
    rel.add(session, admin, fvp, "goes_great_with", [ecb.id])
    ch = session.get(Channel, "nordstrom")
    ch.config = {**ch.config, "feed_columns": [{"header": "Supplier SKU", "source": "core.sku"}, {"header": "Goes With", "source": "related:goes_great_with"}]}
    session.flush()
    p = build_payloads(session, meta, ch, [fvp])[0]
    assert p.feed["Goes With"] == "200809-ECB"
    refresh_snapshots(session, meta, [fvp])
    snap = session.get(ReadinessSnapshot, {"entity_id": fvp.id, "channel_code": "nordstrom"})
    assert not any("related product" in w for w in snap.detail["warnings"])
    ecb.lifecycle_status = "discontinued"
    session.flush()
    refresh_snapshots(session, meta, [fvp])
    snap = session.get(ReadinessSnapshot, {"entity_id": fvp.id, "channel_code": "nordstrom"})
    assert any("related product(s) discontinued or missing" in w for w in snap.detail["warnings"])
    assert build_payloads(session, meta, ch, [fvp])[0].feed["Goes With"] == ""  # a broken link never ships
    assert rel.broken_links(session, [fvp.id, ecb.id]) == {fvp.id: [f"goes_great_with: {ecb.label}"]}
    # the batched feed lookup matches the per-entity one and folds in inherited style links
    rel.add(session, admin, _style(session), "replaced_by", ["200810"])
    ch.config = {**ch.config, "feed_columns": [{"header": "Goes With", "source": "related:goes_great_with"}, {"header": "Replaced", "source": "related:replaced_by"}]}
    session.flush()
    batched = rel.related_external_ids_for(session, [fvp, ecb], ["goes_great_with", "replaced_by"])
    assert batched[fvp.id] == {"goes_great_with": [], "replaced_by": ["200810"]} and batched[ecb.id]["replaced_by"] == ["200810"]
    assert batched[fvp.id]["replaced_by"] == rel.related_external_ids(session, fvp, "replaced_by")
    assert build_payloads(session, meta, ch, [fvp])[0].feed["Replaced"] == "200810"


def test_dm13_api_types_links_rights_and_feed_source_validation(client, session, meta, admin):
    fvp, ecb = _sc(session), _sc(session, "200809", "ECB")
    assert [t["code"] for t in client.get("/api/relationship-types", headers=VIEWER).json()][:2] == ["goes_great_with", "you_may_also_like"]
    body = {"type_code": "goes_great_with", "paste": "200809-ECB, nope"}
    assert client.post(f"/api/products/{fvp.id}/relationships", json=body, headers=VIEWER).status_code == 403
    r = client.post(f"/api/products/{fvp.id}/relationships", json=body, headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1 and r.json()["skipped"] == [{"token": "nope", "reason": "not found"}]
    rows = client.get(f"/api/products/{ecb.id}/relationships", headers=VIEWER).json()["rows"]
    assert rows[0]["target"]["entity_id"] == fvp.id and rows[0]["direction"] == "two_way"
    # both ends of a two-way link get their readiness refreshed: discontinuing FVP must show on ECB after a relink
    fvp.lifecycle_status = "discontinued"
    session.commit()
    client.delete(f"/api/relationships/{rows[0]['id']}", headers=ADMIN)
    client.post(f"/api/products/{fvp.id}/relationships", json=body, headers=ADMIN)
    session.expire_all()
    snap = session.get(ReadinessSnapshot, {"entity_id": ecb.id, "channel_code": "nordstrom"})
    assert any("related product(s) discontinued" in w for w in snap.detail["warnings"])
    fvp.lifecycle_status = "active"
    session.commit()
    rows = client.get(f"/api/products/{ecb.id}/relationships", headers=VIEWER).json()["rows"]
    assert client.post(f"/api/products/{fvp.id}/relationships", json={"type_code": "replaced_by", "targets": ["200810"]}, headers=ADMIN).status_code == 400
    assert client.put("/api/relationship-types/goes_great_with", json={"label": "Pairs"}, headers=VIEWER).status_code == 403
    assert client.put("/api/relationship-types/goes_great_with", json={"label": "Pairs", "direction": "sideways"}, headers=ADMIN).status_code == 400
    assert client.put("/api/relationship-types/goes_great_with", json={"label": "Pairs"}, headers=ADMIN).json()["label"] == "Pairs"
    assert client.delete(f"/api/relationships/{rows[0]['id']}", headers=ADMIN).json()["deleted"] == 2
    assert client.get(f"/api/products/{fvp.id}/relationships", headers=ADMIN).json()["rows"] == []
    transport = client.get("/api/channels/nordstrom/transport", headers=ADMIN).json()
    bad = {**transport, "feed_columns": [{"header": "Goes With", "source": "related:ghost"}]}
    assert client.put("/api/channels/nordstrom/transport", json=bad, headers=ADMIN).status_code == 400
    good = {**transport, "feed_columns": [{"header": "Goes With", "source": "related:goes_great_with"}]}
    assert client.put("/api/channels/nordstrom/transport", json=good, headers=ADMIN).status_code == 200


# ---------------------------------------------------------------------------------------------------
# GOV-02 restore to a point in time, change sets, retention
# ---------------------------------------------------------------------------------------------------
def test_gov02_restore_product_to_point_in_time_and_roll_the_restore_back(session, meta, admin, ingested):
    fvp = _sc(session)
    title, color = meta.attributes["product_title"], meta.attributes["customer_color_name"]
    assert set_value(session, meta, admin, fvp, title, "Skylar Top").outcome == "approved"
    session.flush()
    time.sleep(0.02)
    t1 = utcnow()
    time.sleep(0.02)
    set_value(session, meta, admin, fvp, title, "Skylar Longline Top")
    set_value(session, meta, admin, fvp, color, "Festival Pink")
    session.flush()
    as_of = history.values_as_of(session, fvp.id, t1)
    assert as_of[("product_title", "")]["value"] == "Skylar Top" and as_of[("customer_color_name", "")] is None
    res = history.restore_to(session, meta, admin, fvp, t1)
    assert res["restored"] == 2
    from pim.models import ProductValue

    rows = {pv.attribute_code: pv for pv in session.execute(select(ProductValue).where(ProductValue.entity_id == fvp.id,
                                                                                          ProductValue.attribute_code.in_(["product_title", "customer_color_name"]))).scalars()}
    assert rows["product_title"].value_text == "Skylar Top" and "customer_color_name" not in rows
    listed = history.list_change_sets(session, entity_id=fvp.id)
    assert listed["rows"][0]["id"] == res["change_set_id"] and listed["rows"][0]["kind"] == "restore" and listed["rows"][0]["changes"] == 2
    # the restore is itself a change set: rolling it back puts the newer values back as a unit
    back = rollback_change_set(session, meta, admin, res["change_set_id"])
    assert back["restored"] == 2
    rows = {pv.attribute_code: pv.value_text for pv in session.execute(select(ProductValue).where(ProductValue.entity_id == fvp.id)).scalars()}
    assert rows["product_title"] == "Skylar Longline Top" and rows["customer_color_name"] == "Festival Pink"
    # a user without Approve rights gets every attribute reported, nothing written, and no change set is created
    merch = make_user(session, "merch@swimusa.com", ["viewer"])
    before = history.list_change_sets(session, entity_id=fvp.id)["total"]
    res2 = history.restore_to(session, meta, merch, fvp, t1)
    assert res2["restored"] == 0 and all(r["outcome"] == "rejected" for r in res2["results"]) and res2["change_set_id"] is None
    assert history.list_change_sets(session, entity_id=fvp.id)["total"] == before
    # restoring to before the ERP load never rewrites ERP-owned attributes (P1), only the PIM-owned ones
    res3 = history.restore_to(session, meta, admin, fvp, utcnow() - timedelta(days=1))
    erp_rows = [r for r in res3["results"] if meta.attributes[r["attribute_code"]].is_erp]
    assert erp_rows and all(r["outcome"] == "skipped" and "ERP" in r["message"] for r in erp_rows)
    from pim.models import ProductValue as PV

    assert session.execute(select(PV).where(PV.entity_id == fvp.id, PV.attribute_code == erp_rows[0]["attribute_code"])).scalars().first() is not None
    assert all(r["outcome"] != "skipped" for r in res3["results"] if r["attribute_code"] in ("product_title", "customer_color_name"))


def test_gov02_api_restore_to_and_change_set_rollback(client, session, meta, admin):
    fvp = _sc(session)
    set_value(session, meta, admin, fvp, meta.attributes["product_title"], "One")
    session.commit()
    time.sleep(0.02)
    t1 = utcnow()
    time.sleep(0.02)
    set_value(session, meta, admin, fvp, meta.attributes["product_title"], "Two")
    session.commit()
    assert client.post(f"/api/products/{fvp.id}/restore-to", json={"at": t1.isoformat()}, headers=VIEWER).json()["restored"] == 0
    r = client.post(f"/api/products/{fvp.id}/restore-to", json={"at": t1.isoformat()}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["restored"] == 1
    cs_id = r.json()["change_set_id"]
    sets = client.get(f"/api/change-sets?entity_id={fvp.id}", headers=ADMIN).json()
    assert sets["rows"][0]["id"] == cs_id and sets["total"] >= 1
    assert client.post(f"/api/change-sets/{cs_id}/rollback", headers=VIEWER).status_code == 403
    assert client.post(f"/api/change-sets/{cs_id}/rollback", headers=ADMIN).json()["restored"] == 1
    assert client.post(f"/api/change-sets/{cs_id}/rollback", headers=ADMIN).status_code == 409  # already rolled back
    assert client.get(f"/api/change-sets/{cs_id}", headers=ADMIN).json()["rolled_back_at"]
    # import, bulk and ingest sets never roll back from here (their own pages do, or never for the ERP load)
    from pim.models import ChangeSet

    ingest_cs = session.execute(select(ChangeSet).where(ChangeSet.kind == "ingest")).scalars().first()
    assert ingest_cs is not None
    r = client.post(f"/api/change-sets/{ingest_cs.id}/rollback", headers=ADMIN)
    assert r.status_code == 409 and "cannot be rolled back" in r.json()["detail"]
    assert client.get(f"/api/change-sets/{ingest_cs.id}", headers=ADMIN).json()["rollbackable"] is False
    imp = ChangeSet(kind="import", created_by="x", description="batch")
    session.add(imp)
    session.commit()
    r = client.post(f"/api/change-sets/{imp.id}/rollback", headers=ADMIN)
    assert r.status_code == 409 and "import batch page" in r.json()["detail"]
    # the History tab's "Restore to this point" passes the row id: the row's own change is undone too
    hist = client.get(f"/api/products/{fvp.id}/history?attribute_code=product_title", headers=ADMIN).json()["rows"]
    two = next(h for h in hist if (h["new_value"] or {}).get("value") == "Two")
    r = client.post(f"/api/products/{fvp.id}/restore-to", json={"history_id": two["id"]}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["restored"] == 1
    from pim.models import ProductValue

    session.expire_all()
    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == fvp.id, ProductValue.attribute_code == "product_title")).scalars().one()
    assert pv.value_text == "One"
    assert client.post(f"/api/products/{fvp.id}/restore-to", json={}, headers=ADMIN).status_code == 400
    assert client.post(f"/api/products/{fvp.id}/restore-to", json={"history_id": "nope"}, headers=ADMIN).status_code == 404


def test_gov02_history_prune_keeps_the_hot_window(session, meta, admin, ingested):
    fvp = _sc(session)
    set_value(session, meta, admin, fvp, meta.attributes["product_title"], "Recent")
    session.flush()
    now = utcnow()
    for years in (1, 3, 5):
        session.add(ValueHistory(entity_level="style_color", entity_id=fvp.id, attribute_code="product_title", channel_code="",
                                 old_value=None, new_value={"value": f"{years}y"}, source_type="user", set_by="x",
                                 set_at=now - timedelta(days=366 * years)))
    session.flush()
    assert history.prune_history(session, now, hot_years=0) == 0  # retention off: nothing leaves Lakebase
    assert history.prune_history(session, now) == 2  # the 3 and 5 year old rows; PIM_HISTORY_HOT_YEARS defaults to 2
    left = session.execute(select(ValueHistory).where(ValueHistory.entity_id == fvp.id)).scalars().all()
    assert all(h.set_at >= now - timedelta(days=366 * 2) for h in left)  # the ingest and edit rows stay with the 1 year row
    assert sorted(h.new_value["value"] for h in left if h.new_value and str(h.new_value.get("value", "")).endswith("y")) == ["1y"]


# ---------------------------------------------------------------------------------------------------
# DM-07 / DM-09 digest email
# ---------------------------------------------------------------------------------------------------
class FakeSmtp:
    sent: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):  # noqa: ANN002
        return False

    def send_message(self, msg):  # noqa: ANN001
        FakeSmtp.sent.append({"to": msg["To"], "subject": msg["Subject"], "body": msg.get_content()})


def test_dm09_digest_emails_per_user_on_their_schedule(session, monkeypatch):
    FakeSmtp.sent = []
    monkeypatch.setattr(get_settings(), "app_base_url", "https://pim.example")
    now = utcnow()
    notify(session, "a@swimusa.com", "mention", "Dave mentioned you on Skylar Top", "what does NEW mean", "/products/1")
    notify(session, "a@swimusa.com", "workflow", "Copy review is due", None, "/workflows")
    notify(session, "b@swimusa.com", "mention", "Weekly person", None, None)
    notify(session, "c@swimusa.com", "mention", "Opted out", None, None)
    collab.set_digest_frequency(session, "b@swimusa.com", "weekly")
    collab.user_setting(session, "b@swimusa.com").last_digest_at = now - timedelta(days=2)
    collab.set_digest_frequency(session, "c@swimusa.com", "off")
    with pytest.raises(ValueError):
        collab.set_digest_frequency(session, "c@swimusa.com", "hourly")
    sent = send_digest(session, smtp_factory=FakeSmtp, now=now)
    assert sent == {"a@swimusa.com": 2}
    assert FakeSmtp.sent[0]["to"] == "a@swimusa.com" and "2 new notifications" in FakeSmtp.sent[0]["subject"]
    assert "https://pim.example/products/1" in FakeSmtp.sent[0]["body"] and "Mention (1)" in FakeSmtp.sent[0]["body"]
    assert session.get(UserSetting, "a@swimusa.com").last_digest_at == now
    # the weekly user is emailed once seven days have passed; the opted-out user never
    sent = send_digest(session, smtp_factory=FakeSmtp, now=now + timedelta(days=8))
    assert sent == {"b@swimusa.com": 1} and len(FakeSmtp.sent) == 2
    assert send_digest(session, smtp_factory=FakeSmtp, now=now + timedelta(days=9)) == {}
    # a failed send leaves the notifications queued for the next run
    notify(session, "a@swimusa.com", "mention", "Again", None, None)

    class Broken(FakeSmtp):
        def send_message(self, msg):  # noqa: ANN001
            raise ConnectionError("smtp down")

    assert send_digest(session, smtp_factory=Broken, now=now + timedelta(days=10)) == {}
    assert session.execute(select(collab.Notification).where(collab.Notification.emailed_at.is_(None),
                                                               collab.Notification.user_email == "a@swimusa.com")).scalars().one().title == "Again"


def test_dm09_me_settings_api(client, session):
    assert client.get("/api/me/settings", headers=VIEWER).json()["digest_frequency"] == "daily"
    assert client.put("/api/me/settings", json={"digest_frequency": "weekly"}, headers=VIEWER).json()["digest_frequency"] == "weekly"
    assert client.put("/api/me/settings", json={"digest_frequency": "never"}, headers=VIEWER).status_code == 400
    assert session.get(UserSetting, "viewer@swimusa.com").digest_frequency == "weekly"


# ---------------------------------------------------------------------------------------------------
# IMP-02 AI mapping suggester
# ---------------------------------------------------------------------------------------------------
class FakeClient:
    reply = "[]"
    prompts: list[str] = []

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def chat(self, messages, max_tokens, temperature=0.3):  # noqa: ANN001
        FakeClient.prompts.append(messages[-1]["content"])
        return {"content": FakeClient.reply, "prompt_tokens": 10, "completion_tokens": 5}


def test_imp02_ai_mapping_suggester_behind_the_flag_never_auto_accepts(session, meta, monkeypatch):
    from pim.ai.service import AIService

    assert ai_suggester(session, meta, "style_color") is None  # PIM_FEATURE_AI_MAPPING_SUGGEST off by default
    monkeypatch.setattr(get_settings(), "feature_ai_mapping_suggest", True)
    FakeClient.reply = json.dumps([{"column": "Story", "attribute_code": "product_description", "confidence": 0.91, "reason": "long copy"},
                                   {"column": "Story", "attribute_code": "no_such_attribute", "confidence": 0.99},
                                   {"column": "Unknown col", "attribute_code": "product_title", "confidence": 0.95},
                                   {"column": "Hue", "attribute_code": "customer_color_name", "confidence": 0.4}])
    svc = AIService(client_factory=FakeClient)
    suggest = ai_suggester(session, meta, "style_color", {"Story": ["A ribbed top", "Soft"]}, service=svc)
    assert suggest is not None
    out = suggest(["Story", "Hue"])
    assert [(o["column"], o["target"]) for o in out] == [("Story", "product_description"), ("Hue", "customer_color_name")]
    assert "A ribbed top" in FakeClient.prompts[-1] and "product_description" in FakeClient.prompts[-1]
    merged = suggest_mappings(["Product Title", "Story", "Hue"], meta, "style_color", threshold=0.7, ai_suggest=suggest)
    by_col = {m["column"]: m for m in merged}
    assert by_col["Product Title"]["reason"].startswith("header matches") and by_col["Story"]["reason"] == "long copy"
    assert "Hue" not in by_col  # below the threshold: hidden, never applied
    assert parse_suggestions("not json", meta, {"Story"}) == []


# ---------------------------------------------------------------------------------------------------
# GOV-04 adapter error rates, ARC-05 resolved stubs
# ---------------------------------------------------------------------------------------------------
def test_gov04_adapter_errors_are_scrubbed_and_rated(client, session, meta, admin):
    ev = record_adapter_error(session, "walmart-mp", "401 for token=abc123 secret: xyz at /v3/feeds", {"publish_id": "p1", "adapter": "walmart_mp"})
    assert ev.payload["error"] == "401 for token=<redacted> secret=<redacted> at /v3/feeds" and scrub("plain text") == "plain text"
    # every credential form loses its value (GOV-05): key=value, key: value, Authorization: Bearer x, bare Bearer x
    assert scrub("HTTP 401 Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc") == "HTTP 401 Authorization=<redacted>"
    assert scrub("x-api-key: k-12345 then client_secret = s3cr3t end") == "x-api-key=<redacted> then client_secret=<redacted> end"
    assert scrub("header Bearer abcdefghijklmnop sent") == "header Bearer <redacted> sent"
    session.add(PublishRecord(channel_code="walmart-mp", channel_version=1, kind="publish", mode="full", status="failed", created_by="x"))
    session.add(PublishRecord(channel_code="walmart-mp", channel_version=1, kind="publish", mode="full", status="completed", created_by="x"))
    record_adapter_error(session, "air_dam", "500 from Air", {"op": "poll"})
    session.commit()
    rates = {r["adapter"]: r for r in adapter_error_rates(session)}
    # one row per channel: the publish record and its adapter_error event count once, never as a second 100 percent row
    assert set(rates) == {"walmart-mp", "air_dam"}
    assert rates["walmart-mp"]["calls"] == 2 and rates["walmart-mp"]["errors"] == 1 and rates["walmart-mp"]["error_rate"] == 0.5
    assert rates["walmart-mp"]["last_error"].startswith("401")
    assert rates["air_dam"]["calls"] == 0 and rates["air_dam"]["errors"] == 1 and rates["air_dam"]["error_rate"] is None
    t = client.get("/api/admin/telemetry", headers=ADMIN).json()
    assert {r["adapter"] for r in t["adapter_error_rates"]} == {"walmart-mp", "air_dam"} and t["adapter_errors"][0]["adapter"] == "air_dam"
    events = session.execute(select(AppEvent).where(AppEvent.kind == "adapter_error", AppEvent.source == "walmart-mp")).scalars().all()
    assert len(events) == 1 and events[0].payload["publish_id"] == "p1" and events[0].payload["adapter"] == "walmart_mp"


def test_arc05_resolved_stubs_point_at_rithum():
    tp = TargetPlusAdapter()
    assert tp.validate([{"core.style_number": "1", "core.sku": "1-S", "product_title": "Fine", "gtin": "840000000011", "image_width": 1200, "image_height": 1200}]).ok
    assert not tp.validate([{"core.style_number": "1", "core.sku": "1-S", "product_title": "T" * 151, "gtin": "840000000011", "image_width": 1200, "image_height": 1200}]).ok
    with pytest.raises(NotConfigured, match="D-02"):
        tp.publish([{}])
    with pytest.raises(NotConfigured, match="D-01"):
        MiraklSellerAdapter().publish([{}])
    import pim.adapters.mirakl_seller as mirakl_mod
    import pim.adapters.target_plus as tp_mod

    assert "D-01" in mirakl_mod.__doc__ and "D-02" in tp_mod.__doc__ and "TODO(decision" not in (mirakl_mod.__doc__ + tp_mod.__doc__)
