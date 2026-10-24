"""IMP-02 saved transformations: trim, split, concatenate, regex extract, value replace, unit conversion, HTML clean,
date parsing, case. Applied to the combined value of up to four source columns."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

_TAG = re.compile(r"<[^>]+>")
_UNITS = {("in", "cm"): 2.54, ("cm", "in"): 1 / 2.54, ("lb", "kg"): 0.45359237, ("kg", "lb"): 1 / 0.45359237,
          ("oz", "g"): 28.349523125, ("g", "oz"): 1 / 28.349523125, ("mm", "in"): 1 / 25.4, ("in", "mm"): 25.4}
_FRACTION = re.compile(r"(\d+)\s+(\d+)/(\d+)")


def _num(s: str) -> float | None:
    s = s.strip().replace(",", "").replace('"', "").replace("in", "").strip()
    m = _FRACTION.match(s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    if "/" in s and " " not in s:
        a, b = s.split("/", 1)
        try:
            return float(a) / float(b)
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def apply_one(value: str | None, op: str, args: dict[str, Any]) -> str | None:
    if value is None:
        return None
    if op == "trim":
        return value.strip()
    if op == "split":
        parts = value.split(str(args.get("delimiter", ",")))
        idx = int(args.get("index", 0))
        return parts[idx].strip() if -len(parts) <= idx < len(parts) else None
    if op == "regex_extract":
        m = re.search(str(args.get("pattern", "")), value)
        if not m:
            return None
        g = args.get("group", 1)
        try:
            return m.group(int(g) if str(g).isdigit() else g)
        except (IndexError, KeyError):
            return None
    if op == "value_replace":
        mapping = {str(k).strip().lower(): v for k, v in (args.get("map") or {}).items()}
        return str(mapping.get(value.strip().lower(), value))
    if op == "unit_convert":
        n = _num(value)
        factor = _UNITS.get((str(args.get("from", "")).lower(), str(args.get("to", "")).lower()))
        if n is None or factor is None:
            return value
        return f"{round(n * factor, 4):g}"
    if op == "html_clean":
        return html.unescape(_TAG.sub(" ", value)).replace("\xa0", " ").strip()
    if op == "date_parse":
        formats = args.get("formats") or ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m.%d.%y", "%m.%d.%Y", "%d-%b-%Y"]
        s = value.strip()
        for fmt in formats:
            try:
                return datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                continue
        return value
    if op == "case":
        mode = str(args.get("mode", "as_is"))
        return {"title": value.title(), "upper": value.upper(), "lower": value.lower(),
                "sentence": (value[:1].upper() + value[1:].lower()) if value else value}.get(mode, value)
    if op == "concat":
        return value  # handled when joining sources
    return value


def combine_sources(raw: dict[str, str], sources: list[str], transforms: list[dict]) -> str | None:
    values = [raw.get(s, "") or "" for s in sources[:4]]
    values = [v for v in values if v != ""]
    if not values:
        return None
    sep = " "
    for t in transforms:
        if t.get("op") == "concat":
            sep = str((t.get("args") or {}).get("separator", " "))
    value: str | None = sep.join(values) if len(values) > 1 else values[0]
    for t in transforms:
        if t.get("op") == "concat":
            continue
        value = apply_one(value, str(t.get("op")), t.get("args") or {})
        if value is None:
            break
    return value


def map_row(raw: dict[str, str], mapping: list[dict]) -> dict[str, Any]:
    """Apply a column mapping to one raw row -> {target: value}. Later mappings to the same target do not overwrite
    a non-empty earlier value (lets a second source column act as a fallback)."""
    out: dict[str, Any] = {}
    for m in mapping:
        target = m.get("target")
        if not target or target == "skip" or m.get("skip"):
            continue
        val = combine_sources(raw, m.get("sources") or [], m.get("transforms") or [])
        if val is None or val == "":
            out.setdefault(target, None)
            continue
        if out.get(target) in (None, ""):
            out[target] = val
    return out
