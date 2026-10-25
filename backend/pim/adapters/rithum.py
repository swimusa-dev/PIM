"""Rithum (formerly CommerceHub and Dsco) flat-file adapter for Nordstrom drop-ship (EXP-10, D-01) and Target+
(EXP-11, D-02). Both programs exchange product data as template-based files [C22], so this adapter builds on the
retailer feed renderer (EXP-09): columns and their settings come from the channel transport profile, normally
filled from the program's own template uploaded under Admin > Channels > Transport.

The default column sets below are placeholders for the first run and are UNCONFIRMED until the Rithum account's
templates are uploaded; the Target+ item rules (title of 150 characters or less, a GS1 UPC, 1:1 images of 1200 px
or more, a family checked as a unit) are UNCONFIRMED vendor claims [C17] applied only when `family_rules` is on.
Nordstrom image naming is VPN-SupplierColorName-01, photographs only, AI imagery disclosed [C21].
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from pim.adapters.base import NotConfigured, PublishResult, ValidationResult
from pim.adapters.feed_file import FeedColumn, FeedFileAdapter

TARGET_TITLE_MAX = 150  # UNCONFIRMED [C17]
TARGET_IMAGE_MIN = 1200  # UNCONFIRMED [C17]

DEFAULT_COLUMNS: dict[str, list[dict]] = {
    "nordstrom_dropship": [
        {"header": "Vendor Part Number", "source": "core.style_number", "required": True},
        {"header": "Supplier SKU", "source": "core.sku", "required": True},
        {"header": "UPC", "source": "gtin", "required": True},
        {"header": "Product Name", "source": "product_title", "required": True, "case_transform": "title"},
        {"header": "Description", "source": "product_description", "required": True},
        {"header": "Brand", "source": "erp_brand_name", "always_include": True},
        {"header": "Supplier Color Name", "source": "customer_color_name", "required": True, "case_transform": "title"},
        {"header": "NRF Color Code", "source": "nrf_color"},
        {"header": "Size", "source": "core.size", "required": True},
        {"header": "NRF Size Code", "source": "nrf_size"},
        {"header": "Fabric Content", "source": "erp_style_content", "case_transform": "sentence"},
        {"header": "Care", "source": "fabric.fabric_care"},
        {"header": "Country of Origin", "source": "erp_country_of_origin", "case_transform": "title"},
        {"header": "Wholesale Cost", "source": "erp_standard_cost"},
        {"header": "Retail Price", "source": "erp_retail_msrp"},
        {"header": "Image 1", "source": "image:1", "required": True},
        {"header": "Image 2", "source": "image:2"},
        {"header": "Image 3", "source": "image:3"},
        {"header": "AI Generated Imagery", "source": "image_ai_flag", "always_include": True},
    ],
    "targetplus": [
        {"header": "Parent SKU", "source": "core.style_number", "required": True},
        {"header": "SKU", "source": "core.sku", "required": True},
        {"header": "GTIN", "source": "gtin", "required": True},
        {"header": "Title", "source": "product_title", "required": True, "case_transform": "title"},
        {"header": "Description", "source": "product_description", "required": True},
        {"header": "Brand", "source": "erp_brand_name", "always_include": True},
        {"header": "Color", "source": "customer_color_name", "required": True, "case_transform": "title"},
        {"header": "Size", "source": "core.size", "required": True},
        {"header": "Variation Theme", "source": "const:Color-Size", "always_include": True},
        {"header": "Fabric Content", "source": "erp_style_content", "case_transform": "sentence"},
        {"header": "Country of Origin", "source": "erp_country_of_origin", "case_transform": "title"},
        {"header": "Retail Price", "source": "erp_retail_msrp"},
        {"header": "Main Image", "source": "image:1", "required": True},
        {"header": "Alt Image 1", "source": "image:2"},
        {"header": "Alt Image 2", "source": "image:3"},
    ],
}
_GTIN = re.compile(r"^\d{12,14}$")


def columns_from_config(cols: list[dict] | None, program: str) -> list[FeedColumn]:
    raw = cols if cols is not None and len(cols) > 0 else DEFAULT_COLUMNS.get(program, DEFAULT_COLUMNS["nordstrom_dropship"])
    return [FeedColumn(header=c["header"], source=c.get("source", ""), always_include=bool(c.get("always_include")),
                       case_transform=c.get("case_transform", "as_is"), value_map=dict(c.get("value_map") or {}),
                       required=bool(c.get("required"))) for c in raw]


def image_name(vpn: str, supplier_color_name: str, seq: int, prefix: str | None = None) -> str:
    """Nordstrom image naming VPN-SupplierColorName-01 [C21]; the optional VPN prefix comes from the profile."""
    color = re.sub(r"[^A-Za-z0-9]+", "", (supplier_color_name or "").title())
    return f"{(prefix or '') + vpn}-{color}-{seq:02d}"


class RithumFeedAdapter:
    name = "rithum"

    def __init__(self, program: str = "nordstrom_dropship", columns: list[dict] | None = None, family_rules: bool | None = None,
                 template_bytes: bytes | None = None, header_row: int = 1, api_key: str | None = None, supplier_id: str | None = None,
                 vpn_prefix: str | None = None) -> None:
        self.program = program if program in DEFAULT_COLUMNS else "nordstrom_dropship"
        self.family_rules = (program == "targetplus") if family_rules is None else bool(family_rules)
        self.columns = columns_from_config(columns, self.program)
        self.feed = FeedFileAdapter(self.columns, template_bytes=template_bytes, header_row=header_row)
        self.api_key, self.supplier_id, self.vpn_prefix = api_key, supplier_id, vpn_prefix

    # ---- rendering ----------------------------------------------------------------------------------
    def render_rows(self, products: Iterable[dict]) -> list[dict[str, str | None]]:
        return self.feed.render_rows(products)

    def to_csv(self, products: Iterable[dict]) -> bytes:
        return self.feed.to_csv(products)

    def to_xlsx(self, products: Iterable[dict]) -> bytes:
        return self.feed.to_xlsx(products)

    # ---- validation ----------------------------------------------------------------------------------
    def validate(self, payload: Iterable[dict]) -> ValidationResult:
        rows = list(payload)
        base = self.feed.validate(rows)
        errors = list(base.errors)
        if self.family_rules:
            errors += self._family_errors(rows)
        return ValidationResult(ok=not errors, errors=errors)

    def _family_errors(self, rows: list[dict]) -> list[dict]:
        """Target+: parent/child families with a variation theme; one invalid child fails the whole family [C17]."""
        families: dict[str, list[dict]] = {}
        for r in rows:
            fam = str(r.get("core.style_number") or r.get("Parent SKU") or r.get("family_id") or r.get("variant_group") or "")
            families.setdefault(fam, []).append(r)
        out: list[dict] = []
        for fam, items in families.items():
            bad: list[str] = []
            for it in items:
                title = str(it.get("product_title") or it.get("Title") or "")
                upc = str(it.get("gtin") or it.get("core.upc") or it.get("GTIN") or "").strip()
                if len(title) > TARGET_TITLE_MAX:
                    bad.append(f"{it.get('core.sku') or it.get('SKU')}: title longer than {TARGET_TITLE_MAX}")
                if not _GTIN.match(upc):
                    bad.append(f"{it.get('core.sku') or it.get('SKU')}: GTIN missing or not 12 to 14 digits")
                w, h = it.get("image_width"), it.get("image_height")
                if w and h and (w != h or w < TARGET_IMAGE_MIN):
                    bad.append(f"{it.get('core.sku') or it.get('SKU')}: main image must be 1:1 and at least {TARGET_IMAGE_MIN} px")
            if bad:
                out.append({"family": fam, "message": f"{len(bad)} child item(s) invalid; the whole family fails", "details": bad[:20],
                            "kind": "internal"})
        return out

    # ---- transport -----------------------------------------------------------------------------------
    def publish(self, batch: list[dict], dry_run: bool = False) -> PublishResult:
        if dry_run or not self.api_key:
            return PublishResult(batch_id="file", accepted=len(batch), status="dry_run" if dry_run else "generated",
                                 detail={"program": self.program, "delivery": "file"})
        raise NotConfigured("Rithum API upload is not built; deliver the generated file through the channel transport (SFTP, email or download)")

    def fetch_status(self, batch_id: str) -> dict:
        return {"batch_id": batch_id, "status": "n/a (file delivery); upload Rithum's error report as feedback"}

    def fetch_errors(self, batch_id: str) -> list[dict]:
        return []


def rithum_for_channel(channel, template_bytes: bytes | None = None) -> RithumFeedAdapter:  # noqa: ANN001
    cfg = channel.config or {}
    r = cfg.get("rithum") or {}
    return RithumFeedAdapter(program=r.get("program") or ("targetplus" if channel.code == "targetplus" else "nordstrom_dropship"),
                             columns=cfg.get("feed_columns"), family_rules=r.get("family_rules"), template_bytes=template_bytes,
                             header_row=int(cfg.get("header_row") or 1), supplier_id=r.get("supplier_id"), vpn_prefix=r.get("vpn_prefix"))


def nrf_code(option_value, kind: str) -> Any:  # noqa: ANN001
    """GS1 NRF color and size codes ride on the option value's channel_mappings under the key `nrf` [C18][C19]."""
    if option_value is None:
        return None
    return (option_value.channel_mappings or {}).get("nrf") or (option_value.channel_mappings or {}).get(f"nrf_{kind}")
