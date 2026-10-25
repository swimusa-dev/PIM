"""Phase 3: EXP-02 schema loaders and diff, EXP-04 payloads and validation, EXP-05 publishes, feedback and health,
EXP-06 delta and schedule, EXP-12 eligibility overrides, IMG-03 tier 3, IMG-05 rules and ordering, IMG-06 write-back,
IMG-07 renditions."""

from __future__ import annotations

import io
import zipfile
from datetime import timedelta

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from tests.conftest import FIXTURES

from pim.adapters.base import NotConfigured
from pim.config import get_settings
from pim.export import publishing
from pim.export.payloads import build_payloads, payload_files
from pim.export.schema_loaders import (
    SchemaLoadError,
    TargetSchema,
    diff_schemas,
    load_mirakl,
    load_retailer_xlsx,
    load_shopify,
    load_walmart_spec,
)
from pim.models import (
    Asset,
    AssetLink,
    Channel,
    EligibilityOverride,
    ImageRendition,
    Notification,
    ProductEntity,
    PublishItem,
    PublishRecord,
    UserRole,
)
from pim.models._common import utcnow
from pim.services import images_phase3 as img
from pim.services.values import set_value

P3 = FIXTURES / "phase3"
CHANNEL_STATE = ("target_schema", "last_schema_diff", "attribute_mapping", "transforms", "image_profile", "schedule", "config", "enabled")


@pytest.fixture(autouse=True)
def _restore_channels(session):
    """Channels are seeded, not truncated; Phase 3 tests mutate them, so put them back afterwards."""
    import copy

    saved = {c.code: {k: copy.deepcopy(getattr(c, k)) for k in CHANNEL_STATE} for c in session.execute(select(Channel)).scalars()}
    yield
    session.rollback()
    for c in session.execute(select(Channel)).scalars():
        for k, v in saved.get(c.code, {}).items():
            setattr(c, k, v)
    session.commit()


def _sc(session, style="200809", color="FVP"):
    return session.execute(select(ProductEntity).where(ProductEntity.level == "style_color", ProductEntity.style_number == style,
                                                       ProductEntity.color_code == color)).scalar_one()


def _template_xlsx(required_hint=True) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Feed"
    ws.append(["Vendor Style", "Product Title*", "Color Family", "Fabric Weight Oz", "Care", "Long Description"])
    ws.append(["", "required, max 60", "Black|Pink|Blue", "number", "", ""])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _configure_nordstrom(session, meta, admin) -> Channel:
    ch = session.get(Channel, "nordstrom")
    ch.config = {**(ch.config or {}), "file_format": "csv", "transport": "download"}  # Phase 3 generic feed path; Phase 5 moved the seed to XLSX
    ch.target_schema = load_retailer_xlsx(_template_xlsx()).as_dict()
    ch.attribute_mapping = {"core.style_number": "Vendor Style", "product_title": "Product Title", "color_family": "Color Family",
                            "product_description": "Long Description", "fabric.fabric_care": "Care"}
    ch.transforms = [{"target": "Product Title", "op": "truncate", "args": {"max_length": 60}},
                     {"target": "Care", "op": "case", "args": {"mode": "upper"}},
                     {"target": "Fabric Weight Oz", "op": "conditional",
                      "args": {"when": {"field": "attr:product_title", "op": "not_empty"}, "then": "7.5"}},
                     {"target": "Fabric Weight Oz", "op": "unit_convert", "args": {"from": "oz", "to": "g", "precision": 1}}]
    ch.enabled = True
    session.flush()
    return ch


def _set_ready(session, meta, admin, sc, title="Skylar Top", color_family=None):
    st = session.get(ProductEntity, sc.parent_id)
    assert set_value(session, meta, admin, st, meta.attributes["product_description"], "<p>Ribbed bralette top.</p>").outcome in ("approved", "unchanged")
    assert set_value(session, meta, admin, sc, meta.attributes["product_title"], title).outcome == "approved"
    if color_family:
        set_value(session, meta, admin, sc, meta.attributes["color_family"], color_family)
    session.flush()


# ---------------------------------------------------------------------------------------------------
# EXP-02
# ---------------------------------------------------------------------------------------------------
def test_exp02_walmart_spec_loader_and_diff():
    v1 = load_walmart_spec((P3 / "walmart_spec_v1.json").read_bytes(), "Swimwear")
    names = v1.by_name()
    assert v1.source == "walmart_spec" and v1.product_type == "Swimwear"
    assert names["productName"].required and names["productName"].max_length == 200 and names["productName"].group == "Swimwear"
    assert names["colorCategory"].type == "array" and "Pink" in names["colorCategory"].enum
    assert names["productIdType"].type == "enum" and names["productIdType"].required
    assert names["price"].type == "number" and names["price"].min == 0
    v2 = load_walmart_spec((P3 / "walmart_spec_v2.json").read_bytes(), "Swimwear")
    d = diff_schemas(v1, v2)
    assert [f["name"] for f in d["added"]] == ["ageGroup"] and d["added"][0]["required"]
    assert [f["name"] for f in d["removed"]] == ["clothingSize"]
    assert d["enum_changed"] == [{"name": "colorCategory", "added": ["Green"], "removed": []}]
    with pytest.raises(SchemaLoadError):
        load_walmart_spec((P3 / "walmart_spec_v1.json").read_bytes(), "Shoes")
    with pytest.raises(SchemaLoadError):
        load_walmart_spec(b"not json")


