"""VA Product Information Setup File export.

The merchandising team hands each delivery to e-commerce and wholesale as a "Product Information Setup File": one row
per style-color, two header rows (a merged group row and a field row), 32 columns from Style Details to Sustainability.
This module builds that file from the PIM in two ways:

* `build_setup_workbook`: a new workbook for a selection of style-colors, in the setup file's column layout.
* `fill_setup_workbook`: takes a setup file someone already started, finds the header row, matches each row to a
  style-color by Style # and Color Code, and writes the PIM's values into the matching columns. Columns the PIM does
  not know are left as they are. A "PIM Export Report" sheet lists, per row, what was filled, what changed, and what
  is still blank, and which setup file columns have no PIM attribute yet.

The export reads the same values a channel export would: approved values only, no drafts, no unconfirmed defaults.
Field rights apply: a column whose attribute group the user cannot view comes out blank, never someone else's view.
"""

from __future__ import annotations

import html
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.auth.identity import CurrentUser
from pim.models import Asset, AssetLink, ProductEntity, ProductValue
from pim.models._common import utcnow
from pim.services.metadata import Metadata
from pim.services.values import resolve_cells

TEAL = "3B859C"
REPORT_SHEET = "PIM Export Report"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Families to the setup file's Category values. Used only when no `category` attribute is defined or filled.
FAMILY_CATEGORY = {
    "swim_top": "SWIMWEAR",
    "swim_bottom": "SWIMWEAR",
    "one_piece": "SWIMWEAR",
    "swim_set": "SWIMWEAR",
    "cover_up": "BEACHWEAR",
    "apparel": "BEACHWEAR",
}


@dataclass(frozen=True)
class Column:
    """One setup file column. `sources` are tried in order; the first that yields a value wins.

    Source forms:
      attr:<code>            an attribute at style, style-color or SKU level (SKU values are summarized across sizes)
      ref:<attr>.<inner>     an attribute of the referenced Fabric or Print record
      entity:<field>         a column of the product record (style_number, color_code, launch_date, lifecycle_status)
      erp:<field>            a raw ERP field kept on the product record
      family_category        the Category derived from the product family
      size_range             first and last size of the style-color's SKUs, in size scale order
      image                  the first confirmed image's URL
    """

    group: str
    header: str
    sources: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    width: float = 16


COLUMNS: tuple[Column, ...] = (
    Column("Style Details", "Delivery Date", ("attr:erp_delivery_date",), width=12),
    Column("Style Details", "Ecomm Launch Date", ("attr:ecomm_launch_date", "entity:launch_date"), width=12),
    Column("Style Details", "Category", ("attr:category", "family_category"), width=12),
    Column("Style Details", "Status", ("attr:erp_style_status", "entity:lifecycle_status"), width=14),
    Column("Style Details", "Style #", ("entity:style_number",), aliases=("style number", "style no", "style"), width=11),
    Column("Style Details", "Style Name", ("attr:product_name", "attr:erp_style_description"), width=26),
    Column("Style Details", "Style Image", ("image",), width=30),
    Column("Style Details", "Group", ("attr:collection",), width=18),
    Column("Style Details", "Color/Print", ("attr:customer_color_name", "attr:erp_color_description"), aliases=("color", "color name"), width=16),
    Column("Style Details", "Color Code", ("entity:color_code",), width=10),
    Column("Style Details", "Size Range", ("size_range",), width=11),
    Column("Style Details", "Wholesale $", ("attr:wholesale_price",), aliases=("wholesale",), width=11),
    Column("Style Details", "Retail $", ("attr:erp_retail_msrp",), aliases=("retail", "msrp"), width=10),
    Column("Production", "Fabrication", ("ref:fabric.fabric_name", "attr:fabric"), width=16),
    Column("Production", "Content", ("attr:erp_style_content",), width=28),
    Column("Production", "Care Instructions", ("attr:care_instructions", "ref:fabric.fabric_care"), width=36),
    Column("Production", "Country of Origin", ("attr:erp_country_of_origin",), width=10),
    Column("Production", "HTS Number", ("attr:hts_number",), width=14),
    Column("Production", "Weight", ("attr:weight",), width=9),
    Column("Design & Tech", "Fit Scale #", ("attr:fit_scale",), width=9),
    Column("Design & Tech", "Inseam", ("attr:inseam",), width=9),
    Column("Design & Tech", "Front Rise", ("attr:front_rise",), width=9),
    Column("Design & Tech", "Back Rise", ("attr:back_rise",), width=9),
    Column("Design & Tech", "CFL Length", ("attr:cfl_length",), width=9),
    Column("Design & Tech", "HPS Length", ("attr:hps_length",), width=9),
    Column("Design & Tech", "Strap Length", ("attr:strap_length",), width=9),
    Column("Design & Tech", "Fit Details", ("attr:fit_details", "attr:bullet_points"), width=40),
    Column("Merch", "Notes", ("attr:merch_notes",), aliases=("merch notes",), width=24),
    Column("SEO", "Key Words", ("attr:seo_keywords",), aliases=("keywords", "seo key words", "seo keywords"), width=24),
    Column("Copy", "Product Description", ("attr:product_description",), width=60),
    Column("Copy", "Secondary Description", ("ref:print.print_story", "ref:fabric.fabric_story"), width=60),
    Column("Copy", "Sustainability", ("ref:fabric.fabric_sustainability",), width=40),
)

