"""IMP-02 AI mapping suggester: for header columns the fuzzy matcher could not place, ask the classify endpoint
(AI-01, AI-05) which attribute each column feeds. Suggestions carry a confidence, are hidden below the threshold,
and are never auto-accepted (P4); the person maps the column. Off until PIM_FEATURE_AI_MAPPING_SUGGEST=true."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

from pim.config import get_settings
from pim.services.metadata import Metadata

log = logging.getLogger(__name__)
TEMPLATE_CODE = "import_mapping_suggest"


def ai_suggester(session, meta: Metadata, level: str, sample_values: dict[str, list[str]] | None = None,  # noqa: ANN001
                 service=None, user_email: str = "system") -> Callable[[list[str]], list[dict]] | None:  # noqa: ANN001
    """Returns the `ai_suggest` callable for suggest_mappings, or None when the feature is off or no template exists."""
    if not get_settings().feature_ai_mapping_suggest:
        return None
    from pim.ai.service import AIService, BrandVoice, PromptTemplate
    from pim.models import PromptTemplate as TemplateRow

    tpl = session.get(TemplateRow, TEMPLATE_CODE)
    if tpl is None or tpl.status != "active":
        return None
    svc = service or AIService()
    candidates = [{"code": a.code, "label": a.label, "level": a.level, "type": a.data_type}
                  for a in meta.attributes.values() if a.status != "deprecated" and not a.level.startswith("ref:") and not a.is_erp]

    def suggest(columns: list[str]) -> list[dict]:
        if not columns:
            return []
        attrs = {"columns": json.dumps([{"column": c, "samples": (sample_values or {}).get(c, [])[:5]} for c in columns]),
                 "attributes": json.dumps(candidates), "level": level}
        prompt = PromptTemplate(code=tpl.code, version=str(tpl.version), task_type="classify", target_attribute="",
                                body=tpl.body, input_attributes=[], max_length=None)
        try:
            res = svc.run(prompt, BrandVoice(brand_code="system", tone="Answer with JSON only."), attrs, product_id="import",
                          user_email=user_email, grounded=False, temperature=0.0)
        except Exception:  # noqa: BLE001
            log.exception("AI mapping suggestion failed")
            return []
        return parse_suggestions(res.text, meta, set(columns))

    return suggest


def parse_suggestions(text: str, meta: Metadata, columns: set[str]) -> list[dict]:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out: list[dict] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        col, target = it.get("column"), it.get("attribute_code") or it.get("target")
        if col not in columns or target not in meta.attributes:
            continue
        try:
            conf = float(it.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        out.append({"column": col, "target": target, "confidence": max(0.0, min(1.0, conf)), "reason": str(it.get("reason") or "AI suggestion")[:200]})
    return out
