"""BlueCherry Style Master source (IMP-09, P1). The ERP already lands in Delta (catalog swim_data_whse).

Two implementations behind one interface:
  - DeltaStyleMasterSource: reads the Delta table through a SQL warehouse (Databricks SQL Statement API).
    Once the Lakebase synced table exists (PLT-00 step 6), point `table` at it via the same SQL.
  - CsvStyleMasterSource: reads a CSV export (local dev, tests, fixtures).

Both yield dicts with lower_snake_case keys. The hierarchy keys the app needs are: style_number, color_code, size,
sku, upc. Everything else is mapped to attributes through AttributeDefinition.erp_column (metadata, not code).
PLM columns (YPLM*) are ignored on purpose (D-08).
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from pim.config import get_settings

KEY_ALIASES = {
    # canonical -> accepted column headers (normalized lower_snake). Extend as the real Style Master dictates.
    "style_number": ["style_number", "style", "style_no", "style_#", "correct_style_#", "style_num"],
    "color_code": ["color_code", "color", "colour_code", "color_cd"],
    "size": ["size", "size_code", "style_master_size", "sz"],
    "sku": ["sku", "sku_number", "upc_sku", "item_number"],
    "upc": ["upc", "upc_code", "style_master_upc", "gtin", "ean"],
    "parent_sku": ["parent_sku"],
    "gms_style_no": ["gms_style_no", "gms_style_number", "legacy_style"],
    "product_type": ["product_type", "class", "category", "item_type"],
    "division": ["division", "division_desc", "division_name", "div"],
    "sub_division": ["sub_division", "subdivision", "sub_div", "sub_division_desc", "sub_division_name"],
    "brand_name": ["brand_name", "brand"],
    "brand_classification": ["brand_classification"],
    "style_description": ["style_description", "style_desc", "description"],
    "color_description": ["color_description", "color_desc", "color_name", "colour_description"],
    "season": ["season", "season_code", "season_cd"],
    "style_status": ["style_status", "status", "style_status_desc"],
    "delivery_date": ["delivery_date", "wholesale_delivery_date", "delivery"],
    "discontinued": ["discontinued", "is_discontinued", "inactive"],
    "pack_type": ["pack_type", "prepack", "assortment"],
    "pack_components": ["pack_components", "component_skus"],
}


def normalize_header(h: str) -> str:
    return re.sub(r"[^a-z0-9#]+", "_", h.strip().lower()).strip("_")


def canonicalize(row: dict[str, Any]) -> dict[str, Any]:
    """Rename recognized headers to canonical keys; keep every other column as normalized lower_snake."""
    out: dict[str, Any] = {}
    normalized = {normalize_header(k): v for k, v in row.items() if k is not None}
    taken: set[str] = set()
    for canon, aliases in KEY_ALIASES.items():
        for a in aliases:
            if a in normalized and a not in taken:
                out[canon] = normalized[a]
                taken.add(a)
                break
    for k, v in normalized.items():
        if k not in taken and k not in out:
            if k.startswith("yplm"):
                continue  # D-08: PLM is not a competing source
            out[k] = v
    return out


class CsvStyleMasterSource:
    name = "bluecherry_csv"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read_changes(self, since: datetime | None = None) -> Iterator[dict[str, Any]]:
        with self.path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                yield canonicalize(row)


class DeltaStyleMasterSource:
    """Reads the Style Master through Databricks SQL (Statement Execution API via the SDK)."""

    name = "bluecherry_delta"

    def __init__(self, table: str | None = None, warehouse_id: str | None = None, updated_column: str | None = None) -> None:
        s = get_settings()
        self.table = table or s.style_master_table
        self.warehouse_id = warehouse_id or s.sql_warehouse_id
        self.updated_column = updated_column

    def read_changes(self, since: datetime | None = None) -> Iterator[dict[str, Any]]:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.sql import Disposition, Format, StatementState

        if not self.warehouse_id:
            raise RuntimeError("PIM_SQL_WAREHOUSE_ID is required for Delta reads")
        w = WorkspaceClient()
        sql = f"SELECT * FROM {self.table}"
        if since and self.updated_column:
            sql += f" WHERE {self.updated_column} >= '{since.isoformat()}'"
        resp = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=self.warehouse_id, wait_timeout="50s",
            disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
        )
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            resp = w.statement_execution.get_statement(resp.statement_id)
        if resp.status and resp.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"Style Master query failed: {resp.status.error}")
        cols = [c.name for c in resp.manifest.schema.columns]
        chunk = resp.result
        while chunk is not None:
            for arr in chunk.data_array or []:
                yield canonicalize(dict(zip(cols, arr, strict=False)))
            if chunk.next_chunk_index is None:
                break
            chunk = w.statement_execution.get_statement_result_chunk_n(resp.statement_id, chunk.next_chunk_index)