def test_exp02_mirakl_zip_shopify_and_xlsx_loaders():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("export_PM11.csv", (P3 / "mirakl_PM11.csv").read_bytes())
        zf.writestr("export_VL11.csv", (P3 / "mirakl_VL11.csv").read_bytes())
    m = load_mirakl({"nordstrom.zip": buf.getvalue()})
    names = m.by_name()
    assert names["color_family"].type == "enum" and names["color_family"].enum == ["BLACK", "PINK", "BLUE"] and names["color_family"].required
    assert names["eco_claims"].type == "array" and names["eco_claims"].enum == ["RECYCLED", "OEKO"]
    assert names["product_title"].max_length == 150 and not names["fabric_content"].required
    with pytest.raises(SchemaLoadError):
        load_mirakl({"VL11.csv": (P3 / "mirakl_VL11.csv").read_bytes()})
    s = load_shopify((P3 / "shopify_metafield_definitions.json").read_bytes())
    sn = s.by_name()
    assert sn["Title"].required and sn["SEO Title"].max_length == 70
    assert sn["custom.short_description"].max_length == 300 and sn["custom.coverage"].enum == ["Full", "Moderate", "Cheeky"]
    assert sn["shopify--discovery--product_recommendation.complementary_products"].group == "product_metafield"
    assert s.version == "2026-07"
    x = load_retailer_xlsx(_template_xlsx())
    xn = x.by_name()
    assert xn["Product Title"].required and xn["Color Family"].enum == ["Black", "Pink", "Blue"] and xn["Fabric Weight Oz"].type == "number"
    assert not xn["Vendor Style"].required
    roundtrip = TargetSchema.from_dict(x.as_dict())
    assert roundtrip.by_name()["Color Family"].enum == ["Black", "Pink", "Blue"]


# ---------------------------------------------------------------------------------------------------
# EXP-04 and EXP-12
# ---------------------------------------------------------------------------------------------------
def test_exp04_payload_build_transforms_and_validation(session, meta, admin, ingested):
    ch = _configure_nordstrom(session, meta, admin)
    fvp = _sc(session)
    _set_ready(session, meta, admin, fvp, title="A very long product title that goes past the sixty character limit of the retailer", color_family="green")
    blk = _sc(session, "200809", "ECB")
    _set_ready(session, meta, admin, blk, title="Skylar Top", color_family="black")
    payloads = {p.entity_id: p for p in build_payloads(session, meta, ch, [fvp, blk])}
    p = payloads[fvp.id]
    assert p.data["Vendor Style"] == "200809"
    assert len(p.data["Product Title"]) == 60  # truncate transform
    assert p.data["Fabric Weight Oz"] == 212.6  # conditional then unit_convert oz -> g
    kinds = {(i.kind, i.field) for i in p.issues}
    assert ("enum", "Color Family") in kinds  # purple is not in the retailer list
    assert p.sources["Color Family"] == "color_family"  # issue maps back to our attribute (F10)
    assert not p.valid
    ok = payloads[blk.id]
    assert ok.valid, [i.message for i in ok.issues]
    assert ok.data["Color Family"] == "Black"
    files = {n: c for n, c, _k in payload_files(ch, [p, ok], TargetSchema.from_dict(ch.target_schema))}
    assert set(files) == {"payload.csv", "validation_report.csv"}
    csv_text = files["payload.csv"].decode("utf-8-sig")
    assert "Vendor Style,Product Title,Color Family" in csv_text.splitlines()[0]
    assert csv_text.count("\n") == 2  # header plus the one valid product
    assert "Green" in files["validation_report.csv"].decode("utf-8-sig")


def test_exp04_dry_run_records_items_and_files(session, meta, admin, ingested):
    ch = _configure_nordstrom(session, meta, admin)
    fvp = _sc(session)
    _set_ready(session, meta, admin, fvp, color_family="black")
    rec = publishing.start_run(session, ch, "dry_run", "full", admin.email, {"entity_ids": [fvp.id]})
    publishing.execute_run(session, meta, ch, rec, preview=3)
    session.commit()
    assert rec.status == "completed" and rec.product_count == 1 and rec.valid_count == 1 and rec.invalid_count == 0
    assert {f["name"] for f in rec.files} == {"payload.csv", "validation_report.csv"}
    assert rec.summary["preview"][0]["data"]["Product Title"] == "Skylar Top"
    items = session.execute(select(PublishItem).where(PublishItem.publish_id == rec.id)).scalars().all()
    assert len(items) == 1 and items[0].status == "valid" and items[0].external_id == "200809-FVP"
    assert publishing.storage().read(rec.files[0]["path"]).startswith(b"\xef\xbb\xbfVendor Style")


def test_exp12_ineligible_products_skipped_unless_overridden(session, meta, admin, ingested):
    ch = _configure_nordstrom(session, meta, admin)
    fvp = _sc(session)
    _set_ready(session, meta, admin, fvp, color_family="black")
    fvp.brand_classification = "exclusive_brand"
    session.flush()
    kept, skipped = publishing.eligible_entities(session, meta, ch, [fvp])
    assert kept == [] and skipped[0]["entity_id"] == fvp.id and "own retailer" in skipped[0]["reasons"][0]
    session.add(EligibilityOverride(entity_id=fvp.id, channel_code=ch.code, reason="Buyer approved a one-time exception", approved_by=admin.email))
    session.flush()
    kept, skipped = publishing.eligible_entities(session, meta, ch, [fvp])
    assert kept == [fvp] and skipped == []
    expired = session.execute(select(EligibilityOverride)).scalar_one()
    expired.expires_at = utcnow() - timedelta(days=1)
    session.flush()
    kept, _ = publishing.eligible_entities(session, meta, ch, [fvp])
    assert kept == []