DATE_HEADERS = {"Delivery Date", "Ecomm Launch Date"}
MONEY_HEADERS = {"Wholesale $", "Retail $"}


class SetupFileError(Exception):
    """The uploaded file is not a setup file this module can read."""


# ---------------------------------------------------------------------------------------------------
# Header handling
# ---------------------------------------------------------------------------------------------------
def normalize_header(text: Any) -> str:
    """'CFL    Length' -> 'cfl length'; 'Secondary Description   (Copy on print...)' -> 'secondary description'."""
    s = re.sub(r"\(.*?\)", " ", str(text or ""))
    return re.sub(r"\s+", " ", s).strip().lower()


_BY_NAME: dict[str, Column] = {}
for _c in COLUMNS:
    for _name in (_c.header, *_c.aliases):
        _BY_NAME.setdefault(normalize_header(_name), _c)


def column_for_header(text: Any) -> Column | None:
    return _BY_NAME.get(normalize_header(text))


def find_header_row(ws: Worksheet, scan_rows: int = 15) -> int:
    for r in range(1, min(ws.max_row, scan_rows) + 1):
        names = {normalize_header(c.value) for c in ws[r] if c.value is not None}
        if "style #" in names and "color code" in names:
            return r
    raise SetupFileError("Could not find the header row: the file needs a 'Style #' and a 'Color Code' column")


# ---------------------------------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------------------------------
_BLOCK_TAGS = re.compile(r"</?(p|div|br|ul|ol|h[1-6])\b[^>]*>", re.I)


