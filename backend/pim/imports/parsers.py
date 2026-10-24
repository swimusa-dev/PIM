"""IMP-01 file parsing: CSV and XLSX (multiple sheets, header row not necessarily row 1, merged group header rows
like today's setup file, dates as text, curly quotes). Also recognizes keyed worksheets (IMP-12) by their hidden
`_pim` sheet. Everything is returned as strings; typing happens in validation against attribute metadata."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook

WORKSHEET_SHEET = "_pim"
MAX_HEADER_SCAN = 15


@dataclass
class ColumnInfo:
    name: str
    group: str | None = None
    samples: list[str] = field(default_factory=list)
    index: int = 0


@dataclass
class ParsedFile:
    name: str
    sheet: str | None
    header_row: int  # 1-based
    group_header_row: int | None
    data_start_row: int
    columns: list[ColumnInfo]
    rows: list[dict[str, str]]
    worksheet_meta: dict | None = None
    hidden_columns: list[str] = field(default_factory=list)

    def as_dict(self, index: int, precedence: int) -> dict:
        return {"index": index, "name": self.name, "sheet": self.sheet, "header_row": self.header_row,
                "group_header_row": self.group_header_row, "data_start_row": self.data_start_row, "rows": len(self.rows),
                "columns": [{"name": c.name, "group": c.group, "samples": c.samples} for c in self.columns],
                "precedence": precedence, "worksheet_meta": self.worksheet_meta, "signature": structure_signature([c.name for c in self.columns])}


def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'").strip()


def normalize_header(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower())


def structure_signature(headers: list[str]) -> str:
    """Stable id of a file layout (IMP-02 auto-apply): hash of the normalized header names in order."""
    joined = "|".join(normalize_header(h) for h in headers if h)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def detect_header(grid: list[list[str]]) -> tuple[int, int | None]:
    """Return (header_row_idx, group_header_row_idx) as 0-based indexes.

    The header row is the row within the first MAX_HEADER_SCAN rows with the most distinct non-empty text cells.
    The row above it is a group header when it is mostly text, has fewer distinct values than filled cells (merged
    group cells repeat after forward-fill, or are blank), and the row above that is not more header-like."""
    best, best_score = 0, -1
    for i, row in enumerate(grid[:MAX_HEADER_SCAN]):
        cells = [c for c in row if c]
        if not cells:
            continue
        texts = [c for c in cells if not _looks_numeric(c)]
        score = len(set(texts)) + (0.5 if len(texts) == len(cells) else 0)
        if score > best_score:
            best, best_score = i, score
    group_idx = None
    if best > 0:
        above = [c for c in grid[best - 1] if c]
        header_filled = len([c for c in grid[best] if c])
        # a group row repeats values (or leaves merged cells blank), is all text, and has fewer distinct values
        # than the header has columns; a single title cell does not qualify
        if len(above) >= 2 and all(not _looks_numeric(c) for c in above) and len(set(above)) < header_filled:
            group_idx = best - 1
    return best, group_idx


def _looks_numeric(s: str) -> bool:
    try:
        float(s.replace(",", ""))
        return True
    except ValueError:
        return False


def _build(name: str, sheet: str | None, grid: list[list[str]], header_row: int | None = None,
           group_row: int | None = None, worksheet_meta: dict | None = None, hidden: list[str] | None = None) -> ParsedFile:
    if header_row is None:
        h, g = detect_header(grid)
    else:
        h, g = header_row, group_row
    headers_raw = grid[h] if h < len(grid) else []
    width = max((len(r) for r in grid), default=0)
    headers: list[str] = []
    seen: dict[str, int] = {}
    for i in range(width):
        hname = headers_raw[i] if i < len(headers_raw) else ""
        hname = hname or f"Column {i + 1}"
        if hname in seen:
            seen[hname] += 1
            hname = f"{hname} ({seen[hname]})"
        else:
            seen[hname] = 1
        headers.append(hname)
    groups: list[str | None] = [None] * width
    if g is not None:
        last = None
        for i in range(width):
            val = grid[g][i] if i < len(grid[g]) else ""
            if val:
                last = val
            groups[i] = last
    rows: list[dict[str, str]] = []
    for r in grid[h + 1:]:
        if not any(c for c in r):
            continue
        rows.append({headers[i]: (r[i] if i < len(r) else "") for i in range(width)})
    columns = []
    for i, hname in enumerate(headers):
        samples = [row[hname] for row in rows if row.get(hname)][:3]
        columns.append(ColumnInfo(name=hname, group=groups[i], samples=samples, index=i))
    return ParsedFile(name=name, sheet=sheet, header_row=h + 1, group_header_row=(g + 1) if g is not None else None,
                      data_start_row=h + 2, columns=columns, rows=rows, worksheet_meta=worksheet_meta, hidden_columns=hidden or [])


def parse_csv(name: str, content: bytes, header_row: int | None = None) -> ParsedFile:
    text = content.decode("utf-8-sig", errors="replace")
    grid = [[_cell_str(c) for c in row] for row in csv.reader(io.StringIO(text))]
    return _build(name, None, grid, None if header_row is None else header_row - 1)


def parse_xlsx(name: str, content: bytes, header_row: int | None = None) -> list[ParsedFile]:
    wb = load_workbook(io.BytesIO(content), data_only=True, read_only=False)
    meta = read_worksheet_meta(wb)
    out: list[ParsedFile] = []
    for ws in wb.worksheets:
        if ws.title == WORKSHEET_SHEET or ws.sheet_state != "visible" and meta is None:
            continue
        if meta is not None and ws.title.lower() == "instructions":
            continue
        grid = [[_cell_str(c) for c in row] for row in ws.iter_rows(values_only=True)]
        if not any(any(c for c in r) for r in grid):
            continue
        hidden = [k for k, dim in ws.column_dimensions.items() if dim.hidden]
        hr, gr = (None, None)
        if meta is not None:
            hr, gr = int(meta.get("header_row", 2)) - 1, int(meta.get("group_header_row", 1)) - 1
        elif header_row is not None:
            hr = header_row - 1
        out.append(_build(name, ws.title, grid, hr, gr, meta, hidden))
        if meta is not None:
            break  # a keyed worksheet has one data sheet
    return out


def read_worksheet_meta(wb) -> dict | None:  # noqa: ANN001
    if WORKSHEET_SHEET not in wb.sheetnames:
        return None
    ws = wb[WORKSHEET_SHEET]
    meta: dict[str, Any] = {}
    for row in ws.iter_rows(values_only=True):
        if row and row[0] is not None:
            meta[str(row[0])] = row[1]
    return meta if meta.get("worksheet_id") else None


def parse_upload(filename: str, content: bytes, header_row: int | None = None) -> list[ParsedFile]:
    lower = filename.lower()
    if lower.endswith(".csv") or lower.endswith(".txt"):
        return [parse_csv(filename, content, header_row)]
    if lower.endswith(".xlsx") or lower.endswith(".xlsm"):
        return parse_xlsx(filename, content, header_row)
    raise ValueError("Unsupported file type; upload CSV or XLSX")
