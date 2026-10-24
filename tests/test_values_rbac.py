"""ARC-03, DM-01 strict ownership, DM-03 validation, DM-08 drafts, GOV-02 history, GOV-06 defaults, P1, P4, RBAC-01."""

from sqlalchemy import select

from pim.models import ProductEntity, ProductValue, ValueDraft, ValueHistory
from pim.services.values import (
    NA_SENTINEL,
    decide_drafts,
    new_change_set,
    resolve_cells,
    restore_from_history,
    set_value,
)


def _sc(session, style="200809", color="FVP"):
    return session.execute(select(ProductEntity).where(ProductEntity.level == "style_color", ProductEntity.style_number == style,
                                                       ProductEntity.color_code == color)).scalar_one()


def _style(session, style="200809"):
    return session.execute(select(ProductEntity).where(ProductEntity.level == "style", ProductEntity.style_number == style)).scalar_one()


def test_p1_erp_values_are_read_only_even_for_admin(session, meta, admin, ingested):
    sc = _sc(session)
    res = set_value(session, meta, admin, sc, meta.attributes["erp_style_content"], "changed")
    assert res.outcome == "rejected" and "ERP" in res.message


def test_dm01_attribute_must_be_edited_at_owning_level(session, meta, admin, ingested):
    sc = _sc(session)
    res = set_value(session, meta, admin, sc, meta.attributes["product_description"], "Style level copy")
    assert res.outcome == "rejected" and "style level" in res.message


def test_dm01_inherited_values_resolve_read_only_on_children(session, meta, admin, ingested):
    st = _style(session)
    assert set_value(session, meta, admin, st, meta.attributes["product_description"], "Meet the Skylar Top.").outcome == "approved"
    session.flush()
    sc = _sc(session)
    cells = resolve_cells(session, meta, admin, [sc], ["product_description"])[sc.id]["product_description"]
    assert cells["value"] == "Meet the Skylar Top."
    assert cells["read_only"] and cells["read_only_reason"] == "inherited" and cells["inherited_from"]["level"] == "style"


def test_dm08_edit_without_approve_creates_draft_then_approval_applies(session, meta, merch, ecommerce, admin, ingested):
    sc = _sc(session)
    # ecommerce has approve on copy; merch has only view on copy -> rejected; on style_details merch has approve
    res = set_value(session, meta, merch, sc, meta.attributes["product_title"], "Skylar Top")
    assert res.outcome == "rejected"
    # viewer-like path: give a user edit-only rights by lowering rights in-memory
    merch.data_rights["style_details"] = "edit"
    res = set_value(session, meta, merch, sc, meta.attributes["customer_color_name"], "Festival Pink")
    assert res.outcome == "draft"
    session.flush()
    draft = session.execute(select(ValueDraft).where(ValueDraft.entity_id == sc.id)).scalar_one()
    assert draft.state == "draft" and draft.proposed["value"] == "Festival Pink"
    # the draft is visible to the grid cell
    cell = resolve_cells(session, meta, merch, [sc], ["customer_color_name"])[sc.id]["customer_color_name"]
    assert cell["draft"]["value"] == "Festival Pink" and cell["value"] is None
    out = decide_drafts(session, meta, admin, [draft.id], "approve")
    assert out[0].outcome == "approved"
    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == sc.id, ProductValue.attribute_code == "customer_color_name")).scalar_one()
    assert pv.value_text == "Festival Pink" and pv.approval_state == "approved"


def test_dm03_validation_from_attribute_definition(session, meta, admin, ingested):
    sc = _sc(session)
    assert set_value(session, meta, admin, sc, meta.attributes["seo_title"], "x" * 71).outcome == "rejected"
    assert set_value(session, meta, admin, sc, meta.attributes["color_family"], "chartreuse").outcome == "rejected"
    assert set_value(session, meta, admin, sc, meta.attributes["color_family"], "pink").outcome == "approved"
    assert set_value(session, meta, admin, sc, meta.attributes["weight"], "heavy").outcome == "rejected"
    assert set_value(session, meta, admin, sc, meta.attributes["weight"], "0.16").outcome == "approved"
    assert set_value(session, meta, admin, sc, meta.attributes["ecomm_launch_date"], "10.30.26").outcome == "approved"