# ---------------------------------------------------------------------------------------------------
# EXP-05
# ---------------------------------------------------------------------------------------------------
def test_exp05_feedback_maps_errors_tags_and_notifies(session, meta, admin, ingested):
    ch = _configure_nordstrom(session, meta, admin)
    session.add(UserRole(email="ecom@swimusa.com", role_code="ecommerce", brand_scopes=[]))
    fvp, blk = _sc(session), _sc(session, "200809", "ECB")
    for sc in (fvp, blk):
        _set_ready(session, meta, admin, sc, color_family="black")
    rec = publishing.start_run(session, ch, "publish", "full", admin.email, {"entity_ids": [fvp.id, blk.id]})
    publishing.execute_run(session, meta, ch, rec, send=True)
    session.commit()
    assert rec.status == "completed" and rec.summary["delivery"]["transport"] == "download"
    rows = publishing.parse_feedback_file("retailer_feedback.csv", (P3 / "retailer_feedback.csv").read_bytes())
    assert len(rows) == 4 and rows[0]["external_id"] == "200809-FVP"
    result = publishing.apply_feedback(session, meta, ch, rec, rows)
    session.commit()
    assert result == {"updated": 2, "accepted": 1, "rejected": 1, "in_review": 0, "unmatched": 1}
    items = {i.external_id: i for i in session.execute(select(PublishItem).where(PublishItem.publish_id == rec.id)).scalars()}
    fvp_item = items["200809-FVP"]
    assert fvp_item.status == "rejected" and items["200809-ECB"].status == "accepted"
    by_kind = {e["kind"]: e for e in fvp_item.errors}
    assert by_kind["internal"]["attribute_code"] == "product_title"  # mapped back through the channel mapping
    assert "Internal server error" in by_kind["external"]["message"] and by_kind["external"]["attribute_code"] is None
    assert rec.status == "partial"
    notes = session.execute(select(Notification).where(Notification.kind == "publish_rejected")).scalars().all()
    assert {n.user_email for n in notes} == {"ecom@swimusa.com", admin.email}
    health = publishing.channel_health(session, ch)
    assert health["accepted"] == 1 and health["rejected"] == 1 and health["health_score"] == 0.5
    assert health["top_errors"][0]["count"] == 1 and {e["kind"] for e in health["top_errors"]} == {"internal", "external"}


def test_exp05_shopify_publish_builds_exp13_package_not_direct_write(session, meta, admin, ingested):
    ch = session.get(Channel, "shopify-vitamina")
    fvp = _sc(session)
    rec = publishing.start_run(session, ch, "publish", "full", admin.email, {"entity_ids": [fvp.id]})
    publishing.execute_run(session, meta, ch, rec, send=True)
    session.commit()
    from pim.models import UpdatePackage

    assert rec.status == "completed" and rec.package_id and session.get(UpdatePackage, rec.package_id) is not None
    assert not get_settings().feature_shopify_direct_write


def test_exp05_api_adapter_send_stays_off_by_default(session, meta, admin, ingested):
    ch = session.get(Channel, "walmart-mp")
    ch.config = {**ch.config, "transport": "api"}
    ch.target_schema = load_walmart_spec((P3 / "walmart_spec_v1.json").read_bytes(), "Swimwear").as_dict()
    fvp = _sc(session)
    rec = publishing.start_run(session, ch, "publish", "full", admin.email, {"entity_ids": [fvp.id]})
    publishing.execute_run(session, meta, ch, rec, send=True)
    assert rec.status == "completed" and rec.invalid_count == 1  # required Walmart fields unmapped
    assert "missing_required" in rec.summary["issues_by_kind"]
    with pytest.raises(NotConfigured):
        publishing.poll_feedback(session, meta, ch, rec)


# ---------------------------------------------------------------------------------------------------
# EXP-06
# ---------------------------------------------------------------------------------------------------
def test_exp06_delta_detection_and_schedule(session, meta, admin, ingested):
    ch = _configure_nordstrom(session, meta, admin)
    fvp, blk = _sc(session), _sc(session, "200809", "ECB")
    for sc in (fvp, blk):
        _set_ready(session, meta, admin, sc, color_family="black")
    first = publishing.delta_candidates(session, meta, ch, [fvp, blk])
    assert {d["entity_id"] for d in first} == {fvp.id, blk.id} and first[0]["reasons"] == ["Never published to this channel"]
    rec = publishing.start_run(session, ch, "publish", "full", admin.email, {"entity_ids": [fvp.id, blk.id]})
    publishing.execute_run(session, meta, ch, rec, send=True)
    for i in session.execute(select(PublishItem).where(PublishItem.publish_id == rec.id)).scalars():
        i.status = "accepted"
    rec.finished_at = utcnow()  # after every write above
    session.commit()
    assert publishing.delta_candidates(session, meta, ch, [fvp, blk]) == []
    set_value(session, meta, admin, fvp, meta.attributes["product_title"], "Skylar Top Ribbed")
    session.commit()
    delta = publishing.delta_candidates(session, meta, ch, [fvp, blk])
    assert [d["entity_id"] for d in delta] == [fvp.id] and "product_title changed" in delta[0]["reasons"]
    # schedule: every N hours, due only once the interval passed
    sched = {**publishing.DEFAULT_SCHEDULE, "enabled": True, "every_hours": 4, "last_run_at": (utcnow() - timedelta(hours=1)).isoformat()}
    assert not publishing.schedule_due(sched)
    sched["last_run_at"] = (utcnow() - timedelta(hours=5)).isoformat()
    assert publishing.schedule_due(sched)
    assert not publishing.schedule_due({**sched, "enabled": False})
    ch.schedule = {"enabled": True, "mode": "delta", "every_hours": 1}
    result = publishing.run_scheduled(session, meta, ch, force=True)
    assert result["status"] == "started"
    run = session.get(PublishRecord, result["publish_id"])
    sent = {i.entity_id for i in session.execute(select(PublishItem).where(PublishItem.publish_id == run.id)).scalars()}
    assert run.kind == "scheduled" and run.mode == "delta" and fvp.id in sent and blk.id not in sent  # unchanged ECB stays out
    assert ch.schedule["last_result"].startswith("completed")
    # a run in progress is skipped, never queued
    session.add(PublishRecord(channel_code=ch.code, kind="publish", status="running", created_by="x"))
    session.flush()
    assert publishing.run_scheduled(session, meta, ch, force=True)["status"] == "skipped"