def html_to_text(value: str) -> str:
    """Setup files are plain text. Descriptions imported from Shopify can hold HTML; keep line breaks and bullets."""
    if "<" not in value or ">" not in value:
        return value
    s = re.sub(r"<li\b[^>]*>", "\n• ", value, flags=re.I)
    s = _BLOCK_TAGS.sub("\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    lines = (re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines())
    return "\n".join(ln for ln in lines if ln)


def is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        s = v.strip()
        return s == "" or (s.startswith("#") and s.endswith("!")) or s in ("#N/A", "#VALUE!", "#REF!")
    return False


def _number(v: Any) -> Any:
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _same(a: Any, b: Any) -> bool:
    if is_blank(a) and is_blank(b):
        return True
    if isinstance(a, datetime):
        a = a.date()
    if isinstance(b, datetime):
        b = b.date()
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    na = re.sub(r"\s+", " ", str(a)).strip().lower()
    nb = re.sub(r"\s+", " ", str(b)).strip().lower()
    return na == nb


def _show(v: Any) -> str:
    if isinstance(v, datetime):
        v = v.date()
    if isinstance(v, date):
        return v.strftime("%m/%d/%Y")
    s = str(v)
    return s if len(s) <= 120 else s[:117] + "..."


def style_key(v: Any) -> str:
    """Style numbers arrive as text, int, or float (6000150.0) depending on who typed the cell."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


# ---------------------------------------------------------------------------------------------------
# Resolving PIM values for style-colors
# ---------------------------------------------------------------------------------------------------
@dataclass
class _Context:
    session: Session
    meta: Metadata
    user: CurrentUser
    cells: dict[str, dict[str, dict]] = field(default_factory=dict)  # entity id -> attr code -> ValueCell
    sku_cells: dict[str, dict[str, dict]] = field(default_factory=dict)
    skus: dict[str, list[ProductEntity]] = field(default_factory=dict)  # style-color id -> SKUs
    refs: dict[tuple[str, str], ProductValue] = field(default_factory=dict)  # (ref id, attr) -> value
    styles: dict[str, ProductEntity] = field(default_factory=dict)
    images: dict[str, str] = field(default_factory=dict)  # style-color id -> URL


def _attr_codes() -> set[str]:
    out: set[str] = set()
    for c in COLUMNS:
        for s in c.sources:
            if s.startswith("attr:"):
                out.add(s[5:])
            elif s.startswith("ref:"):
                out.add(s[4:].partition(".")[0])
    return out


def missing_attributes(meta: Metadata) -> dict[str, list[str]]:
    """Setup file header -> attribute codes the column reads that the PIM does not define yet."""
    out: dict[str, list[str]] = {}
    for c in COLUMNS:
        codes = [s[5:] for s in c.sources if s.startswith("attr:")]
        defined = [x for x in codes if x in meta.attributes]
        others = [s for s in c.sources if not s.startswith("attr:")]
        if codes and not defined and not others:
            out[c.header] = codes
    return out


def _load(session: Session, meta: Metadata, user: CurrentUser, ents: list[ProductEntity]) -> _Context:
    ctx = _Context(session, meta, user)
    if not ents:
        return ctx
    codes = sorted(c for c in _attr_codes() if c in meta.attributes)
    upper_codes = [c for c in codes if meta.attributes[c].level in ("style", "style_color")]
    sku_codes = [c for c in codes if meta.attributes[c].level == "sku"]
    ctx.cells = resolve_cells(session, meta, user, ents, upper_codes, include_drafts=False)
    parent_ids = {e.parent_id for e in ents if e.parent_id}
    if parent_ids:
        ctx.styles = {s.id: s for s in session.execute(select(ProductEntity).where(ProductEntity.id.in_(parent_ids))).scalars()}
    skus = session.execute(select(ProductEntity).where(ProductEntity.parent_id.in_([e.id for e in ents]),
                                                       ProductEntity.level == "sku")).scalars().all()
    for s in skus:
        ctx.skus.setdefault(s.parent_id, []).append(s)
    if sku_codes and skus:
        ctx.sku_cells = resolve_cells(session, meta, user, list(skus), sku_codes, include_drafts=False)
    ref_ids: set[str] = set()
    for row in ctx.cells.values():
        for code, cl in row.items():
            if meta.attributes[code].data_type == "reference_entity" and _usable(cl) and cl.get("value"):
                ref_ids.add(cl["value"])
    if ref_ids:
        for pv in session.execute(select(ProductValue).where(ProductValue.entity_id.in_(ref_ids),
                                                             ProductValue.channel_code == "")).scalars():
            ctx.refs[(pv.entity_id, pv.attribute_code)] = pv
    links = session.execute(
        select(AssetLink, Asset).join(Asset, Asset.id == AssetLink.asset_id)
        .where(AssetLink.entity_id.in_([e.id for e in ents]), AssetLink.status == "confirmed")
        .order_by(AssetLink.entity_id, AssetLink.sort_order, AssetLink.created_at)
    ).all()
    for link, asset in links:
        if link.entity_id not in ctx.images and asset.thumbnail_url:
            ctx.images[link.entity_id] = asset.thumbnail_url
    return ctx


def _usable(cl: dict | None) -> bool:
    """Same rule as channel exports: approved, not an unconfirmed default, not marked Not applicable."""
    if not cl or cl.get("read_only_reason") == "no_rights":
        return False
    return cl.get("approval_state") == "approved" and not cl.get("is_default") and not cl.get("not_applicable")


def _display(meta: Metadata, code: str, cl: dict) -> Any:
    attr = meta.attributes[code]
    v = cl.get("value")
    if v is None:
        return None
    if attr.data_type == "single_select":
        return cl.get("display") or meta.option_label(attr.option_list_code, v) or v
    if attr.data_type == "multi_select" and isinstance(v, list):
        return ", ".join(meta.option_label(attr.option_list_code, x) or x for x in v)
    if attr.data_type == "reference_entity":
        return cl.get("display")
    if attr.data_type == "date" and isinstance(v, str):
        try:
            return date.fromisoformat(v)
        except ValueError:
            return v
    if attr.data_type == "boolean":
        return "Yes" if v else "No"
    if attr.data_type in ("text", "rich_text") and isinstance(v, str):
        return html_to_text(v)
    return _number(v)


def _ref_display(meta: Metadata, code: str, pv: ProductValue) -> Any:
    attr = meta.attributes.get(code)
    if attr is None or pv.not_applicable or pv.approval_state != "approved":
        return None
    if attr.data_type == "single_select" and pv.value_text:
        return meta.option_label(attr.option_list_code, pv.value_text) or pv.value_text
    if attr.data_type == "multi_select" and isinstance(pv.value_json, list):
        return ", ".join(meta.option_label(attr.option_list_code, x) or x for x in pv.value_json)
    for v in (pv.value_text, pv.value_number, pv.value_date):
        if v is not None:
            return html_to_text(v) if isinstance(v, str) else _number(v)
    return None


def _sku_summary(values: list[Any]) -> Any:
    vals = [v for v in values if not is_blank(v)]
    if not vals:
        return None
    uniq = sorted(set(vals), key=lambda x: (str(type(x)), x))
    if len(uniq) == 1:
        return uniq[0]
    if all(isinstance(x, (int, float)) for x in uniq):
        return f"{_number(min(uniq))} - {_number(max(uniq))}"
    return ", ".join(str(x) for x in uniq)


def size_range(meta: Metadata, skus: Iterable[ProductEntity]) -> str | None:
    sizes: list[tuple[tuple, str]] = []
    seen: set[str] = set()
    for s in skus:
        if s.entity_type == "prepack" or not s.size or s.size in seen:
            continue
        seen.add(s.size)
        hit = meta.size_scale_entry(s.size)
        if hit:
            lst, v = hit
            order = (0, lst.code, v.sort_order, [x.code for x in lst.values].index(v.code))
            sizes.append((order, v.code))
        else:
            sizes.append(((1, "", 0, 0), s.size.strip().upper()))
    if not sizes:
        return None
    sizes.sort()
    first, last = sizes[0][1], sizes[-1][1]
    return first if first == last else f"{first} - {last}"


def _resolve(ctx: _Context, ent: ProductEntity, source: str) -> Any:
    meta = ctx.meta
    kind, _, arg = source.partition(":")
    if kind == "attr":
        attr = meta.attributes.get(arg)
        if attr is None:
            return None
        if attr.level == "sku":
            return _sku_summary([_display(meta, arg, ctx.sku_cells.get(s.id, {}).get(arg) or {})
                                 for s in ctx.skus.get(ent.id, [])
                                 if _usable(ctx.sku_cells.get(s.id, {}).get(arg))])
        cl = ctx.cells.get(ent.id, {}).get(arg)
        return _display(meta, arg, cl) if _usable(cl) else None
    if kind == "ref":
        ref_attr, _, inner = arg.partition(".")
        cl = ctx.cells.get(ent.id, {}).get(ref_attr)
        inner_attr = meta.attributes.get(inner)
        if not _usable(cl) or not cl.get("value") or inner_attr is None or not ctx.user.can_view_group(inner_attr.group_code):
            return None
        pv = ctx.refs.get((cl["value"], inner))
        return _ref_display(meta, inner, pv) if pv is not None else None
    if kind == "entity":
        v = getattr(ent, arg, None)
        if v in (None, "") and ent.parent_id in ctx.styles:
            v = getattr(ctx.styles[ent.parent_id], arg, None)
        if arg == "lifecycle_status" and isinstance(v, str):
            return v.replace("_", " ").title()
        return v
    if kind == "erp":
        erp = ent.erp_fields or (ctx.styles[ent.parent_id].erp_fields if ent.parent_id in ctx.styles else {}) or {}
        return erp.get(arg)
    if source == "family_category":
        fam = ent.family_code or (ctx.styles[ent.parent_id].family_code if ent.parent_id in ctx.styles else None)
        return FAMILY_CATEGORY.get(fam or "")
    if source == "size_range":
        return size_range(meta, ctx.skus.get(ent.id, []))
    if source == "image":
        return ctx.images.get(ent.id)
    raise ValueError(f"Unknown setup file source {source}")


def row_values(ctx: _Context, ent: ProductEntity) -> dict[str, Any]:
    """Setup file header -> PIM value (None when the PIM has nothing usable)."""
    out: dict[str, Any] = {}
    for col in COLUMNS:
        val = None
        for src in col.sources:
            val = _resolve(ctx, ent, src)
            if not is_blank(val):
                break
        out[col.header] = None if is_blank(val) else val
    return out


# ---------------------------------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------------------------------
def parse_style_keys(text_or_list: str | Iterable[str]) -> list[tuple[str, str | None]]:
    """'6000150' (every color), '6000150-MBU', '6000150 MBU' or '6000150/MBU' -> [(style, color or None)]."""
    items = re.split(r"[\n,;]+", text_or_list) if isinstance(text_or_list, str) else list(text_or_list)
    out: list[tuple[str, str | None]] = []
    for raw in items:
        s = str(raw).strip()
        if not s:
            continue
        parts = re.split(r"[\s\-/]+", s, maxsplit=1)
        style = parts[0].strip()
        color = parts[1].strip().upper() if len(parts) > 1 and parts[1].strip() else None
        out.append((style, color))
    return out


def find_style_colors(session: Session, user: CurrentUser, keys: list[tuple[str, str | None]]) -> dict[tuple[str, str | None], list[ProductEntity]]:
    """(style, color) -> matching style-color entities in the user's brand scope. A None color returns every color."""
    styles = {s for s, _ in keys}
    if not styles:
        return {}
    ents = session.execute(select(ProductEntity).where(ProductEntity.level == "style_color",
                                                       ProductEntity.style_number.in_(styles))
                           .order_by(ProductEntity.style_number, ProductEntity.color_code)).scalars().all()
    ents = [e for e in ents if user.in_brand_scope(e.brand_scopes or [])]
    out: dict[tuple[str, str | None], list[ProductEntity]] = {}
    for style, color in keys:
        out[(style, color)] = [e for e in ents if e.style_number == style
                               and (color is None or (e.color_code or "").upper() == color)]
    return out


# ---------------------------------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------------------------------
@dataclass
class RowReport:
    row: int
    style: str
    color: str
    name: str = ""
    result: str = "matched"  # matched | not_in_pim | no_key
    filled: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)  # "Header: old -> new"
    blank: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # file values the PIM has nothing for