def test_imp10_not_applicable_explicit_value(session, meta, admin, ingested):
    st = _style(session, "200811")
    res = set_value(session, meta, admin, st, meta.attributes["underwire"], NA_SENTINEL)
    assert res.outcome == "approved"
    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == st.id, ProductValue.attribute_code == "underwire")).scalar_one()
    assert pv.not_applicable is True
    # product_name does not allow N/A
    assert set_value(session, meta, admin, st, meta.attributes["product_name"], NA_SENTINEL).outcome == "rejected"


def test_gov02_history_and_restore(session, meta, admin, ingested):
    sc = _sc(session)
    attr = meta.attributes["seo_title"]
    assert set_value(session, meta, admin, sc, attr, "First").outcome == "approved"
    assert set_value(session, meta, admin, sc, attr, "Second").outcome == "approved"
    session.flush()
    hist = session.execute(select(ValueHistory).where(ValueHistory.entity_id == sc.id, ValueHistory.attribute_code == "seo_title")
                           .order_by(ValueHistory.set_at)).scalars().all()
    assert [h.new_value["value"] for h in hist] == ["First", "Second"]
    assert hist[1].old_value["value"] == "First" and hist[1].version == 2
    res = restore_from_history(session, meta, admin, hist[1])
    assert res.outcome == "approved"
    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == sc.id, ProductValue.attribute_code == "seo_title")).scalar_one()
    assert pv.value_text == "First" and pv.version == 3


def test_gov06_defaults_never_overwrite_and_are_tagged(session, meta, admin, ingested):
    st = _style(session)
    attr = meta.attributes["care_instructions"]
    assert set_value(session, meta, None, st, attr, "hand_wash_cold_line_dry", source_type="default", force=True).outcome == "approved"
    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == st.id, ProductValue.attribute_code == attr.code)).scalar_one()
    assert pv.source_type == "default" and pv.confirmed_default is False
    cell = resolve_cells(session, meta, admin, [st], [attr.code])[st.id][attr.code]
    assert cell["is_default"] is True
    assert set_value(session, meta, admin, st, attr, "hand_wash_cold_dry_flat").outcome == "approved"
    assert set_value(session, meta, None, st, attr, "hand_wash_cold_line_dry", source_type="default", force=True).outcome == "unchanged"


def test_p4_ai_cannot_write_directly(session, meta, admin, ingested):
    sc = _sc(session)
    assert set_value(session, meta, admin, sc, meta.attributes["seo_title"], "AI text", source_type="ai").outcome == "rejected"


def test_arc03_channel_override(session, meta, ecommerce, ingested):
    sc = _sc(session)
    assert set_value(session, meta, ecommerce, sc, meta.attributes["seo_title"], "Global title").outcome == "approved"
    assert set_value(session, meta, ecommerce, sc, meta.attributes["seo_title"], "Shopify title", channel_code="shopify-vitamina").outcome == "approved"
    assert set_value(session, meta, ecommerce, sc, meta.attributes["customer_color_name"], "x", channel_code="shopify-vitamina").outcome == "rejected"
    session.flush()
    cells = resolve_cells(session, meta, ecommerce, [sc], ["seo_title"], channel_code="shopify-vitamina")[sc.id]["seo_title"]
    assert cells["value"] == "Shopify title"
    assert resolve_cells(session, meta, ecommerce, [sc], ["seo_title"])[sc.id]["seo_title"]["value"] == "Global title"


def test_rbac_cost_masked_unless_view_cost(session, meta, admin, viewer, ingested):
    from tests.conftest import make_user

    sku = session.execute(select(ProductEntity).where(ProductEntity.sku == "200809-FVP-XS")).scalar_one()
    for u in (admin, viewer):
        cell = resolve_cells(session, meta, u, [sku], ["erp_standard_cost"])[sku.id]["erp_standard_cost"]
        assert cell["value"] is None and cell["read_only_reason"] == "no_rights"
    fin = make_user(session, "fin@swimusa.com", ["finance"])
    cell = resolve_cells(session, meta, fin, [sku], ["erp_standard_cost"])[sku.id]["erp_standard_cost"]
    assert cell["value"] == 9.5


def test_change_set_groups_edits(session, meta, admin, ingested):
    sc = _sc(session)
    cs = new_change_set(session, "edit", admin.email)
    set_value(session, meta, admin, sc, meta.attributes["seo_title"], "A", change_set=cs)
    set_value(session, meta, admin, sc, meta.attributes["seo_description"], "B", change_set=cs)
    session.flush()
    n = session.execute(select(ValueHistory).where(ValueHistory.change_set_id == cs.id)).scalars().all()
    assert len(n) == 2