# ---------------------------------------------------------------------------------------------------
# IMG-05, IMG-06, IMG-07, IMG-03
# ---------------------------------------------------------------------------------------------------
def _asset(session, aid, filename="200809-FVP_front_01.jpg", w=2400, h=3000, ai=False):
    a = Asset(id=aid, filename=filename, width=w, height=h, ai_generated_image=ai, thumbnail_url=f"https://cdn.example/{aid}.jpg", version_id="v1")
    session.add(a)
    session.flush()
    return a


def test_img05_technical_rules_ordering_and_queue(session, meta, admin, ingested):
    fvp = _sc(session)
    good = _asset(session, "good")
    small = _asset(session, "small", "200809-FVP_back_01.png", 1200, 1500)
    square = _asset(session, "square", "200809-FVP_side_01.jpg", 2000, 2000)
    assert img.check_image_rules(good, {"min_width": 2000, "min_height": 2000, "aspect_ratio": "4:5", "formats": ["jpg"]}) == []
    fails = img.check_image_rules(small, {"min_width": 2000, "min_height": 2000, "aspect_ratio": "4:5", "formats": ["jpg"]})
    assert any("width 1200" in f for f in fails) and any("format png" in f for f in fails)
    assert any("aspect ratio" in f for f in img.check_image_rules(square, {"aspect_ratio": "4:5"}))
    assert img.check_image_rules(good, {"reject_ai_generated": True}) == []
    good.ai_generated_image = True
    assert img.check_image_rules(good, {"reject_ai_generated": True}) == ["AI generated images are not allowed by this channel"]
    good.ai_generated_image = False
    l1 = AssetLink(asset_id=good.id, entity_id=fvp.id, shot_type="front", status="confirmed", sort_order=0)
    l2 = AssetLink(asset_id=small.id, entity_id=fvp.id, shot_type="back", status="confirmed", sort_order=1)
    l3 = AssetLink(asset_id=square.id, entity_id=fvp.id, shot_type="side", status="confirmed", sort_order=2)
    session.add_all([l1, l2, l3])
    session.flush()
    ordered = img.reorder_links(session, fvp.id, [l3.id, l1.id])
    assert [lk.id for lk in ordered] == [l3.id, l1.id, l2.id] and ordered[0].sort_order == 0
    with pytest.raises(ValueError):
        img.reorder_links(session, fvp.id, ["nope"])
    rf = img.rule_failures_for(meta, small, fvp.family_code)
    assert "shopify-vitamina" in rf and "walmart-mp" in rf
    queue = img.failing_rules_queue(session, meta, "shopify-vitamina", 1, 50)
    assert queue["total"] == 2 and {r["asset_id"] for r in queue["rows"]} == {"small", "square"}
    assert img.failing_rules_queue(session, meta, "targetplus", 1, 50)["total"] == 2  # only the 1:1 square passes there


class FakeAir:
    def __init__(self, fail=False):
        self.fields: dict[str, dict] = {}
        self.fail = fail
        self.cdn_calls: list[tuple] = []

    def set_custom_fields(self, asset_id, fields):
        if self.fail:
            raise RuntimeError("boom")
        self.fields.setdefault(asset_id, {}).update(fields)

    def cdn_url(self, asset_id, width=None, height=None, fmt="jpg"):
        self.cdn_calls.append((asset_id, width, height, fmt))
        return f"https://cdn.air.inc/{asset_id}?w={width}&h={height}&f={fmt}"

    def search_assets(self, query, board_id=None, semantic=True, limit=20):
        return [{"id": "sibling", "score": 0.8}]


def test_img06_write_back_on_confirm_is_best_effort(session, meta, admin, ingested):
    fvp = _sc(session)
    a = _asset(session, "wb", ai=True)
    lk = AssetLink(asset_id=a.id, entity_id=fvp.id, shot_type="front", status="confirmed")
    session.add(lk)
    session.flush()
    air = FakeAir()
    assert img.try_write_back(session, lk, air) is True
    assert air.fields["wb"] == {"Style Number": "200809", "Color Code": "FVP", "Shot Type": "front", "AI Generated": "Yes"}
    assert lk.written_back_at is not None
    lk2 = AssetLink(asset_id=a.id, entity_id=fvp.id, shot_type="back", status="confirmed")
    session.add(lk2)
    session.flush()
    assert img.try_write_back(session, lk2, FakeAir(fail=True)) is False and lk2.written_back_at is None

    class NoAir:
        def set_custom_fields(self, *_a, **_k):
            raise NotConfigured("no key")

    assert img.try_write_back(session, lk2, NoAir()) is False


