"""Product Information Setup File export: new workbook, fill an uploaded setup file, rights, approved values only."""

import io
import json
from datetime import date

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from tests.conftest import make_user

from pim.export.setup_file import (
    REPORT_SHEET,
    build_setup_workbook,
    fill_setup_workbook,
    html_to_text,
    normalize_header,
    parse_style_keys,
    style_colors_for,
)
from pim.models import Asset, AssetLink, ProductEntity, ReferenceEntity, UserRole
from pim.services.values import set_value

# The VA setup file's two header rows, spelled as the team types them (trailing spaces, runs of spaces, a note in
# parentheses), plus one column the export does not know.
GROUPS = ["Style Details"] * 13 + ["Production"] * 6 + ["Design & Tech"] * 8 + ["Merch", "SEO", "Copy", "Copy", "Copy"]
HEADERS = ["Delivery Date", "Ecomm Launch Date", "Category", "Status", "Style #", "Style Name", "Style Image", "Group",
           "Color/Print", "Color Code", "Size Range", "Wholesale $", "Retail $", "Fabrication ", "Content",
           "Care Instructions", "Country of Origin", "HTS Number", "Weight", "Fit Scale #", "Inseam", "Front Rise",
           "Back Rise", "CFL    Length", "HPS Length", "Strap Length", "Fit Details", "Notes", "Key Words",
           "Product Description", "Secondary Description        (Copy on print and/or fabrication)", "Sustainability"]


def _sc(session, style, color):
    return session.execute(select(ProductEntity).where(ProductEntity.level == "style_color", ProductEntity.style_number == style,
                                                       ProductEntity.color_code == color)).scalar_one()


def _enrich(session, meta, admin):
    """Give 200809-FVP the PIM data a setup file asks for."""
    sc = _sc(session, "200809", "FVP")
    st = session.get(ProductEntity, sc.parent_id)
    fabric = ReferenceEntity(type_code="fabric", code="biosculpt", label="BioSculpt")
    session.add(fabric)
    session.flush()
    pseudo = ProductEntity(id=fabric.id, level="ref:fabric", style_number="biosculpt", label="BioSculpt")
    for code, val in {"fabric_name": "BioSculpt", "fabric_story": "The secret is in the source.",
                      "fabric_sustainability": "Plant-based polyamide.", "fabric_care": "hand_wash_cold_dry_flat"}.items():
        assert set_value(session, meta, admin, pseudo, meta.attributes[code], val).outcome == "approved", code
    for code, val in {"product_name": "BioSculpt Bralette Top", "collection": "BioSculpt Solids",
                      "product_description": "<p>Designed to flatter.</p><ul><li>Removable cups</li></ul>",
                      "hts_number": "6112.41.0010", "wholesale_price": 57.5, "fit_scale": 80, "front_rise": "3 1/4",
                      "strap_length": "12.5", "inseam": {"not_applicable": True}}.items():
        assert set_value(session, meta, admin, st, meta.attributes[code], val).outcome == "approved", code
    # Fit details is the legacy combined field: deprecated for edits, still filled by the Shopify import.
    set_value(session, meta, admin, st, meta.attributes["fit_details"], "• Over the shoulder straps\n• Model is wearing a size small",
              source_type="import", force=True)
    for code, val in {"customer_color_name": "Festival Pink", "fabric": fabric.id, "weight": 0.18,
                      "seo_keywords": "bralette, sculpting swim", "ecomm_launch_date": "2026-11-17",
                      "merch_notes": "Key item"}.items():
        assert set_value(session, meta, admin, sc, meta.attributes[code], val).outcome == "approved", code
    a = Asset(id="air-1", filename="200809-FVP_front.jpg", thumbnail_url="https://cdn.example/200809-FVP_front.jpg")
    session.add(a)
    session.flush()
    session.add(AssetLink(asset_id=a.id, entity_id=sc.id, shot_type="front", tier=1, status="confirmed"))
    session.flush()
    return sc


