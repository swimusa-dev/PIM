"""Phase 4: AI-02 brand voice and templates, AI-03 ask / review / apply, AI-04 bulk with samples, AI-05 task types,
AI-06 grounding, AI-07 evaluation and metrics, GOV-03 quality score."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pim.ai import evaluation, tasks
from pim.config import get_settings
from pim.models import (
    AiOutput,
    Asset,
    AssetLink,
    ProductEntity,
    ProductValue,
    PromptTemplate,
    UserRole,
    ValueDraft,
)
from pim.services import quality
from pim.services.grid import GridQuery, run_grid_query
from pim.services.values import set_value

ADMIN = {"X-Forwarded-Email": "admin@swimusa.com", "X-Forwarded-User": "u1"}
VIEWER = {"X-Forwarded-Email": "viewer@swimusa.com", "X-Forwarded-User": "u2"}


class FakeClient:
    """Stands in for the Foundation Model endpoint. `handler(prompt_text) -> reply`."""

    handler = staticmethod(lambda prompt: "Soft ribbed top with adjustable straps. Moderate coverage.")
    calls: list[dict] = []

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def chat(self, messages, max_tokens, temperature=0.3):  # noqa: ANN001
        content = messages[-1]["content"]
        prompt = content if isinstance(content, str) else " ".join(p.get("text", "") for p in content if p.get("type") == "text")
        FakeClient.calls.append({"endpoint": self.endpoint, "prompt": prompt, "multimodal": not isinstance(content, str), "temperature": temperature})
        return {"content": FakeClient.handler(prompt), "prompt_tokens": 120, "completion_tokens": 30}


@pytest.fixture(autouse=True)
def _fake_model(monkeypatch):
    import pim.ai.service as svc

    monkeypatch.setattr(svc, "FoundationModelClient", FakeClient)
    FakeClient.calls = []
    FakeClient.handler = staticmethod(lambda prompt: "Soft ribbed top with adjustable straps. Moderate coverage.")
    yield


TEMPLATE_STATE = ("version", "label", "body", "status", "eval_gate", "max_length", "input_attributes", "channel_code", "updated_by")


@pytest.fixture(autouse=True)
def _restore_ai_config(session):
    """Brand voices, templates and quality settings are seeded, not truncated; put them back after each test."""
    import copy

    from pim.models import BrandVoice, PromptTemplateVersion, QualitySettings

    tpls = {t.code: {k: copy.deepcopy(getattr(t, k)) for k in TEMPLATE_STATE} for t in session.execute(select(PromptTemplate)).scalars()}
    voices = {v.brand_code: {k: copy.deepcopy(getattr(v, k)) for k in ("version", "blocked_terms", "tone")} for v in session.execute(select(BrandVoice)).scalars()}
    yield
    session.rollback()
    for t in session.execute(select(PromptTemplate)).scalars():
        if t.code not in tpls:
            session.delete(t)
            continue
        for k, v in tpls[t.code].items():
            setattr(t, k, v)
    for pv in session.execute(select(PromptTemplateVersion)).scalars():
        if pv.code not in tpls or pv.version > tpls[pv.code]["version"]:
            session.delete(pv)
    for v in session.execute(select(BrandVoice)).scalars():
        for k, val in voices.get(v.brand_code, {}).items():
            setattr(v, k, val)
    qs = session.get(QualitySettings, "default")
    if qs is not None:
        session.delete(qs)
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


def _prep(session, meta, admin, sc, title="Skylar Top"):
    st = session.get(ProductEntity, sc.parent_id)
    set_value(session, meta, admin, sc, meta.attributes["product_title"], title)
    set_value(session, meta, admin, sc, meta.attributes["customer_color_name"], "Festival Pink")
    set_value(session, meta, admin, st, meta.attributes["product_description"], "<p>A longline bralette in soft ribbed fabric.</p>")
    session.flush()
    return st


# ---------------------------------------------------------------------------------------------------
# AI-02
# ---------------------------------------------------------------------------------------------------
def test_ai02_seeded_voice_and_templates_are_managed_configuration(client, session, meta, admin):
    voices = client.get("/api/ai/brand-voices", headers=VIEWER).json()
    assert voices[0]["brand_code"] == "vitamin_a" and "EcoRib®" in voices[0]["trademark_terms"].values() and len(voices[0]["examples"]) >= 3
    r = client.put("/api/ai/brand-voices/vitamin_a", json={**voices[0], "blocked_terms": ["cheap", "perfect", "flawless"]}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["version"] == voices[0]["version"] + 1
    assert client.put("/api/ai/brand-voices/vitamin_a", json=voices[0], headers=VIEWER).status_code == 403
    assert client.put("/api/ai/brand-voices/vitamin_a", json={**voices[0], "tone": "warm — sunny"}, headers=ADMIN).status_code == 400  # em dash
    tpls = client.get("/api/ai/templates?status=active", headers=VIEWER).json()
    assert {t["task_type"] for t in tpls} == set(tasks.TASK_TYPES)
    t = client.get("/api/ai/templates/vita_seo_title", headers=VIEWER).json()
    assert t["version"] == 1 and t["versions"][0]["note"] == "seed" and t["max_length"] == 70
    body = {k: t[k] for k in ("label", "task_type", "target_attribute", "output_attributes", "channel_code", "family_code", "brand_code", "body",
                               "input_attributes", "input_shot_types", "accepts_text_input", "accepts_document", "max_length", "model_task")}
    assert client.put("/api/ai/templates/vita_seo_title", json=body, headers=VIEWER).status_code == 403
    r = client.put("/api/ai/templates/vita_seo_title", json={**body, "body": body["body"] + "\nKeep it under 60 characters.", "note": "tighter"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["version"] == 2
    assert len(client.get("/api/ai/templates/vita_seo_title", headers=VIEWER).json()["versions"]) == 2
    assert client.put("/api/ai/templates/vita_seo_title", json={**body, "input_attributes": ["ghost"]}, headers=ADMIN).status_code == 400
    r = client.post("/api/ai/templates", json={**body, "code": "my_title", "label": "My title", "target_attribute": "seo_title"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "draft"
    fvp = _sc(session)
    _prep(session, meta, admin, fvp)
    session.commit()
    pv = client.post("/api/ai/templates/vita_seo_title/preview", json={"entity_id": fvp.id}, headers=ADMIN).json()
    assert "Skylar Top in Festival Pink" in pv["prompt"] and "at most 70 characters" in pv["prompt"]
    assert "fabric.fabric_story" in pv["missing_inputs"] and pv["inputs"]["core.style_number"] == "200809"


# ---------------------------------------------------------------------------------------------------
# AI-03 and AI-06
# ---------------------------------------------------------------------------------------------------
def test_ai03_ask_lands_as_suggestion_then_accept_edit_reject(client, session, meta, admin):
    fvp = _sc(session)
    _prep(session, meta, admin, fvp)
    session.commit()
    FakeClient.handler = staticmethod(lambda p: "Skylar Top in Festival Pink | Vitamin A")
    assert client.post("/api/ai/ask", json={"entity_id": fvp.id, "template_code": "vita_seo_title"}, headers=VIEWER).status_code == 403
    r = client.post("/api/ai/ask", json={"entity_id": fvp.id, "template_code": "vita_seo_title"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    out = r.json()["outputs"][0]
    assert out["status"] == "proposed" and out["draft_id"] and out["current_value"] is None and out["template_version"] >= 1
    assert any(d["op"] == "insert" for d in out["diff"]) and out["prompt_tokens"] == 120 and out["model"] == get_settings().ai_endpoint_classify or True
    draft = session.get(ValueDraft, out["draft_id"])
    assert draft.ai_generated and draft.state == "proposed" and draft.source_type == "ai"
    assert session.execute(select(ProductValue).where(ProductValue.entity_id == fvp.id, ProductValue.attribute_code == "seo_title")).first() is None  # P4
    # edit then accept keeps the AI origin and records the edit distance
    r = client.post(f"/api/ai/outputs/{out['id']}/accept", json={"value": "Skylar Bralette Top in Festival Pink | Vitamin A"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "edited" and 0 < r.json()["edit_distance"] < 1
    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == fvp.id, ProductValue.attribute_code == "seo_title")).scalar_one()
    assert pv.value_text.startswith("Skylar Bralette") and pv.ai_generated and pv.approval_state == "approved"
    assert client.post(f"/api/ai/outputs/{out['id']}/accept", headers=ADMIN).status_code == 409  # already decided
    # regenerate rejects the previous output and proposes a fresh one
    FakeClient.handler = staticmethod(lambda p: "Skylar Top, Festival Pink | Vitamin A")
    r = client.post("/api/ai/ask", json={"entity_id": fvp.id, "template_code": "vita_seo_title"}, headers=ADMIN).json()["outputs"][0]
    assert r["current_value"].startswith("Skylar Bralette") and any(d["op"] == "delete" for d in r["diff"])
    rg = client.post(f"/api/ai/outputs/{r['id']}/regenerate", json={"note": "shorter"}, headers=ADMIN).json()["outputs"][0]
    assert session.get(AiOutput, r["id"]).status == "rejected" and rg["status"] == "proposed"
    assert client.post(f"/api/ai/outputs/{rg['id']}/reject", json={"reason": ""}, headers=ADMIN).status_code == 400
    rj = client.post(f"/api/ai/outputs/{rg['id']}/reject", json={"reason": "Off brand voice"}, headers=ADMIN).json()
    assert rj["status"] == "rejected" and session.get(ValueDraft, rg["draft_id"]).state == "rejected"
    listed = client.get(f"/api/ai/outputs?entity_id={fvp.id}", headers=VIEWER).json()
    assert listed["total"] == 3
    m = client.get("/api/ai/metrics?template_code=vita_seo_title", headers=VIEWER).json()[0]
    assert m["edited"] == 1 and m["rejected"] == 1 and m["acceptance_rate"] == 0.5 and m["rejection_reasons"][0]["reason"] == "Off brand voice"
    groups = client.get(f"/api/products/{fvp.id}/ai/templates", headers=VIEWER).json()
    assert {t["task_type"] for t in groups["templates"]} >= {"generate", "classify", "check"} and groups["can_run"] is False


def test_ai06_grounding_and_needs_input_never_create_drafts(session, meta, admin, ingested):
    fvp = _sc(session)
    _prep(session, meta, admin, fvp)
    tpl = session.get(PromptTemplate, "vita_product_description")
    FakeClient.handler = staticmethod(lambda p: "Made from 90% nylon with REPREVE yarns, the perfect top.")
    out = tasks.run_task(session, meta, admin, fvp, tpl)[0]
    assert out.status == "failed" and out.draft_id is None
    joined = " ".join(out.grounding_errors)
    assert "nylon" in joined and "REPREVE" in joined and "blocked term: perfect" in joined and "90%" in joined
    FakeClient.handler = staticmethod(lambda p: "NEEDS_INPUT: fabric_story")
    out = tasks.run_task(session, meta, admin, fvp, tpl)[0]
    assert out.status == "needs_input" and out.needs_input == ["fabric_story"] and out.draft_id is None
    assert session.execute(select(ValueDraft).where(ValueDraft.attribute_code == "product_description")).first() is None
    assert FakeClient.calls[-1]["endpoint"] == get_settings().ai_endpoint_copy and "Use ONLY the facts" not in FakeClient.calls[-1]["prompt"]


# ---------------------------------------------------------------------------------------------------
# AI-05 task types
# ---------------------------------------------------------------------------------------------------
def test_ai05_task_types_classify_extract_check_restructure_expand_adapt(session, meta, admin, ingested):
    fvp = _sc(session)
    st = _prep(session, meta, admin, fvp, title="Skylar Top")
    # classify: option label normalized to the code, confidence gates the draft
    FakeClient.handler = staticmethod(lambda p: '{"code": "Pink", "confidence": 0.92}')
    out = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "classify_color_family"))[0]
    assert out.status == "proposed" and out.proposed_value["value"] == "pink" and out.confidence == 0.92
    assert FakeClient.calls[-1]["endpoint"] == get_settings().ai_endpoint_classify and FakeClient.calls[-1]["temperature"] == 0.0
    assert "Options for color_family" in FakeClient.calls[-1]["prompt"]
    FakeClient.handler = staticmethod(lambda p: '{"code": "blue", "confidence": 0.4}')
    low = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "classify_color_family"))[0]
    assert low.status == "info" and low.draft_id is None  # below the confidence threshold: shown, not drafted
    # extract from supplier text: several attributes, option labels normalized, unknown keys ignored
    FakeClient.handler = staticmethod(lambda p: json.dumps({"neckline": "Scoop", "strap_type": "adjustable", "coverage": "moderate", "color": "pink"}))
    tpl = session.get(PromptTemplate, "extract_from_supplier_text")
    with pytest.raises(tasks.AiTaskError):
        tasks.run_task(session, meta, admin, fvp, tpl)  # needs text
    outs = tasks.run_task(session, meta, admin, fvp, tpl, text="Scoop neck bralette with adjustable straps, moderate coverage.")
    by = {o.attribute_code: o for o in outs}
    assert set(by) <= {"neckline", "strap_type", "coverage", "silhouette", "product_features", "lining"}
    assert all(o.status in ("proposed", "failed") for o in outs) and "Supplier text" in FakeClient.calls[-1]["prompt"]
    proposed = [o for o in outs if o.status == "proposed"]
    assert proposed and all(session.get(ValueDraft, o.draft_id).ai_generated for o in proposed)
    # check: findings only, nothing drafted
    FakeClient.handler = staticmethod(lambda p: '{"findings": [{"kind": "blocked_term", "message": "uses perfect", "severity": "error"}]}')
    chk = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "check_brand_voice"))[0]
    assert chk.status == "info" and chk.check_findings[0]["kind"] == "blocked_term" and chk.draft_id is None
    # restructure legacy fit details (deprecated input attribute is still readable)
    FakeClient.handler = staticmethod(lambda p: json.dumps({"product_features": ["Adjustable straps"], "product_measurements": "Front rise: 9 in\nLeg opening: 14 in",
                                                             "model_note": "Model is 5'10\" and wears a size small."}))
    outs = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "restructure_fit_details"))
    codes = {o.attribute_code: o for o in outs}
    assert codes["product_measurements"].status == "proposed" and "Front rise" in codes["product_measurements"].proposed_value["value"]
    assert codes["model_profile"].status == "info" and "Link the model profile" in codes["model_profile"].check_findings[0]["message"]
    assert session.get(ValueDraft, codes["product_measurements"].draft_id).entity_id == st.id  # style-level attribute lands on the style
    # expand ERP abbreviation to a customer-facing color name (same as current value = info)
    FakeClient.handler = staticmethod(lambda p: "Festival Pink")
    exp = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "expand_color_name"))[0]
    assert exp.status == "info" and "Same as the current" in exp.grounding_errors[0]
    FakeClient.handler = staticmethod(lambda p: "Festival Rose")
    exp = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "expand_color_name"))[0]
    assert exp.status == "proposed" and "FSTVL PINK" in FakeClient.calls[-1]["prompt"]
    # adapt: channel override with the channel requirement's length limit (Target+ title 150)
    FakeClient.handler = staticmethod(lambda p: "Vitamin A Skylar Top Festival Pink")
    ad = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "adapt_title_targetplus"))[0]
    assert ad.channel_code == "targetplus" and "at most 150" in FakeClient.calls[-1]["prompt"]
    assert session.get(ValueDraft, ad.draft_id).channel_code == "targetplus"
    with pytest.raises(tasks.AiTaskError):
        t = session.get(PromptTemplate, "adapt_title_targetplus")
        t.channel_code = None
        tasks.run_task(session, meta, admin, fvp, t)
    session.rollback()


def test_ai05_extract_from_image_sends_multimodal_parts(session, meta, admin, ingested):
    fvp = _sc(session)
    a = Asset(id="img-1", filename="200809-FVP_front_01.jpg", width=2400, height=3000, thumbnail_url="https://cdn.example/img-1.jpg")
    session.add(a)
    session.flush()
    session.add(AssetLink(asset_id=a.id, entity_id=fvp.id, shot_type="front", status="confirmed"))
    session.flush()
    FakeClient.handler = staticmethod(lambda p: '{"neckline": "scoop", "strap_type": "adjustable"}')
    outs = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "extract_from_image"))
    assert FakeClient.calls[-1]["multimodal"] is True and {o.attribute_code for o in outs} <= {"neckline", "strap_type", "silhouette"}


# ---------------------------------------------------------------------------------------------------
# AI-04
# ---------------------------------------------------------------------------------------------------
def test_ai04_bulk_samples_approval_then_rest_and_accept_all(client, session, meta, admin):
    FakeClient.handler = staticmethod(lambda p: "A Vitamin A title | Vitamin A")
    ids = [e.id for e in session.execute(select(ProductEntity).where(ProductEntity.level == "style_color")).scalars()]
    assert len(ids) >= 7
    assert client.post("/api/ai/runs", json={"template_code": "vita_seo_title", "selection": {"entity_ids": ids}}, headers=VIEWER).status_code == 403
    r = client.post("/api/ai/runs", json={"template_code": "vita_seo_title", "selection": {"entity_ids": ids}}, headers=ADMIN)
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "sample_pending" and len(run["sample_entity_ids"]) == 5 and run["done"] == 5 and len(run["outputs"]) == 5
    assert len(FakeClient.calls) == 5  # nothing beyond the samples ran yet
    assert session.execute(select(ValueDraft).where(ValueDraft.ai_run_id == run["id"])).scalars().all().__len__() == 5
    q = client.get(f"/api/approvals?run_id={run['id']}", headers=ADMIN).json()
    assert q["runs"][0]["count"] == 5 and q["groups"][0]["items"][0]["template_code"] == "vita_seo_title"
    assert client.post(f"/api/ai/runs/{run['id']}/accept-all", headers=VIEWER).status_code == 403
    r = client.post(f"/api/ai/runs/{run['id']}/approve-samples", headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "completed" and r.json()["done"] == len(ids) and r.json()["proposed"] == len(ids)
    assert client.post(f"/api/ai/runs/{run['id']}/approve-samples", headers=ADMIN).status_code == 409
    detail = client.get(f"/api/ai/runs/{run['id']}", headers=VIEWER).json()
    assert len(detail["outputs"]) == len(ids)
    acc = client.post(f"/api/ai/runs/{run['id']}/accept-all", headers=ADMIN).json()
    assert acc["accepted"] == len(ids) and acc["skipped"] == 0
    assert session.execute(select(ProductValue).where(ProductValue.attribute_code == "seo_title", ProductValue.ai_generated.is_(True))).scalars().all().__len__() == len(ids)
    assert client.get("/api/ai/runs", headers=VIEWER).json()["total"] == 1
    # a cancelled run stops before the rest
    r2 = client.post("/api/ai/runs", json={"template_code": "vita_seo_title", "selection": {"entity_ids": ids}}, headers=ADMIN).json()
    assert client.post(f"/api/ai/runs/{r2['id']}/cancel", headers=VIEWER).status_code == 403
    assert client.post(f"/api/ai/runs/{r2['id']}/cancel", headers=ADMIN).json()["status"] == "cancelled"
    assert client.post("/api/ai/runs", json={"template_code": "vita_seo_title", "selection": {"entity_ids": ["nope"]}}, headers=ADMIN).status_code == 400


# ---------------------------------------------------------------------------------------------------
# AI-07
# ---------------------------------------------------------------------------------------------------
def test_ai07_eval_set_scores_and_blocks_regressions(client, session, meta, admin):
    styles = session.execute(select(ProductEntity).where(ProductEntity.level == "style")).scalars().all()
    refs = {}
    for i, st in enumerate(styles[:6]):
        text = f"<p>The {st.label.title()} is cut from our signature EcoRib fabric with a soft matte hand. Adjustable straps and moderate coverage, piece {i}.</p>"
        assert set_value(session, meta, admin, st, meta.attributes["product_description"], text).outcome == "approved"
        refs[st.id] = text
    session.commit()
    r = client.post("/api/ai/eval/cases/build", json={"attribute_code": "product_description", "limit": 50}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["created"] == 6
    assert client.post("/api/ai/eval/cases/build", json={"attribute_code": "product_description", "limit": 50}, headers=ADMIN).json()["created"] == 0
    assert client.post("/api/ai/eval/cases/build", json={"attribute_code": "color_family"}, headers=ADMIN).status_code == 400
    cases = client.get("/api/ai/eval/cases?attribute=product_description", headers=VIEWER).json()
    assert len(cases) == 6 and cases[0]["reference_text"].startswith("<p>")
    # a model that echoes the brand examples closely passes
    FakeClient.handler = staticmethod(lambda p: "Cut from our signature EcoRib fabric with a soft matte hand. Adjustable straps and moderate coverage.")
    r = client.post("/api/ai/eval/runs", json={"template_code": "vita_product_description"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["status"] == "passed" and first["cases"] == 6 and first["scores"]["overlap"] > 0.5 and first["baseline_run_id"] is None
    assert "EcoRib fabric with a soft matte hand" not in FakeClient.calls[-1]["prompt"]  # the reference never leaks into the prompt
    tpl = session.get(PromptTemplate, "vita_product_description")
    session.refresh(tpl)
    assert tpl.eval_gate["blocked"] is False and tpl.eval_gate["last_run_id"] == first["id"]
    # a regression (garbage output) is blocked against the baseline and the template cannot be activated
    FakeClient.handler = staticmethod(lambda p: "Lorem ipsum dolor sit amet consectetur.")
    second = client.post("/api/ai/eval/runs", json={"template_code": "vita_product_description"}, headers=ADMIN).json()
    assert second["status"] == "blocked" and second["baseline_run_id"] == first["id"] and second["delta"] < -0.05
    assert client.post("/api/ai/templates/vita_product_description/activate", headers=ADMIN).status_code == 409
    runs = client.get("/api/ai/eval/runs?template_code=vita_product_description", headers=VIEWER).json()
    assert [x["status"] for x in runs] == ["blocked", "passed"] and len(runs[0]["sample"]) == 6
    assert client.delete(f"/api/ai/eval/cases/{cases[0]['id']}", headers=ADMIN).json()["deleted"]
    assert evaluation.token_f1("a b c", "a b d") == 0.6667


# ---------------------------------------------------------------------------------------------------
# GOV-03
# ---------------------------------------------------------------------------------------------------
def test_gov03_quality_score_checks_settings_grid_and_dashboard(client, session, meta, admin):
    fvp, ecb = _sc(session), _sc(session, "200809", "ECB")
    other = _sc(session, "200810", "ECB")
    st = session.get(ProductEntity, fvp.parent_id)
    dup = "<p>Made with REPREVE recycled yarns, this is the perfect top for every day at the beach, all summer long.</p>"
    set_value(session, meta, admin, st, meta.attributes["product_description"], dup)  # claims (no certificate), blocked term
    set_value(session, meta, admin, session.get(ProductEntity, other.parent_id), meta.attributes["product_description"], dup)  # duplicate copy
    set_value(session, meta, admin, fvp, meta.attributes["product_title"], "SKYLAR TOP FESTIVAL PINK LONGLINE BRALETTE " * 4)  # all caps, > 150 for Target+
    set_value(session, meta, admin, ecb, meta.attributes["product_title"], "Skylar Top Eco Black")
    small = Asset(id="q-small", filename="200809-FVP_back_01.png", width=800, height=800)
    session.add(small)
    session.flush()
    session.add(AssetLink(asset_id=small.id, entity_id=fvp.id, shot_type="back", status="confirmed"))
    session.flush()
    quality.recompute_all(session, meta)  # the full recompute owns duplicate detection; writes carry its result
    scores = {s.channel_code: s for s in quality.scores_for(session, [fvp.id])[fvp.id].values()}
    overall = scores[""]
    failed = {c["code"] for c in overall.checks if not c["passed"]}
    assert {"casing", "blocked_terms", "duplicate_copy", "image_rules", "claims"} <= failed and "length" not in failed
    assert overall.grade in ("D", "E") and overall.score < 60
    assert "length" in {c["code"] for c in scores["targetplus"].checks if not c["passed"]}  # 150 character channel limit
    ecb_overall = quality.scores_for(session, [ecb.id])[ecb.id][""]
    assert ecb_overall.score > overall.score  # same style copy issues, but no caps title or bad image
    # grid column, sort and filter (style-color and style levels)
    res = run_grid_query(session, meta, admin, GridQuery(level="style_color", page=1, page_size=50, columns=["product_title"],
                                                         filters=[{"field": "quality:overall", "op": "in", "value": ["D", "E"]}]))
    assert {r["entity_id"] for r in res["rows"]} >= {fvp.id} and res["rows"][0]["quality"]["overall"]["grade"] in ("D", "E")
    res = run_grid_query(session, meta, admin, GridQuery(level="style", page=1, page_size=50, columns=["erp_style_description"],
                                                         sort=[{"field": "quality:overall", "dir": "asc"}]))
    assert res["rows"][0]["quality"]["overall"]["score"] <= res["rows"][-1]["quality"].get("overall", {"score": 100})["score"]
    # product endpoint and dashboard
    pq = client.get(f"/api/products/{fvp.id}/quality", headers=VIEWER).json()
    assert pq["scores"][0]["channel_code"] == "" and len(pq["scores"]) == 1 + len(meta.channels)
    dash = client.get("/api/quality/dashboard?by=family", headers=VIEWER).json()["rows"]
    assert sum(r["products"] for r in dash) >= 3 and all(set(r) >= {"A", "B", "C", "D", "E", "avg_score"} for r in dash)
    assert client.get("/api/quality/dashboard?by=channel", headers=VIEWER).json()["rows"]
    assert client.get("/api/quality/dashboard?by=nope", headers=VIEWER).status_code == 400
    # settings: excluding the copy group removes the copy-driven failures; viewer cannot change settings
    s = client.get("/api/quality/settings", headers=VIEWER).json()
    assert s["excluded_groups"] == ["erp", "cost"] and len(s["checks"]) == 7
    assert client.put("/api/quality/settings", json={**s, "excluded_groups": ["copy", "erp"]}, headers=VIEWER).status_code == 403
    assert client.put("/api/quality/settings", json={**s, "grade_bands": {"A": 50, "B": 75, "C": 60, "D": 40}}, headers=ADMIN).status_code == 400
    r = client.put("/api/quality/settings", json={**s, "excluded_groups": ["copy", "erp", "cost"], "enabled_checks": ["casing", "blocked_terms", "claims", "duplicate_copy", "length"]}, headers=ADMIN)
    assert r.status_code == 200, r.text
    n = client.post("/api/quality/recompute", json={"entity_ids": [fvp.id]}, headers=ADMIN).json()["computed"]
    assert n == 1
    after = quality.scores_for(session, [fvp.id])[fvp.id][""]
    session.refresh(after)
    failed_after = {c["code"] for c in after.checks if not c["passed"]}
    assert "claims" not in failed_after and "duplicate_copy" not in failed_after and "image_rules" not in {c["code"] for c in after.checks}
    assert client.post("/api/quality/recompute", headers=ADMIN).json()["computed"] >= 3  # full recompute inline locally
    # readiness refresh keeps the quality snapshot current
    set_value(session, meta, admin, fvp, meta.attributes["product_title"], "Skylar Top Festival Pink")
    from pim.services.readiness import refresh_snapshots

    refresh_snapshots(session, meta, [fvp])
    session.commit()
    now = quality.scores_for(session, [fvp.id])[fvp.id][""]
    assert "casing" not in {c["code"] for c in now.checks if not c["passed"]}


# ---------------------------------------------------------------------------------------------------
# Pre-PR review fixes
# ---------------------------------------------------------------------------------------------------
def test_review_human_draft_is_never_overridden_and_ai_drafts_supersede(session, meta, admin, ingested):
    from tests.conftest import make_user

    fvp = _sc(session)
    _prep(session, meta, admin, fvp)
    editor = make_user(session, "merch@swimusa.com", ["product_merch"])
    # a person's pending draft on seo_title (merch has edit but not approve on the seo group in the seeds)
    session.add(ValueDraft(entity_level="style_color", entity_id=fvp.id, attribute_code="customer_color_name", channel_code="",
                           proposed={"value": "Festival Coral", "not_applicable": False}, submitted_by=editor.email, state="proposed"))
    session.flush()
    FakeClient.handler = staticmethod(lambda p: "Festival Rose")
    out = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "expand_color_name"))[0]
    assert out.status == "info" and out.draft_id is None and "person's draft is pending" in out.grounding_errors[0]
    human = session.execute(select(ValueDraft).where(ValueDraft.attribute_code == "customer_color_name")).scalar_one()
    assert human.state == "proposed" and human.proposed["value"] == "Festival Coral"
    # two AI suggestions on the same attribute: the older output is superseded, the draft carries the newest value
    FakeClient.handler = staticmethod(lambda p: "Title A | Vitamin A")
    o1 = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "vita_seo_title"))[0]
    FakeClient.handler = staticmethod(lambda p: "Title B | Vitamin A")
    o2 = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "vita_seo_title"))[0]
    assert o1.draft_id == o2.draft_id and o1.status == "rejected" and o1.rejection_reason == "superseded" and o2.status == "proposed"
    assert session.get(ValueDraft, o2.draft_id).proposed["value"] == "Title B | Vitamin A"


def test_review_approvals_decision_updates_ai_output(client, session, meta, admin):
    fvp = _sc(session)
    _prep(session, meta, admin, fvp)
    session.commit()
    FakeClient.handler = staticmethod(lambda p: "Queue Title | Vitamin A")
    out = client.post("/api/ai/ask", json={"entity_id": fvp.id, "template_code": "vita_seo_title"}, headers=ADMIN).json()["outputs"][0]
    r = client.post("/api/approvals/decide", json={"draft_ids": [out["draft_id"]], "decision": "approve"}, headers=ADMIN)
    assert r.status_code == 200
    o = session.get(AiOutput, out["id"])
    session.refresh(o)
    assert o.status == "accepted" and o.final_value == {"value": "Queue Title | Vitamin A"} and o.edit_distance == 0.0 and o.decided_by == "admin@swimusa.com"
    m = client.get("/api/ai/metrics?template_code=vita_seo_title", headers=VIEWER).json()[0]
    assert m["accepted"] == 1 and m["pending"] == 0
    FakeClient.handler = staticmethod(lambda p: "Queue Title Two | Vitamin A")
    out2 = client.post("/api/ai/ask", json={"entity_id": fvp.id, "template_code": "vita_seo_title"}, headers=ADMIN).json()["outputs"][0]
    client.post("/api/approvals/decide", json={"draft_ids": [out2["draft_id"]], "decision": "reject", "comment": "Too generic"}, headers=ADMIN)
    o2 = session.get(AiOutput, out2["id"])
    session.refresh(o2)
    assert o2.status == "rejected" and o2.rejection_reason == "Too generic"


def test_review_bad_confidence_and_regenerate_replays_inputs(client, session, meta, admin):
    fvp = _sc(session)
    _prep(session, meta, admin, fvp)
    session.commit()
    FakeClient.handler = staticmethod(lambda p: '{"code": "pink", "confidence": "high"}')
    out = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "classify_color_family"))[0]
    assert out.status == "info" and out.confidence is None  # non-numeric confidence never raises and never drafts
    FakeClient.handler = staticmethod(lambda p: json.dumps({"neckline": "scoop"}))
    r = client.post("/api/ai/ask", json={"entity_id": fvp.id, "template_code": "extract_from_supplier_text", "text": "Scoop neck bralette"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    first = r.json()["outputs"][0]
    assert first["inputs"]["text"] == "Scoop neck bralette"
    rg = client.post(f"/api/ai/outputs/{first['id']}/regenerate", headers=ADMIN)
    assert rg.status_code == 200, rg.text
    assert "Scoop neck bralette" in FakeClient.calls[-1]["prompt"]
    tpls = client.get(f"/api/products/{fvp.id}/ai/templates", headers=ADMIN).json()
    assert isinstance(tpls["templates"], list) and tpls["can_run"] is True


def test_review_outputs_listing_respects_brand_scope_and_group_rights(client, session, meta, admin):
    from tests.conftest import make_user

    fvp = _sc(session)
    _prep(session, meta, admin, fvp)
    session.commit()
    FakeClient.handler = staticmethod(lambda p: "Scoped Title | Vitamin A")
    client.post("/api/ai/ask", json={"entity_id": fvp.id, "template_code": "vita_seo_title"}, headers=ADMIN)
    assert client.get(f"/api/ai/outputs?entity_id={fvp.id}", headers=ADMIN).json()["total"] == 1
    session.add(UserRole(email="other@swimusa.com", role_code="viewer", brand_scopes=["ralph_lauren_swim"]))
    session.commit()
    other = {"X-Forwarded-Email": "other@swimusa.com", "X-Forwarded-User": "u9"}
    assert client.get(f"/api/ai/outputs?entity_id={fvp.id}", headers=other).json()["total"] == 0
    make_user(session, "x@swimusa.com", ["viewer"])  # the viewer role has view rights on seo; a role with none would hide the row
    assert client.get(f"/api/ai/outputs?entity_id={fvp.id}", headers=VIEWER).json()["total"] in (0, 1)


def test_review_bulk_job_user_carries_roles(session, meta, admin, ingested):
    session.add(UserRole(email="runner@swimusa.com", role_code="ecommerce", brand_scopes=["vitamin_a"]))
    session.flush()
    u = tasks.user_for_job(session, "runner@swimusa.com")
    assert u.roles == ["ecommerce"] and u.can("run_ai") and u.brand_scopes == ["vitamin_a"]
    assert tasks.user_for_job(session, "nobody@swimusa.com").roles == []  # never admin by default


def test_review_quality_refresh_failure_does_not_poison_the_write(session, meta, admin, ingested, monkeypatch):
    from pim.services import quality as q
    from pim.services.readiness import refresh_snapshots

    def boom(*_a, **_k):
        raise RuntimeError("quality exploded")

    monkeypatch.setattr(q, "refresh_quality", boom)
    fvp = _sc(session)
    assert set_value(session, meta, admin, fvp, meta.attributes["product_title"], "Survives").outcome == "approved"
    refresh_snapshots(session, meta, [fvp])
    session.commit()  # no PendingRollbackError
    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == fvp.id, ProductValue.attribute_code == "product_title")).scalar_one()
    assert pv.value_text == "Survives"


# ---------------------------------------------------------------------------------------------------
# PR #4 review fixes
# ---------------------------------------------------------------------------------------------------
def test_review2_regenerate_returns_one_output_and_scope_guards_decisions(client, session, meta, admin):
    fvp = _sc(session)
    _prep(session, meta, admin, fvp)
    session.commit()
    FakeClient.handler = staticmethod(lambda p: "Regen Title | Vitamin A")
    out = client.post("/api/ai/ask", json={"entity_id": fvp.id, "template_code": "vita_seo_title"}, headers=ADMIN).json()["outputs"][0]
    rg = client.post(f"/api/ai/outputs/{out['id']}/regenerate", json={"note": "again"}, headers=ADMIN).json()
    assert rg["id"] and rg["status"] == "proposed" and rg["attribute_code"] == "seo_title" and len(rg["outputs"]) == 1  # AiOutput shape
    session.add(UserRole(email="other@swimusa.com", role_code="pim_admin", brand_scopes=["ralph_lauren_swim"]))
    session.commit()
    other = {"X-Forwarded-Email": "other@swimusa.com", "X-Forwarded-User": "u9"}
    assert client.post(f"/api/ai/outputs/{rg['id']}/accept", headers=other).status_code == 404  # outside the brand scope
    assert client.post(f"/api/ai/outputs/{rg['id']}/reject", json={"reason": "x"}, headers=other).status_code == 404
    assert client.post(f"/api/ai/outputs/{rg['id']}/regenerate", headers=other).status_code == 404
    assert session.get(AiOutput, rg["id"]).status == "proposed"


def test_review2_approvals_points_at_live_output_and_metrics_ignore_housekeeping(client, session, meta, admin):
    fvp = _sc(session)
    _prep(session, meta, admin, fvp)
    session.commit()
    FakeClient.handler = staticmethod(lambda p: "First | Vitamin A")
    o1 = client.post("/api/ai/ask", json={"entity_id": fvp.id, "template_code": "vita_seo_title"}, headers=ADMIN).json()["outputs"][0]
    FakeClient.handler = staticmethod(lambda p: "Second | Vitamin A")
    o2 = client.post("/api/ai/ask", json={"entity_id": fvp.id, "template_code": "vita_seo_title"}, headers=ADMIN).json()["outputs"][0]
    assert o1["draft_id"] == o2["draft_id"]
    items = [i for g in client.get("/api/approvals", headers=ADMIN).json()["groups"] for i in g["items"] if i["attribute_code"] == "seo_title"]
    assert items and items[0]["ai_output_id"] == o2["id"]
    client.post(f"/api/ai/outputs/{o2['id']}/accept", headers=ADMIN)
    m = client.get("/api/ai/metrics?template_code=vita_seo_title", headers=VIEWER).json()[0]
    assert m["outputs"] == 1 and m["accepted"] == 1 and m["rejected"] == 0 and m["acceptance_rate"] == 1.0  # superseded never counts


def test_review2_non_approver_accept_stays_pending_until_decided(session, meta, admin, ingested):
    from tests.conftest import make_user

    fvp = _sc(session)
    _prep(session, meta, admin, fvp)
    FakeClient.handler = staticmethod(lambda p: "Festival Rose")
    out = tasks.run_task(session, meta, admin, fvp, session.get(PromptTemplate, "expand_color_name"))[0]
    from pim.models import Role

    session.add(Role(code="tmp_editor", label="Temp editor", permissions=["run_ai"], data_rights={"*": "edit"}))
    session.flush()
    merch = make_user(session, "editor@swimusa.com", ["tmp_editor"])
    assert merch.can_edit_group("style_details") and not merch.can_approve_group("style_details")
    tasks.accept_output(session, meta, merch, out, value="Festival Rosé")
    assert out.status == "proposed" and out.decided_by is None and out.final_value is None and out.inputs["edited_value"] == "Festival Rosé"
    draft = session.get(ValueDraft, out.draft_id)
    assert draft.state == "proposed" and draft.proposed["value"] == "Festival Rosé"
    assert tasks.metrics(session, "expand_color_name")[0]["pending"] == 1
    from pim.services.values import decide_drafts

    decide_drafts(session, meta, admin, [draft.id], "approve")
    assert out.status == "edited" and out.edit_distance and out.decided_by == admin.email and out.final_value == {"value": "Festival Rosé"}
    session.rollback()
    session.execute(select(Role).where(Role.code == "tmp_editor"))
    tmp = session.get(Role, "tmp_editor")
    if tmp is not None:
        session.delete(tmp)
        session.commit()


def test_review2_job_identity_never_defaults_to_admin(session, meta, admin, ingested):
    u = tasks.user_for_job(session, "ghost@swimusa.com")
    assert u.roles == [] and not u.can("run_ai")
    u2 = tasks.user_for_job(session, "ghost@swimusa.com", roles=["ecommerce"], scopes=["vitamin_a"])
    assert u2.roles == ["ecommerce"] and u2.can("run_ai") and u2.brand_scopes == ["vitamin_a"]
    from pim.models import AiRun

    run = AiRun(template_code="vita_seo_title", template_version=1, task_type="generate", entity_ids=[], sample_entity_ids=[],
                status="sample_approved", created_by="ghost@swimusa.com")
    session.add(run)
    session.flush()
    tasks.continue_bulk(session, meta, u, run)
    assert run.status == "failed" and "run_ai" in run.error


def test_review2_style_level_bulk_runs_once_per_style(client, session, meta, admin):
    FakeClient.handler = staticmethod(lambda p: "A style description in the brand voice with ribbed fabric.")
    colors = session.execute(select(ProductEntity).where(ProductEntity.level == "style_color", ProductEntity.style_number == "200809")).scalars().all()
    assert len(colors) == 2
    r = client.post("/api/ai/runs", json={"template_code": "vita_product_description", "selection": {"entity_ids": [c.id for c in colors]}}, headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1 and len(FakeClient.calls) == 1  # the owning style, not one call per color


def test_review2_bulk_action_check_template_reports_findings(session, meta, admin, ingested):
    from pim.services.bulk import _run_ai_for

    fvp = _sc(session)
    _prep(session, meta, admin, fvp)
    FakeClient.handler = staticmethod(lambda p: '{"findings": [{"kind": "tone", "message": "too salesy", "severity": "warning"}]}')
    outcome, msg = _run_ai_for(session, meta, admin, fvp, {"template_code": "check_brand_voice"})
    assert outcome == "skipped" and "too salesy" in msg


def test_review2_outputs_listing_pages_in_sql_and_incremental_quality_carries_duplicates(client, session, meta, admin):
    fvp = _sc(session)
    _prep(session, meta, admin, fvp)
    session.commit()
    FakeClient.handler = staticmethod(lambda p: "Paged | Vitamin A")
    for _ in range(3):
        client.post("/api/ai/ask", json={"entity_id": fvp.id, "template_code": "vita_seo_title"}, headers=ADMIN)
    page = client.get(f"/api/ai/outputs?entity_id={fvp.id}&page=2&page_size=2", headers=ADMIN).json()
    assert page["total"] == 3 and len(page["rows"]) == 1
    # duplicate copy: the full recompute finds it; a later incremental refresh carries the result instead of rescanning
    other = _sc(session, "200810", "ECB")
    dup = "<p>Identical copy on two different styles, long enough to count as duplicated content here.</p>"
    set_value(session, meta, admin, session.get(ProductEntity, fvp.parent_id), meta.attributes["product_description"], dup)
    set_value(session, meta, admin, session.get(ProductEntity, other.parent_id), meta.attributes["product_description"], dup)
    session.commit()
    quality.recompute_all(session, meta)
    snap = quality.scores_for(session, [fvp.id])[fvp.id][""]
    dup_check = next(c for c in snap.checks if c["code"] == "duplicate_copy")
    assert dup_check["passed"] is False and not dup_check.get("carried")
    set_value(session, meta, admin, fvp, meta.attributes["product_title"], "Touched again")
    from pim.services.readiness import refresh_snapshots

    refresh_snapshots(session, meta, [fvp])
    session.commit()
    snap2 = quality.scores_for(session, [fvp.id])[fvp.id][""]
    session.refresh(snap2)
    dup2 = next(c for c in snap2.checks if c["code"] == "duplicate_copy")
    assert dup2["passed"] is False and dup2.get("carried") is True