def test_img07_renditions_cdn_then_pillow_fallback(session, meta, admin, ingested, tmp_path):
    fvp = _sc(session)
    ch = session.get(Channel, "nordstrom")
    ch.image_profile = {"shot_types": ["front"], "width": 1200, "height": 1500, "format": "jpg", "pad_to_ratio": "4:5", "background": "white"}
    a = _asset(session, "r1")
    session.add(AssetLink(asset_id=a.id, entity_id=fvp.id, shot_type="front", status="confirmed"))
    b = _asset(session, "r2", "200809-FVP_back_01.jpg")
    session.add(AssetLink(asset_id=b.id, entity_id=fvp.id, shot_type="back", status="confirmed"))
    session.flush()
    air = FakeAir()
    stats = img.refresh_renditions(session, ch, [fvp.id], air)
    assert stats == {"created": 1, "queued": 0} and air.cdn_calls == [("r1", 1200, 1500, "jpg")]
    r = session.execute(select(ImageRendition)).scalar_one()
    assert r.source == "air_cdn" and r.url.startswith("https://cdn.air.inc/r1") and r.channel_code == "nordstrom"
    assert img.refresh_renditions(session, ch, [fvp.id], air) == {"created": 1, "queued": 0} and len(air.cdn_calls) == 1  # cached
    a.version_id = "v2"  # a new Air version gets a new rendition
    session.flush()
    img.refresh_renditions(session, ch, [fvp.id], air)
    assert len(air.cdn_calls) == 2

    class NoAir:
        def cdn_url(self, *_a, **_k):
            raise NotConfigured("no key")

    ch2 = session.get(Channel, "targetplus")
    ch2.image_profile = {"shot_types": ["front"], "width": 600, "height": 600, "format": "png", "pad_to_ratio": "1:1", "background": "white"}
    assert img.refresh_renditions(session, ch2, [fvp.id], NoAir()) == {"created": 0, "queued": 1}
    from PIL import Image

    src = io.BytesIO()
    Image.new("RGB", (800, 1000), (200, 30, 90)).save(src, "PNG")
    from pim.services.storage import Storage

    done = img.render_pending_with_pillow(session, lambda asset: src.getvalue(), Storage(str(tmp_path)))
    assert done == 1
    pend = session.execute(select(ImageRendition).where(ImageRendition.channel_code == "targetplus")).scalar_one()
    assert pend.source == "job" and pend.width == 600 and pend.height == 600 and pend.url.endswith(".png")
    out = Image.open(pend.url)
    assert out.size == (600, 600) and out.getpixel((5, 5)) == (255, 255, 255)  # padded to square on white


def test_img03_tier3_behind_flag_and_never_auto_confirms(session, meta, admin, ingested, monkeypatch):
    fvp = _sc(session)
    sib = _asset(session, "sibling", "200809-FVP_front_01.jpg")
    session.add(AssetLink(asset_id=sib.id, entity_id=fvp.id, shot_type="front", status="confirmed"))
    mystery = _asset(session, "mystery", "DSC_0001.jpg")
    mystery.parse_status = "unparsed"
    session.flush()
    with pytest.raises(img.FeatureOff):
        img.ai_candidates(session, meta, mystery, air_client=FakeAir())
    monkeypatch.setattr(get_settings(), "feature_image_ai_match", True)

    class FakeAI:
        def describe_image(self, url, *, shot_types, user_email="system"):
            return {"style_number": "200809", "color_code": "ECB", "shot_type": "back", "confidence": 0.75}

    links = img.ai_candidates(session, meta, mystery, air_client=FakeAir(), ai_service=FakeAI())
    assert len(links) == 2 and all(lk.status == "proposed" and lk.tier == 3 for lk in links)
    blk = _sc(session, "200809", "ECB")
    assert links[0].entity_id == blk.id and links[0].shot_type == "back" and links[0].confidence == 0.75
    assert links[1].entity_id == fvp.id and "semantic" in links[1].evidence["why"]
    assert mystery.parse_status == "parsed"
    again = img.ai_candidates(session, meta, mystery, air_client=FakeAir(), ai_service=FakeAI())
    assert {lk.id for lk in again} == {lk.id for lk in links}  # idempotent


# ---------------------------------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------------------------------
ADMIN = {"X-Forwarded-Email": "admin@swimusa.com", "X-Forwarded-User": "u1"}
VIEWER = {"X-Forwarded-Email": "viewer@swimusa.com", "X-Forwarded-User": "u2"}


@pytest.fixture
def client(session, ingested):
    from fastapi.testclient import TestClient

    from pim.main import app

    for email, role in (("admin@swimusa.com", "pim_admin"), ("viewer@swimusa.com", "viewer")):
        if not session.execute(select(UserRole).where(UserRole.email == email, UserRole.role_code == role)).first():
            session.add(UserRole(email=email, role_code=role, brand_scopes=[]))
    session.commit()
    return TestClient(app)