def _setup_file(rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(GROUPS)
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _row(style, color, **cells):
    r = [None] * len(HEADERS)
    r[4], r[9] = style, color
    for k, v in cells.items():
        r[HEADERS.index(k)] = v
    return r


def _sheet_rows(content):
    wb = load_workbook(io.BytesIO(content))
    ws = wb["Sheet1"]
    headers = [c.value for c in ws[2]]
    out = []
    for r in ws.iter_rows(min_row=3, values_only=True):
        out.append(dict(zip(headers, r, strict=False)))
    return wb, out


def test_header_and_key_parsing():
    assert normalize_header("CFL    Length") == "cfl length"
    assert normalize_header("Secondary Description   (Copy on print and/or fabrication)") == "secondary description"
    assert normalize_header("Fabrication ") == "fabrication"
    assert parse_style_keys("6000150\n6000150-MBU, 6131286 klp;") == [("6000150", None), ("6000150", "MBU"), ("6131286", "KLP")]
    assert html_to_text("<p>Designed &amp; made.</p><ul><li>One</li><li>Two</li></ul>") == "Designed & made.\n• One\n• Two"


def test_new_setup_file_from_pim(session, ingested, meta, admin):
    _enrich(session, meta, admin)
    ents, missing = style_colors_for(session, admin, parse_style_keys("200809, 999999"))
    assert {e.color_code for e in ents} == {"FVP", "ECB"} and missing == ["999999"]
    result = build_setup_workbook(session, meta, admin, sorted(ents, key=lambda e: e.color_code))
    wb, rows = _sheet_rows(result.content)
    assert [c.value for c in wb["Sheet1"][2]][:5] == ["Delivery Date", "Ecomm Launch Date", "Category", "Status", "Style #"]
    fvp = next(r for r in rows if r["Color Code"] == "FVP")
    assert fvp["Style #"] == "200809" and fvp["Style Name"] == "BioSculpt Bralette Top"
    assert fvp["Color/Print"] == "Festival Pink" and fvp["Group"] == "BioSculpt Solids"
    assert fvp["Size Range"] == "XS - M"
    assert fvp["Category"] == "SWIMWEAR" and fvp["Status"] == "Repeat Body / New Color"
    assert fvp["Ecomm Launch Date"].date() == date(2026, 11, 17)
    assert fvp["Fabrication"] == "BioSculpt" and fvp["Sustainability"] == "Plant-based polyamide."
    assert fvp["Care Instructions"] == "Hand wash cold. Dry flat."  # falls back to the Fabric's care
    assert fvp["Secondary Description"] == "The secret is in the source."
    assert fvp["Product Description"] == "Designed to flatter.\n• Removable cups"
    assert fvp["Style Image"] == "https://cdn.example/200809-FVP_front.jpg"
    assert fvp["Weight"] == 0.18 and fvp["Key Words"] == "bralette, sculpting swim"
    assert fvp["Retail $"] is None  # the admin role has no view_cost (D-05)
    ecb = next(r for r in rows if r["Color Code"] == "ECB")
    assert ecb["Style Name"] == "BioSculpt Bralette Top"  # style-level values reach every color
    assert ecb["Color/Print"] == "ECO BLACK"  # the ERP color description when there is no customer-facing name
    assert fvp["HTS Number"] == "6112.41.0010" and fvp["Wholesale $"] == 57.5 and fvp["Fit Scale #"] == 80
    assert fvp["Front Rise"] == "3 1/4" and fvp["Strap Length"] == "12.5"
    assert fvp["Inseam"] is None  # marked Not applicable for a top: left blank, never written as text
    # Every setup file column now has a PIM attribute behind it.
    assert result.summary["columns_without_pim_attribute"] == []
    assert not any(r[0].value == "Setup file columns with no PIM attribute yet" for r in wb[REPORT_SHEET].iter_rows())


def test_setup_file_attributes_validate(session, ingested, meta, admin):
    st = session.get(ProductEntity, _sc(session, "200809", "FVP").parent_id)
    ok = {"hts_number": "6204.62.8018", "front_rise": "3.25", "back_rise": "1/2", "wholesale_price": "76"}
    for code, val in ok.items():
        assert set_value(session, meta, admin, st, meta.attributes[code], val).outcome == "approved", code
    bad = {"hts_number": "6112-41-0010", "front_rise": "3 inches", "fit_scale": "-1", "wholesale_price": "-5"}
    for code, val in bad.items():
        assert set_value(session, meta, admin, st, meta.attributes[code], val).outcome == "rejected", code


def test_cost_columns_follow_cost_rights(session, ingested, meta):
    lead = make_user(session, "lead@swimusa.com", ["merch_lead"])
    ents, _ = style_colors_for(session, lead, [("200809", "FVP")])
    skus = session.execute(select(ProductEntity).where(ProductEntity.parent_id == ents[0].id)).scalars().all()
    for sku in skus:  # ERP-owned, so written the way the ingest writes it
        set_value(session, meta, None, sku, meta.attributes["erp_retail_msrp"], 125, source_type="erp", force=True)
    _, rows = _sheet_rows(build_setup_workbook(session, meta, lead, ents).content)
    assert rows[0]["Retail $"] == 125


def test_only_approved_values_are_exported(session, ingested, meta, admin, merch):
    sc = _sc(session, "200809", "FVP")
    st = session.get(ProductEntity, sc.parent_id)
    # A viewer-level edit lands as a draft; a draft must never reach the file.
    viewer = make_user(session, "v@swimusa.com", ["viewer"])
    assert set_value(session, meta, viewer, st, meta.attributes["product_name"], "Draft name").outcome != "approved"
    set_value(session, meta, admin, sc, meta.attributes["merch_notes"], "Unconfirmed default", source_type="default", force=True)
    _, rows = _sheet_rows(build_setup_workbook(session, meta, admin, [sc]).content)
    assert rows[0]["Style Name"] != "Draft name"
    assert rows[0]["Notes"] is None


def test_fill_uploaded_setup_file(session, ingested, meta, admin):
    _enrich(session, meta, admin)
    content = _setup_file([
        _row(200809, "FVP", **{"Style Name": "Old name", "HTS Number": "6112.41.0010", "Style Image": "#VALUE!",
                                "Wholesale $": 57.5, "Fit Scale #": 80, "HPS Length": "24"}),
        _row("200809", "ecb"),                  # lower-case color code still matches
        _row(6000150.0, "MBU", **{"Style Name": "BioSculpt Bralette Top"}),  # not in the PIM
        _row(None, "KLP"),                       # no style number
    ])
    result = fill_setup_workbook(session, meta, admin, content, "VA_Resort_2027.xlsx")
    assert result.file_name == "VA_Resort_2027_PIM.xlsx"
    s = result.summary
    assert s["matched"] == 2 and s["not_in_pim"] == ["6000150-MBU"] and s["no_key"] == [6]
    wb, rows = _sheet_rows(result.content)
    fvp = rows[0]
    assert fvp["Style Name"] == "BioSculpt Bralette Top"  # PIM wins by default
    assert fvp["HTS Number"] == "6112.41.0010" and fvp["Wholesale $"] == 57.5 and fvp["Fit Scale #"] == 80
    assert fvp["HPS Length"] == "24"
    assert fvp["Style Image"] == "https://cdn.example/200809-FVP_front.jpg"
    assert fvp["Fabrication "] == "BioSculpt"  # original header spelling is left alone
    assert rows[1]["Style Name"] == "BioSculpt Bralette Top"
    assert rows[2]["Style Name"] == "BioSculpt Bralette Top" and rows[2]["Product Description"] is None  # untouched
    fvp_rep = next(r for r in result.rows if r.row == 3)
    assert "Style Name: Old name -> BioSculpt Bralette Top" in fvp_rep.changed
    assert "HPS Length" in fvp_rep.kept and "Inseam" in fvp_rep.blank  # no PIM value: the file's value stays
    assert not any(c.startswith("HTS Number") for c in fvp_rep.changed)  # same value in both: not a change
    report = [[c for c in r] for r in wb[REPORT_SHEET].iter_rows(values_only=True)]
    assert any(r[0] == "Rows not found in the PIM" and r[1] == "6000150-MBU" for r in report)


def test_fill_can_keep_file_values(session, ingested, meta, admin):
    _enrich(session, meta, admin)
    content = _setup_file([_row("200809", "FVP", **{"Style Name": "Team name"})])
    result = fill_setup_workbook(session, meta, admin, content, keep_file_values=True)
    _, rows = _sheet_rows(result.content)
    assert rows[0]["Style Name"] == "Team name" and rows[0]["Color/Print"] == "Festival Pink"
    assert result.summary["cells_changed"] == 0


def test_setup_file_api(session, ingested, meta, admin):
    _enrich(session, meta, admin)
    if not session.execute(select(UserRole).where(UserRole.email == "admin@swimusa.com", UserRole.role_code == "pim_admin")).first():
        session.add(UserRole(email="admin@swimusa.com", role_code="pim_admin", brand_scopes=[]))
    session.commit()
    client = TestClient(app_instance())
    hdr = {"X-Forwarded-Email": "admin@swimusa.com", "X-Forwarded-User": "u1"}
    r = client.post("/api/setup-file", json={"styles": "200809-FVP\n999999"}, headers=hdr)
    assert r.status_code == 200, r.text
    summary = json.loads(r.headers["X-Setup-File-Summary"])
    assert summary["matched"] == 1 and summary["styles_not_found"] == ["999999"]
    assert load_workbook(io.BytesIO(r.content))["Sheet1"]["F3"].value == "BioSculpt Bralette Top"
    up = client.post("/api/setup-file/fill", headers=hdr,
                     files={"file": ("VA Resort.xlsx", _setup_file([_row("200809", "FVP")]), "application/octet-stream")})
    assert up.status_code == 200, up.text
    assert "VA_Resort_PIM.xlsx" in up.headers["Content-Disposition"]
    bad = client.post("/api/setup-file/fill", headers=hdr, files={"file": ("x.xlsx", b"not a workbook", "application/octet-stream")})
    assert bad.status_code == 400
    assert client.post("/api/setup-file", json={"styles": "999999"}, headers=hdr).status_code == 404


def app_instance():
    from pim.main import app

    return app