@dataclass
class SetupFileResult:
    content: bytes
    file_name: str
    rows: list[RowReport]
    missing_attributes: dict[str, list[str]]
    unmapped_headers: list[str] = field(default_factory=list)
    images_dropped: bool = False

    @property
    def summary(self) -> dict:
        return {
            "file_name": self.file_name,
            "rows": len(self.rows),
            "matched": sum(1 for r in self.rows if r.result == "matched"),
            "not_in_pim": [f"{r.style}-{r.color}" for r in self.rows if r.result == "not_in_pim"],
            "no_key": [r.row for r in self.rows if r.result == "no_key"],
            "cells_filled": sum(len(r.filled) for r in self.rows),
            "cells_changed": sum(len(r.changed) for r in self.rows),
            "cells_blank": sum(len(r.blank) for r in self.rows),
            "columns_without_pim_attribute": sorted(self.missing_attributes),
            "unmapped_headers": self.unmapped_headers,
            "images_dropped": self.images_dropped,
        }


def _write_report(wb: Workbook, user: CurrentUser, result: SetupFileResult, mode: str) -> None:
    if REPORT_SHEET in wb.sheetnames:
        del wb[REPORT_SHEET]
    ws = wb.create_sheet(REPORT_SHEET)
    s = result.summary
    bold = Font(bold=True)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor=TEAL)
    ws.append(["Swim USA PIM: Product Information Setup File export"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Generated", utcnow().strftime("%Y-%m-%d %H:%M UTC")])
    ws.append(["Generated by", user.email])
    ws.append(["Mode", "Filled an uploaded setup file" if mode == "fill" else "New setup file from a PIM selection"])
    ws.append(["Rows", s["rows"]])
    ws.append(["Rows matched to the PIM", s["matched"]])
    ws.append(["Rows not found in the PIM", ", ".join(s["not_in_pim"]) or "None"])
    if s["no_key"]:
        ws.append(["Rows without a Style # or Color Code", ", ".join(str(r) for r in s["no_key"])])
    ws.append(["Cells filled from the PIM", s["cells_filled"]])
    ws.append(["Cells where the PIM value replaced a different file value", s["cells_changed"]])
    ws.append(["Cells still blank", s["cells_blank"]])
    ws.append(["Values come from approved PIM data only. Drafts, unapproved AI suggestions and unconfirmed defaults are left out."])
    if result.images_dropped:
        ws.append(["Pictures embedded in the uploaded file are not carried over. Style Image holds the PIM image link where one is confirmed."])
    ws.append([])
    if result.missing_attributes:
        ws.append(["Setup file columns with no PIM attribute yet", "Attribute code(s) the export looks for"])
        for c in ws[ws.max_row]:
            c.font = bold
        for header, codes in result.missing_attributes.items():
            ws.append([header, ", ".join(codes)])
        ws.append([])
    if result.unmapped_headers:
        ws.append(["Columns in the file the export does not fill", ", ".join(result.unmapped_headers)])
        ws.append([])
    ws.append(["Row", "Style #", "Color Code", "Style Name", "Result", "Filled from PIM", "Changed (file value -> PIM value)",
               "Still blank", "Kept from file (no PIM value)"])
    for c in ws[ws.max_row]:
        c.font = head_font
        c.fill = head_fill
    labels = {"matched": "Matched", "not_in_pim": "Not found in PIM", "no_key": "No Style # or Color Code"}
    wrap = Alignment(wrap_text=True, vertical="top")
    for r in result.rows:
        ws.append([r.row, r.style, r.color, r.name, labels.get(r.result, r.result), ", ".join(r.filled),
                   "\n".join(r.changed), ", ".join(r.blank), ", ".join(r.kept)])
        for c in ws[ws.max_row]:
            c.alignment = wrap
    for letter, width in zip("ABCDEFGHI", (7, 11, 11, 28, 18, 50, 60, 40, 40), strict=True):
        ws.column_dimensions[letter].width = width


# ---------------------------------------------------------------------------------------------------
# Writing cells
# ---------------------------------------------------------------------------------------------------
def _set_cell(ws: Worksheet, row: int, col: int, header: str, value: Any) -> None:
    c = ws.cell(row=row, column=col)
    if isinstance(value, datetime):
        value = value.date()
    c.value = value
    if header == "Style Image" and isinstance(value, str) and value.startswith("http"):
        c.hyperlink = value
        c.style = "Hyperlink"
    elif isinstance(value, date):
        c.number_format = "m/d/yyyy"
    elif header in MONEY_HEADERS and isinstance(value, (int, float)):
        c.number_format = "0.00"
    if isinstance(value, str) and "\n" in value:
        c.alignment = Alignment(wrap_text=True, vertical="top")


def _apply_row(ws: Worksheet, row: int, col_map: dict[int, Column], values: dict[str, Any], rep: RowReport,
               keep_file_values: bool) -> None:
    for idx, col in col_map.items():
        if col.header in ("Style #", "Color Code"):
            continue
        old = ws.cell(row=row, column=idx).value
        new = values.get(col.header)
        if new is None:
            if is_blank(old):
                rep.blank.append(col.header)
                if old is not None:  # an error value such as #VALUE! from a lost picture
                    ws.cell(row=row, column=idx).value = None
            else:
                rep.kept.append(col.header)
            continue
        if not is_blank(old) and _same(old, new):
            continue
        if not is_blank(old) and keep_file_values:
            rep.kept.append(col.header)
            continue
        if not is_blank(old):
            rep.changed.append(f"{col.header}: {_show(old)} -> {_show(new)}")
        rep.filled.append(col.header)
        _set_cell(ws, row, idx, col.header, new)


def _file_name(stem: str) -> str:
    return f"{stem}_{utcnow().strftime('%Y%m%d')}.xlsx"


def build_setup_workbook(session: Session, meta: Metadata, user: CurrentUser, entities: list[ProductEntity],
                         title: str = "PIM_Product_Information_Setup_File") -> SetupFileResult:
    """A new setup file for the given style-colors, in the VA setup file layout."""
    ents = [e for e in entities if e.level == "style_color"]
    ctx = _load(session, meta, user, ents)
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    groups = [c.group for c in COLUMNS]
    ws.append(groups)
    ws.append([c.header for c in COLUMNS])
    start = 1
    for i in range(2, len(groups) + 2):
        if i == len(groups) + 1 or groups[i - 1] != groups[start - 1]:
            if i - 1 > start:
                ws.merge_cells(start_row=1, start_column=start, end_row=1, end_column=i - 1)
            start = i
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=TEAL)
        c.alignment = Alignment(horizontal="center")
    for c in ws[2]:
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, col in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = col.width
    col_map = dict(enumerate(COLUMNS, start=1))
    reports: list[RowReport] = []
    for n, ent in enumerate(ents, start=3):
        values = row_values(ctx, ent)
        ws.cell(row=n, column=5, value=ent.style_number)
        ws.cell(row=n, column=10, value=ent.color_code)
        rep = RowReport(row=n, style=ent.style_number, color=ent.color_code or "", name=str(values.get("Style Name") or ""))
        _apply_row(ws, n, col_map, values, rep, keep_file_values=False)
        reports.append(rep)
    ws.freeze_panes = "F3"
    result = SetupFileResult(b"", _file_name(title), reports, missing_attributes(meta))
    _write_report(wb, user, result, "new")
    buf = io.BytesIO()
    wb.save(buf)
    result.content = buf.getvalue()
    return result


def fill_setup_workbook(session: Session, meta: Metadata, user: CurrentUser, content: bytes, file_name: str = "setup_file.xlsx",
                        keep_file_values: bool = False, sheet_name: str | None = None) -> SetupFileResult:
    """Fill an uploaded setup file in place with PIM values for every row that matches a style-color.

    keep_file_values=False (default): the PIM value wins wherever the PIM has one, and each replaced value is listed in
    the report. True: only empty cells are filled. Cells the PIM has no value for are never cleared.
    """
    try:
        wb = load_workbook(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 - openpyxl raises many types for a bad file
        raise SetupFileError("The file is not a readable .xlsx workbook") from exc
    candidates = [wb[sheet_name]] if sheet_name and sheet_name in wb.sheetnames else [
        w for w in wb.worksheets if w.title != REPORT_SHEET]
    ws = header_row = None
    for w in candidates:
        try:
            header_row = find_header_row(w)
            ws = w
            break
        except SetupFileError:
            continue
    if ws is None or header_row is None:
        raise SetupFileError("Could not find the header row: the file needs a 'Style #' and a 'Color Code' column")
    col_map: dict[int, Column] = {}
    unmapped: list[str] = []
    for c in ws[header_row]:
        if c.value is None:
            continue
        col = column_for_header(c.value)
        if col is not None and col not in col_map.values():
            col_map[c.column] = col
        else:
            unmapped.append(str(c.value).strip())
    style_col = next(i for i, c in col_map.items() if c.header == "Style #")
    color_col = next(i for i, c in col_map.items() if c.header == "Color Code")

    keyed: list[tuple[int, str, str]] = []
    reports: list[RowReport] = []
    for r in range(header_row + 1, ws.max_row + 1):
        style = style_key(ws.cell(row=r, column=style_col).value)
        color = style_key(ws.cell(row=r, column=color_col).value).upper()
        if not style and not color:
            continue
        if not style or not color:
            reports.append(RowReport(row=r, style=style, color=color, result="no_key"))
            continue
        keyed.append((r, style, color))
    matches = find_style_colors(session, user, [(s, c) for _, s, c in keyed])
    ents = {e.id: e for lst in matches.values() for e in lst}
    ctx = _load(session, meta, user, list(ents.values()))
    for r, style, color in keyed:
        found = matches.get((style, color)) or []
        if not found:
            reports.append(RowReport(row=r, style=style, color=color, result="not_in_pim"))
            continue
        values = row_values(ctx, found[0])
        rep = RowReport(row=r, style=style, color=color, name=str(values.get("Style Name") or ""))
        _apply_row(ws, r, col_map, values, rep, keep_file_values)
        reports.append(rep)
    reports.sort(key=lambda x: x.row)
    images_dropped = bool(re.search(rb"xl/(richData|media)/", _zip_names(content)))
    stem = re.sub(r"\.xlsx?$", "", file_name, flags=re.I) or "setup_file"
    result = SetupFileResult(b"", f"{stem}_PIM.xlsx", reports, missing_attributes(meta), unmapped, images_dropped)
    _write_report(wb, user, result, "fill")
    buf = io.BytesIO()
    wb.save(buf)
    result.content = buf.getvalue()
    return result


def _zip_names(content: bytes) -> bytes:
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            return "\n".join(z.namelist()).encode()
    except zipfile.BadZipFile:
        return b""


def style_colors_for(session: Session, user: CurrentUser, keys: list[tuple[str, str | None]]) -> tuple[list[ProductEntity], list[str]]:
    """Entities for a pasted list of style numbers, plus the keys that matched nothing."""
    found = find_style_colors(session, user, keys)
    ents: dict[str, ProductEntity] = {}
    missing: list[str] = []
    for (style, color), lst in found.items():
        if not lst:
            missing.append(style if color is None else f"{style}-{color}")
        for e in lst:
            ents.setdefault(e.id, e)
    return list(ents.values()), missing


__all__ = [
    "COLUMNS",
    "REPORT_SHEET",
    "XLSX_MEDIA_TYPE",
    "SetupFileError",
    "SetupFileResult",
    "build_setup_workbook",
    "fill_setup_workbook",
    "parse_style_keys",
    "style_colors_for",
]
