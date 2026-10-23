"""Retailer data-feed export adapter (EXP-09): fills an XLSX template or writes CSV with per-column settings:
always_include_even_if_empty (F14), case_transform (F6), size and color value mapping (DM-14, IMP-03).
Delivery by download in v1; SFTP and email are config hooks."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, field

from openpyxl import Workbook, load_workbook

from pim.adapters.base import PublishResult, ValidationResult


@dataclass
class FeedColumn:
    header: str
    source: str  # attribute code or core field
    always_include: bool = False
    case_transform: str = "as_is"  # as_is | title | sentence | upper | lower
    value_map: dict[str, str] = field(default_factory=dict)
    required: bool = False


def transform_case(value: str | None, mode: str) -> str | None:
    if value is None:
        return None
    if mode == "title":
        return value.title()
    if mode == "sentence":
        return value[:1].upper() + value[1:].lower() if value else value
    if mode == "upper":
        return value.upper()
    if mode == "lower":
        return value.lower()
    return value


class FeedFileAdapter:
    name = "feed_file"

    def __init__(self, columns: list[FeedColumn], template_path: str | None = None, header_row: int = 1) -> None:
        self.columns = columns
        self.template_path = template_path
        self.header_row = header_row

    def render_rows(self, products: Iterable[dict]) -> list[dict[str, str | None]]:
        out = []
        for p in products:
            row: dict[str, str | None] = {}
            for c in self.columns:
                raw = p.get(c.source)
                if isinstance(raw, list):
                    raw = ", ".join(str(x) for x in raw)
                val = None if raw is None else str(raw)
                if val is not None and c.value_map:
                    val = c.value_map.get(val, val)
                val = transform_case(val, c.case_transform)
                if val is None and not c.always_include:
                    val = None
                row[c.header] = val
            out.append(row)
        return out

    def to_csv(self, products: Iterable[dict]) -> bytes:
        rows = self.render_rows(products)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=[c.header for c in self.columns])
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})
        return buf.getvalue().encode("utf-8")

    def to_xlsx(self, products: Iterable[dict]) -> bytes:
        rows = self.render_rows(products)
        if self.template_path:
            wb = load_workbook(self.template_path)  # preserves formatting, header rows, data validation
            ws = wb.active
            headers = {str(c.value).strip(): c.column for c in ws[self.header_row] if c.value}
            for i, r in enumerate(rows, start=self.header_row + 1):
                for h, v in r.items():
                    if h in headers:
                        ws.cell(row=i, column=headers[h], value=v)
        else:
            wb = Workbook()
            ws = wb.active
            ws.append([c.header for c in self.columns])
            for r in rows:
                ws.append([r.get(c.header) for c in self.columns])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def validate(self, payload: Iterable[dict]) -> ValidationResult:
        errors = []
        for r in self.render_rows(payload):
            for c in self.columns:
                if c.required and not r.get(c.header):
                    errors.append({"column": c.header, "message": "required but empty"})
        return ValidationResult(ok=not errors, errors=errors)

    def publish(self, batch: list[dict], dry_run: bool = False) -> PublishResult:
        return PublishResult(batch_id="download", accepted=len(batch), status="dry_run" if dry_run else "generated")

    def fetch_status(self, batch_id: str) -> dict:
        return {"batch_id": batch_id, "status": "n/a (file delivery)"}

    def fetch_errors(self, batch_id: str) -> list[dict]:
        return []
