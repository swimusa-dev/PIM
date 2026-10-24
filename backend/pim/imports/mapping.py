"""IMP-02 mapping suggestions and template auto-apply.

Suggestions come from header similarity against attribute labels, codes, and ERP column names (rapidfuzz), plus a
small synonym table for the hierarchy keys. An AI suggester (AI-05 classify) can be plugged in through `ai_suggest`;
either way suggestions are shown with a confidence, hidden below the threshold, and never auto-accepted."""

from __future__ import annotations

from collections.abc import Callable

from rapidfuzz import fuzz

from pim.imports.parsers import normalize_header
from pim.services.metadata import Metadata

CORE_SYNONYMS = {
    "style_number": ["style", "style number", "style #", "style no", "style num", "correct style #", "parent style"],
    "color_code": ["color", "color code", "colour", "colour code", "color cd", "clr"],
    "size": ["size", "size code", "sz"],
    "sku": ["sku", "sku number", "item number", "variant sku"],
    "upc": ["upc", "gtin", "ean", "barcode", "variant barcode"],
    "family_code": ["family", "product type", "category"],
}


def suggest_mappings(columns: list[str], meta: Metadata, level: str, already: set[str] | None = None,
                     threshold: float = 0.70, ai_suggest: Callable[[list[str]], list[dict]] | None = None) -> list[dict]:
    already = already or set()
    targets: list[tuple[str, str, str]] = []  # (target, text, kind)
    for core, syns in CORE_SYNONYMS.items():
        for s in syns:
            targets.append((core, s, "core"))
    for a in meta.attributes.values():
        if a.status == "deprecated" or a.level.startswith("ref:"):
            continue
        targets.append((a.code, a.label, "attribute"))
        targets.append((a.code, a.code.replace("_", " "), "attribute"))
        if a.erp_column:
            targets.append((a.code, a.erp_column.replace("_", " "), "attribute"))
    out: list[dict] = []
    for col in columns:
        if col in already:
            continue
        key = normalize_header(col)
        best: tuple[float, str, str] | None = None
        for target, text, kind in targets:
            score = fuzz.token_set_ratio(key, normalize_header(text)) / 100.0
            if kind == "core" and key == normalize_header(text):
                score = 1.0
            if best is None or score > best[0]:
                best = (score, target, text)
        if best and best[0] >= threshold:
            out.append({"column": col, "target": best[1], "confidence": round(best[0], 2), "reason": f"header matches '{best[2]}'"})
    if ai_suggest is not None:
        remaining = [c for c in columns if c not in already and c not in {o["column"] for o in out}]
        if remaining:
            for s in ai_suggest(remaining):
                if float(s.get("confidence", 0)) >= threshold and s.get("target") in meta.attributes:
                    out.append({"column": s["column"], "target": s["target"], "confidence": round(float(s["confidence"]), 2),
                                "reason": s.get("reason", "AI suggestion")})
    return out


def required_unmapped(mapping: list[dict], meta: Metadata, level: str, required_codes: list[str]) -> list[str]:
    mapped = {m.get("target") for m in mapping if m.get("target") and not m.get("skip")}
    return [c for c in required_codes if c not in mapped]
