"""DM-04 bulk actions, DM-07 workflows, DM-09 comments, DM-12 carryover, GOV-01 rules, DM-06 compare, plus API smoke."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from pim.main import app
from pim.models import (
    Comment,
    Notification,
    ProductEntity,
    ProductValue,
    Rule,
    UserRole,
    ValueDraft,
    WorkflowDefinition,
    WorkflowItem,
)
from pim.services import bulk, workflow
from pim.services.collab import add_comment, parse_mentions
from pim.services.rules import eval_condition, preview_rule, run_rules
from pim.services.values import set_value


def _sc(session, style, color):
    return session.execute(select(ProductEntity).where(ProductEntity.level == "style_color", ProductEntity.style_number == style,
                                                       ProductEntity.color_code == color)).scalar_one()


def _pv(session, ent, code):
    return session.execute(select(ProductValue).where(ProductValue.entity_id == ent.id, ProductValue.attribute_code == code,
                                                      ProductValue.channel_code == "")).scalar_one_or_none()


# ---- DM-04 bulk --------------------------------------------------------------------------------------------
def test_dm04_bulk_preview_run_report_rollback(session, meta, admin, ingested):
    ids = [e.id for e in session.execute(select(ProductEntity).where(ProductEntity.level == "style_color", ProductEntity.style_number.in_(["200809", "200810"]))).scalars()]
    action = bulk.preview(session, meta, admin, "set_value", {"entity_ids": ids, "level": "style_color"}, {"attribute_code": "customer_color_name", "value": "Eco Black"})
    assert action.preview["total"] == 3 and len(action.preview["sample"]) == 3 and action.status == "preview"
    report = bulk.run(session, meta, admin, action)
    assert report["changed"] == 3 and action.status == "succeeded" and action.change_set_id
    fr = bulk.preview(session, meta, admin, "find_replace", {"entity_ids": ids, "level": "style_color"}, {"attribute_code": "customer_color_name", "find": "eco", "replace": "Ocean"})
    assert fr.preview["sample"][0]["after"] == "Ocean Black"
    bulk.run(session, meta, admin, fr)
    assert _pv(session, _sc(session, "200809", "FVP"), "customer_color_name").value_text == "Ocean Black"
    res = bulk.rollback(session, meta, admin, fr)
    assert res["restored"] == 3 and _pv(session, _sc(session, "200809", "FVP"), "customer_color_name").value_text == "Eco Black"
    # ERP attributes are refused and reported, never written
    bad = bulk.preview(session, meta, admin, "set_value", {"entity_ids": ids, "level": "style_color"}, {"attribute_code": "erp_color_description", "value": "x"})
    rep = bulk.run(session, meta, admin, bad)
    assert rep["failed"] == 3 and all("ERP" in (i["reason"] or "") for i in rep["items"])


def test_dm04_bulk_as_editor_lands_drafts(session, meta, merch, ingested):
    merch.data_rights["style_details"] = "edit"
    merch.permissions.add("bulk_edit")
    sc = _sc(session, "200809", "FVP")
    action = bulk.preview(session, meta, merch, "set_value", {"entity_ids": [sc.id], "level": "style_color"}, {"attribute_code": "customer_color_name", "value": "Festival Pink"})
    rep = bulk.run(session, meta, merch, action)
    assert rep["changed"] == 1 and "draft" in rep["items"][0]["reason"]
    assert session.execute(select(ValueDraft).where(ValueDraft.entity_id == sc.id)).scalars().first().state == "draft"
    send = bulk.preview(session, meta, merch, "send_for_approval", {"entity_ids": [sc.id], "level": "style_color"}, {})
    bulk.run(session, meta, merch, send)
    assert session.execute(select(ValueDraft).where(ValueDraft.entity_id == sc.id)).scalars().first().state == "proposed"


# ---- DM-07 workflows, DM-12 carryover -------------------------------------------------------------------------------
def test_dm07_inbox_advance_reject_and_dm12_step_skipping(session, meta, admin, merch, ecommerce, ingested):
    sc = _sc(session, "200809", "ECB")
    item = session.execute(select(WorkflowItem).where(WorkflowItem.entity_id == sc.id, WorkflowItem.state == "open")).scalar_one()
    assert item.assigned_role == "product_merch"
    assert len(workflow.inbox(session, merch, "mine")) >= 1 and workflow.inbox(session, ecommerce, "mine") == []
    workflow.advance(session, meta, merch, item, "design done")
    step2 = session.get(__import__("pim.models", fromlist=["WorkflowStep"]).WorkflowStep, item.current_step_id)
    assert step2.label == "Merch enrichment"
    workflow.advance(session, meta, merch, item)
    assert item.assigned_role == "ecommerce"
    first_step = next(s for s in session.get(WorkflowDefinition, item.workflow_id).steps if s.position == 1)
    workflow.reject(session, meta, ecommerce, item, first_step.id, "copy needs the fabric name", [{"attribute_code": "product_name", "comment": "please confirm"}])
    assert item.assigned_role == "product_merch" and item.assigned_email == merch.email
    assert session.execute(select(Comment).where(Comment.entity_id == sc.id)).scalars().all()
    assert session.execute(select(Notification).where(Notification.user_email == merch.email)).scalars().first()
    summary = workflow.manager_summary(session)
    assert summary["by_step"] and sum(b["count"] for b in summary["by_age"]) >= 1
    # DM-12: a new color whose Style Details and Design & Tech are already approved skips those steps
    st = session.get(ProductEntity, sc.parent_id)
    for code in ("product_name", "silhouette", "neckline", "strap_type", "underwire", "coverage", "product_features"):
        attr = meta.attributes[code]
        val = {"single_select": "triangle", "boolean": "no", "multi_select": ["removable_cups"], "text": "Skylar Top"}[attr.data_type]
        if code == "neckline":
            val = "v_neck"
        if code == "strap_type":
            val = "adjustable"
        if code == "coverage":
            val = "full"
        set_value(session, meta, admin, st, attr, val)
    for code, val in (("customer_color_name", "Eco Black"), ("color_family", "black"), ("print", "__NOT_APPLICABLE__")):
        set_value(session, meta, admin, sc, meta.attributes[code], val)
    fabric_attr = meta.attributes["fabric"]
    from pim.models import ReferenceEntity

    fab = ReferenceEntity(type_code="fabric", code="ecorib", label="EcoRib")
    session.add(fab)
    session.flush()
    set_value(session, meta, admin, sc, fabric_attr, fab.id)
    for code, val in (("care_instructions", "hand_wash_cold_dry_flat"), ("product_measurements", "x"), ("lining", "full")):
        set_value(session, meta, admin, st, meta.attributes[code], val)
    set_value(session, meta, admin, sc, meta.attributes["weight"], "0.1")
    model = ReferenceEntity(type_code="model", code="model_a", label="Model A")
    session.add(model)
    session.flush()
    set_value(session, meta, admin, sc, meta.attributes["model_profile"], model.id)
    session.flush()
    wf = session.get(WorkflowDefinition, item.workflow_id)
    item.state = "cancelled"
    new_item = workflow.start_workflow(session, meta, wf, sc, by="test")
    assert new_item is not None
    skipped = [h for h in new_item.history if h["event"].startswith("skipped")]
    assert skipped and "Design & Tech" in skipped[0]["step"] or new_item.current_step_id != wf.steps[0].id


def test_dm12_carryover_creates_drafts_without_overwriting(session, meta, admin, ingested):
    fvp, ecb = _sc(session, "200809", "FVP"), _sc(session, "200809", "ECB")
    set_value(session, meta, admin, fvp, meta.attributes["seo_title"], "Skylar Top | Vitamin A")
    set_value(session, meta, admin, fvp, meta.attributes["seo_description"], "Longline bralette")
    set_value(session, meta, admin, ecb, meta.attributes["seo_title"], "Keep me")
    session.flush()
    sibs = workflow.siblings(session, meta, ecb)
    assert sibs[0]["entity_id"] == fvp.id and sibs[0]["approved_values"] >= 2
    n = workflow.carryover(session, meta, admin, ecb, fvp)
    assert n == 1  # seo_title kept, seo_description carried as a draft
    d = session.execute(select(ValueDraft).where(ValueDraft.entity_id == ecb.id)).scalar_one()
    assert d.attribute_code == "seo_description" and d.proposed["carried_from"] == fvp.id


# ---- DM-09 comments ---------------------------------------------------------------------------------------
def test_dm09_mentions_notify(session, meta, admin, ingested):
    assert parse_mentions("@ashley.k and @dchristy@swimusa.com please look") == ["ashley.k@swimusa.com", "dchristy@swimusa.com"]
    sc = _sc(session, "200809", "FVP")
    c = add_comment(session, admin.email, sc, "what does NEW? mean @ashley.k", "erp_style_status")
    session.flush()
    assert c.mentions == ["ashley.k@swimusa.com"]
    n = session.execute(select(Notification).where(Notification.user_email == "ashley.k@swimusa.com")).scalar_one()
    assert n.kind == "mention" and n.link == f"/products/{sc.id}"


# ---- GOV-01 rules ----------------------------------------------------------------------------------------
def test_gov01_rule_preview_blocks_suspicious_constant_and_runs_when_active(session, meta, admin, ingested):
    sc = _sc(session, "200809", "FVP")
    assert eval_condition({"all": [{"field": "attr:erp_color_description", "op": "contains", "value": "pink"}]}, sc, {"erp_color_description": "FSTVL PINK"})
    rule = Rule(code="title_concat", label="Title from name and color", trigger="all", level="style_color",
                condition={"all": [{"field": "attr:customer_color_name", "op": "not_empty"}]},
                actions=[{"op": "concatenate", "target": "product_title", "parts": ["attr:product_name", "attr:customer_color_name"], "separator": " in "}],
                created_by=admin.email)
    session.add(rule)
    st = session.get(ProductEntity, sc.parent_id)
    set_value(session, meta, admin, st, meta.attributes["product_name"], "Skylar Top")
    set_value(session, meta, admin, sc, meta.attributes["customer_color_name"], "Festival Pink")
    session.flush()
    pv = preview_rule(session, meta, rule)
    assert pv["matched_total"] == 1 and pv["sample"] and not pv["suspicious_constants"]
    assert any("brand scope" in b for b in pv["blockers"])  # only one brand in the fixture, GOV-06 asks for 3
    # a blanket constant across unrelated brands is flagged
    blanket = Rule(code="blanket_care", label="Everything is hand wash", trigger="nightly", level="style",
                   actions=[{"op": "set", "target": "care_instructions", "value": "hand_wash_cold_line_dry"}], created_by=admin.email)
    session.add(blanket)
    session.flush()
    pv2 = preview_rule(session, meta, blanket)
    assert pv2["suspicious_constants"] and pv2["ok_to_activate"] is False
    rule.status = "active"
    results = run_rules(session, meta, "on_save", [sc], user_email=admin.email)
    assert results[0]["affected"] == 1
    out = _pv(session, sc, "product_title")
    assert out.value_text == "Skylar Top in Festival Pink" and out.source_type == "rule" and out.source_ref == "title_concat"


# ---- API smoke -------------------------------------------------------------------------------------------------
def test_phase2_api_smoke(session, meta, ingested):
    for email, role in (("admin@swimusa.com", "pim_admin"), ("viewer@swimusa.com", "viewer")):
        if not session.execute(select(UserRole).where(UserRole.email == email, UserRole.role_code == role)).first():
            session.add(UserRole(email=email, role_code=role, brand_scopes=[]))
    session.commit()
    client = TestClient(app)
    H = {"X-Forwarded-Email": "admin@swimusa.com"}
    V = {"X-Forwarded-Email": "viewer@swimusa.com"}
    assert any(s["code"] == "supplier" for s in client.get("/api/imports/sources", headers=H).json())
    from tests.conftest import FIXTURES

    with open(FIXTURES / "supplier_sample.csv", "rb") as fh:
        b = client.post("/api/imports/batches", files=[("file", ("supplier_sample.csv", fh, "text/csv"))], data={"source_code": "supplier", "level": "style_color"}, headers=H).json()
    assert b["status"] == "uploaded" and b["files"][0]["rows"] == 4
    sugg = client.get(f"/api/imports/batches/{b['id']}/suggest-mapping", headers=H).json()
    assert any(s["target"] == "style_number" for s in sugg)
    mapping = [{"target": "style_number", "sources": ["Style #"], "transforms": []}, {"target": "color_code", "sources": ["Colour"], "transforms": []},
               {"target": "weight", "sources": ["Weight (lb)"], "transforms": []}]
    r = client.put(f"/api/imports/batches/{b['id']}/mapping", json={"mapping": mapping, "match_keys": ["style_color"], "options": {}}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "mapped"
    assert client.post(f"/api/imports/batches/{b['id']}/validate", headers=H).json()["stats"]["rows"] == 4
    assert client.get(f"/api/imports/batches/{b['id']}/rows?status=ok", headers=H).json()["total"] >= 1
    assert client.post(f"/api/imports/batches/{b['id']}/match", headers=H).json()["stats"]["matched"] == 3
    rv = client.post(f"/api/imports/batches/{b['id']}/review", headers=H).json()
    assert rv["status"] == "reviewed" and rv["stats"]["adds"] >= 3
    c = client.post(f"/api/imports/batches/{b['id']}/commit", headers=H).json()
    assert c["status"] == "committed" and c["report"]["values_approved"] >= 3
    assert client.post(f"/api/imports/batches/{b['id']}/rollback", headers=H).json()["restored"] >= 3
    assert client.post("/api/imports/batches", data={"source_code": "supplier"}, headers=V).status_code == 403
    # worksheets
    sc = _sc(session, "200809", "FVP")
    w = client.post("/api/worksheets", json={"selection": {"entity_ids": [sc.id], "level": "style_color"}, "group_codes": ["style_details"], "include_erp_context": True}, headers=H).json()
    assert w["rows"] == 1 and client.get(w["url"], headers=H).status_code == 200
    # bulk
    p = client.post("/api/bulk/preview", json={"kind": "set_value", "selection": {"entity_ids": [sc.id], "level": "style_color"}, "params": {"attribute_code": "customer_color_name", "value": "Festival Pink"}}, headers=H).json()
    assert p["preview"]["total"] == 1
    assert client.post(f"/api/bulk/{p['id']}/run", headers=H).json()["report"]["changed"] == 1
    assert client.get("/api/bulk", headers=H).json()["total"] == 1
    # workflows, comments, notifications, compare, carryover, rules
    inbox = client.get("/api/workflows/inbox?scope=all", headers=H).json()
    assert inbox["total"] >= 1
    assert client.get("/api/workflows/manager", headers=H).json()["by_step"]
    cm = client.post(f"/api/products/{sc.id}/comments", json={"body": "ping @viewer@swimusa.com"}, headers=H).json()
    assert cm["mentions"] == ["viewer@swimusa.com"]
    notes = client.get("/api/notifications?unread=true", headers=V).json()
    assert notes["unread"] == 1
    assert client.post("/api/notifications/read", json={}, headers=V).json()["marked"] == 1
    ecb = _sc(session, "200809", "ECB")
    cmp = client.get(f"/api/products/compare?a={sc.id}&b={ecb.id}", headers=H).json()
    assert cmp["a"]["values"]["customer_color_name"]["value"] == "Festival Pink" and cmp["b"]["entity_id"] == ecb.id
    assert client.post(f"/api/products/{ecb.id}/copy-from", json={"from_entity_id": sc.id, "attribute_codes": ["customer_color_name"]}, headers=H).json()["results"][0]["outcome"] == "approved"
    assert client.get(f"/api/products/{ecb.id}/carryover", headers=H).json()["siblings"][0]["entity_id"] == sc.id
    rule = client.post("/api/rules", json={"code": "r1", "label": "R1", "level": "style_color", "actions": [{"op": "set", "target": "seo_keywords", "value": "swim"}]}, headers=H).json()
    assert client.post(f"/api/rules/{rule['id']}/activate", json={}, headers=H).status_code == 409
    pv = client.post(f"/api/rules/{rule['id']}/preview", headers=H).json()
    assert pv["ok_to_activate"] is False
    act = client.post(f"/api/rules/{rule['id']}/activate", json={"force": True, "reason": "single-brand catalog today"}, headers=H).json()
    assert act["status"] == "active"
    assert client.post(f"/api/rules/{rule['id']}/run", headers=H).json()["affected"] >= 1
    assert client.get("/api/rules/runs", headers=H).json()