def test_phase3_api_schema_mapping_dry_run_and_rbac(client, session, meta, admin):
    session.get(Channel, "nordstrom").config = {**(session.get(Channel, "nordstrom").config or {}), "file_format": "csv"}
    session.commit()
    r = client.post("/api/channels/nordstrom/schema/refresh", headers=ADMIN, files={"file": ("template.xlsx", _template_xlsx())})
    assert r.status_code == 200, r.text
    assert len(r.json()["diff"]["added"]) == 6 and r.json()["schema"]["source"] == "retailer_xlsx"
    assert client.post("/api/channels/nordstrom/schema/refresh", headers=VIEWER, files={"file": ("t.xlsx", _template_xlsx())}).status_code == 403
    assert client.get("/api/channels/nordstrom/schema", headers=VIEWER).json()["fields"][1]["name"] == "Product Title"
    body = {"attribute_mapping": {"product_title": "Product Title", "core.style_number": "Vendor Style", "color_family": "Nope"},
            "transforms": [{"target": "Product Title", "op": "truncate", "args": {"max_length": 60}}],
            "image_profile": {"shot_types": ["front"], "width": 1000, "height": 1250, "format": "jpg"}}
    assert client.put("/api/channels/nordstrom/mapping", json=body, headers=VIEWER).status_code == 403
    r = client.put("/api/channels/nordstrom/mapping", json=body, headers=ADMIN)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["gaps"]["mapped_fields_missing_in_schema"] == ["Nope"] and "Color Family" not in m["gaps"]["required_fields_unmapped"]
    assert m["image_profile"]["width"] == 1000 and m["transforms"][0]["op"] == "truncate"
    assert client.put("/api/channels/nordstrom/mapping", json={**body, "attribute_mapping": {"ghost_attr": "X"}}, headers=ADMIN).status_code == 400
    fvp = _sc(session)
    _set_ready(session, meta, admin, fvp)
    session.commit()
    assert client.post("/api/channels/nordstrom/dry-run", json={"selection": {}, "mode": "full"}, headers=ADMIN).status_code == 400
    r = client.post("/api/channels/nordstrom/dry-run", json={"selection": {"entity_ids": [fvp.id]}, "mode": "full", "preview": 2}, headers=ADMIN)
    assert r.status_code == 200, r.text
    pub = r.json()
    assert pub["kind"] == "dry_run" and pub["product_count"] == 1 and pub["valid_count"] == 1
    assert client.get("/api/publishes?channel=nordstrom", headers=VIEWER).json()["total"] == 1
    detail = client.get(f"/api/publishes/{pub['id']}", headers=VIEWER).json()
    assert detail["items"][0]["label"] and detail["items"][0]["status"] == "valid"
    f = client.get(f"/api/publishes/{pub['id']}/files/payload.csv", headers=VIEWER)
    assert f.status_code == 200 and b"Skylar Top" in f.content
    assert client.get(f"/api/publishes/{pub['id']}/files/nope.csv", headers=VIEWER).status_code == 404
    assert client.post("/api/channels/nordstrom/publish", json={"selection": {"entity_ids": [fvp.id]}, "mode": "full"}, headers=VIEWER).status_code == 403
    r = client.post(f"/api/publishes/{pub['id']}/feedback", headers=ADMIN,
                    files={"file": ("fb.csv", b"Product ID,Status,Error Message\n200809-FVP,Rejected,Product Title too long\n")})
    assert r.status_code == 200 and r.json()["rejected"] == 1
    h = client.get("/api/channels/nordstrom/health", headers=VIEWER).json()
    assert h["channel_code"] == "nordstrom" and h["publishes"] == 0  # dry runs never count toward health
    s = client.put("/api/channels/nordstrom/schedule", json={"enabled": True, "mode": "delta", "every_hours": 6}, headers=ADMIN)
    assert s.status_code == 200 and s.json()["every_hours"] == 6
    assert client.put("/api/channels/nordstrom/schedule", json={"enabled": True, "mode": "delta"}, headers=ADMIN).status_code == 400
    d = client.get("/api/channels/nordstrom/delta", headers=VIEWER).json()
    assert d["changed"] >= 1 and d["sample"][0]["reasons"]
    rn = client.post("/api/channels/nordstrom/schedule/run-now", headers=ADMIN)
    assert rn.status_code == 200 and rn.json()["status"] == "started"


def test_phase3_api_eligibility_override_and_images(client, session, meta, admin):
    fvp = _sc(session)
    fvp.brand_classification = "exclusive_brand"
    session.commit()
    e = client.get(f"/api/products/{fvp.id}/eligibility", headers=VIEWER).json()["channels"]
    assert e["shopify-vitamina"]["eligible"] is False and e["shopify-vitamina"]["reasons"]
    body = {"channel_code": "shopify-vitamina", "reason": "Marketing exception approved by the brand director"}
    assert client.post(f"/api/products/{fvp.id}/eligibility-override", json=body, headers=VIEWER).status_code == 403
    assert client.post(f"/api/products/{fvp.id}/eligibility-override", json={**body, "reason": "no"}, headers=ADMIN).status_code == 400
    r = client.post(f"/api/products/{fvp.id}/eligibility-override", json={**body, "expires_at": "2027-01-01T00:00:00Z"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    e = client.get(f"/api/products/{fvp.id}/eligibility", headers=VIEWER).json()["channels"]["shopify-vitamina"]
    assert e["eligible"] is True and e["override"]["approved_by"] == "admin@swimusa.com"
    assert client.delete(f"/api/eligibility-overrides/{r.json()['id']}", headers=ADMIN).json()["deleted"]
    # images
    a1 = _asset(session, "api1")
    a2 = _asset(session, "api2", "200809-FVP_back_01.jpg", 1000, 1000)
    l1 = AssetLink(asset_id=a1.id, entity_id=fvp.id, shot_type="front", status="confirmed", sort_order=0)
    l2 = AssetLink(asset_id=a2.id, entity_id=fvp.id, shot_type="back", status="proposed", sort_order=1)
    session.add_all([l1, l2])
    session.commit()
    im = client.get(f"/api/products/{fvp.id}/images", headers=ADMIN).json()
    assert "shopify-vitamina" in im["rules"] and "shopify-vitamina" not in im["links"][0]["rule_failures"]
    assert client.put(f"/api/products/{fvp.id}/images/order", json={"link_ids": [l2.id, l1.id]}, headers=VIEWER).status_code == 403
    o = client.put(f"/api/products/{fvp.id}/images/order", json={"link_ids": [l2.id, l1.id]}, headers=ADMIN)
    assert o.status_code == 200 and [x["id"] for x in o.json()["links"]] == [l2.id, l1.id]
    c = client.post(f"/api/images/links/{l2.id}/confirm", headers=ADMIN).json()
    assert c["status"] == "confirmed" and c["written_back"] is False  # no Air key locally: best effort, never blocks
    assert c["rule_failures"]["shopify-vitamina"]
    assert client.put("/api/images/assets/api2", json={"ai_generated_image": True}, headers=ADMIN).json()["ai_generated_image"] is True
    q = client.get("/api/images/queue?kind=failing_rules&channel=shopify-vitamina", headers=ADMIN).json()
    assert q["total"] == 1 and q["rows"][0]["asset_id"] == "api2"
    assert client.post("/api/images/assets/api2/ai-candidates", headers=ADMIN).status_code == 409
    ch = session.get(Channel, "nordstrom")
    ch.image_profile = {"shot_types": ["front"], "width": 800, "height": 1000, "format": "jpg"}
    session.commit()
    rr = client.get("/api/images/assets/api1/renditions?channel=nordstrom", headers=ADMIN).json()
    assert rr[0]["source"] == "pending"  # no Air key locally, queued for the job
    assert client.post("/api/images/renditions/refresh", json={"channel_code": "nordstrom"}, headers=ADMIN).json()["queued"] == 1


# ---------------------------------------------------------------------------------------------------
# Review fixes (PR #3)
# ---------------------------------------------------------------------------------------------------
def test_review_summary_package_id_is_persisted(session, meta, admin, ingested):
    ch = session.get(Channel, "shopify-vitamina")
    fvp = _sc(session)
    rec = publishing.start_run(session, ch, "publish", "full", admin.email, {"entity_ids": [fvp.id]})
    publishing.execute_run(session, meta, ch, rec, send=True)
    session.commit()
    session.expire_all()
    fresh = session.get(PublishRecord, rec.id)
    assert fresh.summary["package_id"] == fresh.package_id  # survives the reload, not only the in-memory dict


def test_review_walmart_payload_nests_by_path_and_runs_json_schema(session, meta, admin, ingested):
    ch = session.get(Channel, "walmart-mp")
    ch.target_schema = load_walmart_spec((P3 / "walmart_spec_v1.json").read_bytes(), "Swimwear").as_dict()
    ch.config = {**ch.config, "file_format": "json",
                 "raw_schema_path": publishing.storage().write("schemas/walmart-mp/walmart_spec.json", (P3 / "walmart_spec_v1.json").read_bytes())}
    ch.attribute_mapping = {"product_title": "productName", "product_description": "shortDescription", "customer_color_name": "color",
                            "core.style_number": "productId", "core.color_code": "sku", "erp_brand_name": "brand"}
    fvp = _sc(session)
    _set_ready(session, meta, admin, fvp)
    set_value(session, meta, admin, fvp, meta.attributes["customer_color_name"], "Festival Pink")
    session.flush()
    p = build_payloads(session, meta, ch, [fvp])[0]
    kinds = {(i.kind, i.field) for i in p.issues}
    assert ("missing_required", "productIdType") in kinds and ("missing_required", "mainImageUrl") in kinds
    assert any(i.kind == "schema" and i.field == "productId" and "too short" in i.message for i in p.issues)  # minLength from the raw spec
    assert ("missing_required", "price") in kinds  # nested requirement only the raw spec knows
    files = {n: c for n, c, _k in payload_files(ch, [p], TargetSchema.from_dict(ch.target_schema))}
    p.issues = []  # force the file to include the product so the nesting can be checked
    files = {n: c for n, c, _k in payload_files(ch, [p], TargetSchema.from_dict(ch.target_schema))}
    import json as _json

    feed = _json.loads(files["payload.json"])
    item = feed["MPItem"][0]
    assert item["Orderable"]["sku"] == "FVP" and item["Orderable"]["productIdentifiers"]["productId"] == "200809"
    assert item["Visible"]["Swimwear"]["productName"] == "Skylar Top"


def test_review_delta_style_change_flags_every_colorway(session, meta, admin, ingested):
    ch = _configure_nordstrom(session, meta, admin)
    fvp, ecb = _sc(session), _sc(session, "200809", "ECB")
    for sc in (fvp, ecb):
        _set_ready(session, meta, admin, sc, color_family="black")
    rec = publishing.start_run(session, ch, "publish", "full", admin.email, {"entity_ids": [fvp.id, ecb.id]})
    publishing.execute_run(session, meta, ch, rec, send=True)
    for i in session.execute(select(PublishItem).where(PublishItem.publish_id == rec.id)).scalars():
        i.status = "accepted"
    rec.finished_at = utcnow()
    session.commit()
    style = session.get(ProductEntity, fvp.parent_id)
    set_value(session, meta, admin, style, meta.attributes["product_description"], "<p>Updated at the style.</p>")
    session.commit()
    delta = publishing.delta_candidates(session, meta, ch, [fvp, ecb])
    assert {d["entity_id"] for d in delta} == {fvp.id, ecb.id}
    assert all("product_description changed" in d["reasons"] for d in delta)


def test_review_delta_run_never_falls_back_to_the_catalogue(session, meta, admin, ingested):
    ch = _configure_nordstrom(session, meta, admin)
    rec = publishing.start_run(session, ch, "publish", "delta", admin.email, {"entity_ids": ["does-not-exist"]})
    publishing.execute_run(session, meta, ch, rec, send=True)
    assert rec.status == "completed" and rec.product_count == 0


def test_review_feedback_status_wins_over_informational_message(session, meta, admin, ingested):
    ch = _configure_nordstrom(session, meta, admin)
    fvp = _sc(session)
    _set_ready(session, meta, admin, fvp, color_family="black")
    rec = publishing.start_run(session, ch, "publish", "full", admin.email, {"entity_ids": [fvp.id]})
    publishing.execute_run(session, meta, ch, rec, send=True)
    result = publishing.apply_feedback(session, meta, ch, rec, [{"external_id": "200809-FVP", "status": "accepted", "message": "Item published", "field": None}])
    item = session.execute(select(PublishItem).where(PublishItem.publish_id == rec.id)).scalar_one()
    assert result["accepted"] == 1 and result["rejected"] == 0 and item.status == "accepted" and item.errors == []
    assert session.execute(select(Notification).where(Notification.kind == "publish_rejected")).first() is None
    publishing.apply_feedback(session, meta, ch, rec, [{"external_id": "200809-FVP", "status": "in review", "message": "Pending category check", "field": None}])
    assert item.status == "in_review" and item.errors[0]["kind"] == "external"


def test_review_schedule_validation_and_robust_due_check():
    assert publishing.validate_schedule({"enabled": True, "at_hour": 9, "at_minute": 75}) == "at_minute must be 0 to 59"
    assert publishing.validate_schedule({"enabled": True, "every_hours": 0}) == "every_hours must be greater than zero"
    assert publishing.validate_schedule({"enabled": True, "every_hours": -1}) is not None
    assert publishing.validate_schedule({"enabled": True, "at_hour": 24}) == "at_hour must be 0 to 23"
    assert publishing.validate_schedule({"enabled": False}) is None
    # a malformed schedule stored before validation existed is skipped, never raises inside the job
    assert publishing.schedule_due({"enabled": True, "at_hour": 9, "at_minute": 75, "timezone": "America/New_York"}) is False
    assert publishing.schedule_due({"enabled": True, "every_hours": 1, "last_run_at": "not a date"}) is False


def test_review_walmart_loader_reports_missing_visible_section():
    import json as _json

    spec = {"properties": {"MPItem": {"items": {"properties": {"Orderable": {"type": "object", "properties": {"sku": {"type": "string"}}}}}}}}
    with pytest.raises(SchemaLoadError, match="no Visible section"):
        load_walmart_spec(_json.dumps(spec).encode(), "Swimwear")


def test_review_build_payloads_query_count_is_bounded(session, meta, admin, ingested):
    from sqlalchemy import event

    from pim.models import ReferenceEntity

    ch = _configure_nordstrom(session, meta, admin)
    fabric = ReferenceEntity(type_code="fabric", code="ecorib", label="EcoRib")
    session.add(fabric)
    session.flush()
    pseudo = ProductEntity(id=fabric.id, level="ref:fabric", style_number="ecorib", label="EcoRib")
    set_value(session, meta, admin, pseudo, meta.attributes["fabric_care"], "hand_wash_cold_dry_flat")
    ents = []
    for color in ("FVP", "ECB"):
        sc = _sc(session, "200809", color)
        _set_ready(session, meta, admin, sc, color_family="black")
        set_value(session, meta, admin, sc, meta.attributes["fabric"], fabric.id)
        for i, shot in enumerate(["front", "back"]):
            session.add(AssetLink(asset_id=_asset(session, f"q-{color}-{i}", f"200809-{color}_{shot}.jpg").id, entity_id=sc.id, shot_type=shot, status="confirmed"))
        ents.append(sc)
    session.flush()
    count = {"n": 0}

    def _count(*_a, **_k):
        count["n"] += 1

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", _count)
    try:
        payloads = build_payloads(session, meta, ch, ents)
    finally:
        event.remove(bind, "before_cursor_execute", _count)
    assert len(payloads) == 2 and payloads[0].data["Care"].startswith("HAND WASH COLD")
    assert count["n"] <= 6, count["n"]  # entities, values, styles, reference values, links with assets: not per product


def test_review_walmart_raw_spec_lives_on_the_volume(client, session):
    r = client.post("/api/channels/walmart-mp/schema/refresh?product_type=Swimwear", headers=ADMIN,
                    files={"file": ("spec.json", (P3 / "walmart_spec_v1.json").read_bytes())})
    assert r.status_code == 200, r.text
    ch = session.get(Channel, "walmart-mp")
    session.refresh(ch)
    assert "raw_schema" not in ch.config and ch.config["raw_schema_path"].endswith("walmart_spec.json")
    chans = {c["code"]: c for c in client.get("/api/metadata/channels", headers=VIEWER).json()}
    assert "raw_schema" not in chans["walmart-mp"]["config"]
    assert client.post("/api/channels/walmart-mp/schema/refresh?product_type=Shoes", headers=ADMIN,
                       files={"file": ("spec.json", (P3 / "walmart_spec_v1.json").read_bytes())}).status_code == 400
