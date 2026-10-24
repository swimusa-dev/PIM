"""AI-03 / AI-04 / AI-05 task execution: build the grounded input set for a product, render the managed template
(AI-02), call the model through the AIService seam (AI-01), parse the answer per task type, and land every result
as an AiOutput plus, when it is a value, a ValueDraft with ai_generated=True and state=proposed. Accept, edit then
accept, regenerate and reject are the only ways a suggestion reaches a product value (P4).

Task types (AI-05): generate, adapt (channel override with the channel's length limit), extract (free text,
document, images), classify (option code with confidence), check (findings only), restructure (several
attributes from one legacy field), expand (abbreviated ERP value to customer-facing text).
"""

from __future__ import annotations

import base64
import difflib
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.adapters.base import NotConfigured
from pim.ai.service import AIService, BrandVoice
from pim.ai.service import PromptTemplate as RenderTemplate
from pim.auth.identity import CurrentUser
from pim.config import get_settings
from pim.models import (
    AiOutput,
    AiRun,
    AppEvent,
    AssetLink,
    AttributeDefinition,
    ProductEntity,
    ProductValue,
    ReferenceEntity,
    ValueDraft,
)
from pim.models import BrandVoice as BrandVoiceRow
from pim.models import PromptTemplate as TemplateRow
from pim.models._common import utcnow
from pim.services.metadata import Metadata
from pim.services.values import ValueError_, coerce, decide_drafts, resolve_cells, typed_from_row

log = logging.getLogger(__name__)

TASK_TYPES = ("generate", "adapt", "extract", "classify", "check", "restructure", "expand")
STRUCTURED = ("extract", "classify", "check", "restructure")
CORE = ("style_number", "color_code", "size", "sku", "upc", "label", "family_code", "lifecycle_status")


class AiTaskError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------------
# Brand voice and template rows -> service objects
# ---------------------------------------------------------------------------------------------------
def voice_for(session: Session, brand_code: str) -> BrandVoice:
    row = session.get(BrandVoiceRow, brand_code) or session.get(BrandVoiceRow, "vitamin_a")
    if row is None:
        from pim.ai.service import DEFAULT_VITAMIN_A_VOICE

        return DEFAULT_VITAMIN_A_VOICE
    return BrandVoice(brand_code=row.brand_code, tone=row.tone or "", do_rules=list(row.do_rules or []), dont_rules=list(row.dont_rules or []),
                      blocked_terms=list(row.blocked_terms or []), trademark_terms=dict(row.trademark_terms or {}),
                      punctuation_rules=list(row.punctuation_rules or ["Never use the em dash character."]), examples=list(row.examples or []))


def templates_for(session: Session, meta: Metadata, ent: ProductEntity, attribute: str | None = None,
                  status: str = "active") -> list[TemplateRow]:
    """Templates that apply to this product: level of the target (style attributes come from the parent style),
    family filter, and brand scope."""
    rows = session.execute(select(TemplateRow).where(TemplateRow.status == status).order_by(TemplateRow.task_type, TemplateRow.label)).scalars().all()
    out = []
    scopes = set(ent.brand_scopes or [])
    for t in rows:
        targets = [t.target_attribute] if t.target_attribute else list(t.output_attributes or [])
        if attribute and attribute not in targets:
            continue
        if t.family_code and t.family_code != ent.family_code:
            continue
        if scopes and t.brand_code not in scopes and t.brand_code != "vitamin_a":
            continue
        levels = {meta.attributes[c].level for c in targets if c in meta.attributes}
        if levels and not levels & {ent.level, "style" if ent.level in ("style_color", "sku") else ent.level}:
            continue
        out.append(t)
    return out


# ---------------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------------
@dataclass
class TaskInputs:
    attrs: dict[str, Any] = field(default_factory=dict)  # facts given to the model, keyed by code or ref path
    core: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    image_urls: list[str] = field(default_factory=list)
    options: dict[str, list[dict]] = field(default_factory=dict)  # attribute code -> [{code,label}]
    has_certificate: bool = False
    missing: list[str] = field(default_factory=list)
    max_length: int | None = None


def _owner_for(session: Session, ent: ProductEntity, attr: AttributeDefinition) -> ProductEntity | None:
    """The entity that owns a value at the attribute's level (strict ownership, DM-01)."""
    cur: ProductEntity | None = ent
    while cur is not None and cur.level != attr.level:
        cur = session.get(ProductEntity, cur.parent_id) if cur.parent_id else None
    return cur


def _ref_value(session: Session, meta: Metadata, ref_id: str, inner: str) -> Any:
    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == ref_id, ProductValue.attribute_code == inner,
                                                    ProductValue.channel_code == "")).scalar_one_or_none()
    if pv is None:
        return None
    attr = meta.attributes.get(inner)
    t = typed_from_row(pv)
    if attr and attr.data_type == "single_select":
        return meta.option_label(attr.option_list_code, t.text) or t.text
    if attr and attr.data_type == "multi_select" and isinstance(t.json, list):
        return ", ".join(meta.option_label(attr.option_list_code, c) or c for c in t.json)
    return t.as_python()


def build_inputs(session: Session, meta: Metadata, user: CurrentUser, ent: ProductEntity, tpl: TemplateRow, *,
                 channel_code: str = "", text: str | None = None, document: dict | None = None,
                 image_asset_ids: list[str] | None = None) -> TaskInputs:
    inp = TaskInputs(core={k: getattr(ent, k, None) for k in CORE})
    style = session.get(ProductEntity, ent.parent_id) if ent.level != "style" and ent.parent_id else None
    for k in CORE:
        if inp.core.get(k) in (None, "") and style is not None:
            inp.core[k] = getattr(style, k, None)
    plain = [c for c in tpl.input_attributes or [] if "." not in c and c in meta.attributes]
    refs = [c for c in tpl.input_attributes or [] if "." in c]
    cells = resolve_cells(session, meta, user, [ent], plain, channel_code or None, include_drafts=False).get(ent.id, {}) if plain else {}
    for code in plain:
        cell = cells.get(code) or {}
        v = cell.get("display") if cell.get("display") not in (None, "") else cell.get("value")
        if v in (None, "", []):
            inp.missing.append(code)
        else:
            inp.attrs[code] = v
    for path in refs:
        base, inner = path.split(".", 1)
        attr = meta.attributes.get(base)
        if attr is None or attr.data_type != "reference_entity":
            continue
        owner = _owner_for(session, ent, attr)
        pv = session.execute(select(ProductValue).where(ProductValue.entity_id == owner.id, ProductValue.attribute_code == base,
                                                        ProductValue.channel_code == "")).scalar_one_or_none() if owner else None
        if pv is None or not pv.value_ref or pv.approval_state != "approved":
            inp.missing.append(path)
            continue
        ref = session.get(ReferenceEntity, pv.value_ref)
        if ref is not None and ref.certificate_refs:
            inp.has_certificate = True
        v = _ref_value(session, meta, pv.value_ref, inner)
        if v in (None, "", []):
            inp.missing.append(path)
        else:
            inp.attrs[path] = v
    # options for select targets and outputs (classify, extract, restructure)
    for code in ([tpl.target_attribute] if tpl.target_attribute else []) + list(tpl.output_attributes or []):
        attr = meta.attributes.get(code or "")
        if attr is not None and attr.option_list_code and attr.data_type in ("single_select", "multi_select"):
            ol = meta.option_lists.get(attr.option_list_code)
            inp.options[code] = [{"code": o.code, "label": o.label} for o in (ol.values if ol else [])]
    # free text and documents (AI-05 extract)
    if text:
        inp.text = text.strip()
    if document:
        inp.text = (inp.text + "\n\n" + document_text(document)).strip()
    if inp.text:
        inp.attrs["input.text"] = inp.text
    # images: confirmed links for the template's shot types (approved images only)
    wanted = set(tpl.input_shot_types or [])
    sc = ent if ent.level == "style_color" else (session.get(ProductEntity, ent.parent_id) if ent.level == "sku" and ent.parent_id else None)
    if sc is not None and (wanted or image_asset_ids):
        links = session.execute(select(AssetLink).where(AssetLink.entity_id == sc.id, AssetLink.status == "confirmed")
                                .order_by(AssetLink.sort_order)).scalars().all()
        for lk in links:
            if image_asset_ids and lk.asset_id not in image_asset_ids:
                continue
            if not image_asset_ids and wanted and lk.shot_type not in wanted:
                continue
            url = lk.asset.thumbnail_url if lk.asset else None
            if url:
                inp.image_urls.append(url)
    inp.max_length = resolve_max_length(meta, tpl, ent, channel_code)
    return inp


def resolve_max_length(meta: Metadata, tpl: TemplateRow, ent: ProductEntity, channel_code: str) -> int | None:
    """Template limit, else the channel requirement's limit, else the attribute definition's limit (AI-02)."""
    if tpl.max_length:
        return tpl.max_length
    code = tpl.target_attribute
    attr = meta.attributes.get(code or "")
    if attr is None:
        return None
    chan = channel_code or tpl.channel_code
    if chan:
        rs = meta.requirement_set_for(chan, ent.family_code)
        for r in (rs.requirements if rs else []):
            if r.attribute_code == code and r.max_length:
                return r.max_length
    v = attr.validation or {}
    return int(v["max_length"]) if v.get("max_length") else None


def document_text(document: dict) -> str:
    """Text from an uploaded document. Plain text, CSV and Markdown decode directly; PDF uses pypdf when present,
    otherwise the Databricks `ai_parse_document` function is the production path (D28) and is reported as such."""
    name = str(document.get("name") or "document").lower()
    raw = base64.b64decode(document.get("content_base64") or "")
    if name.endswith((".txt", ".md", ".csv", ".tsv", ".json")):
        return raw.decode("utf-8", errors="replace")
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader  # optional

            reader = PdfReader(io.BytesIO(raw))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except ImportError:
            try:
                from pim.ai.documents import parse_with_databricks

                return parse_with_databricks(raw, name)
            except Exception as exc:  # noqa: BLE001
                raise AiTaskError(f"PDF parsing needs ai_parse_document on a SQL warehouse or pypdf installed: {exc}") from exc
    raise AiTaskError(f"Unsupported document type for {name}; upload PDF, TXT, CSV or MD")


# ---------------------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------------------
def render_prompt(tpl: TemplateRow, inp: TaskInputs) -> str:
    def options_block() -> str:
        lines = []
        for code, opts in inp.options.items():
            lines.append(f"Options for {code}: " + ", ".join(f"{o['code']} ({o['label']})" for o in opts[:80]))
        return "\n".join(lines)

    def repl(m: re.Match) -> str:
        kind, key = m.group(1), m.group(2)
        if kind == "attr":
            v = inp.attrs.get(key)
        elif kind == "core":
            v = inp.core.get(key)
        elif kind == "input":
            v = inp.text if key == "text" else None
        elif kind == "channel":
            v = inp.max_length if key == "max_length" else None
        else:
            v = None
        if v is None and kind == "channel" and key == "max_length":
            return "the attribute's"
        return "" if v is None else str(v)

    body = re.sub(r"\{\{\s*(attr|core|input|channel)\.([A-Za-z0-9_.]+)\s*\}\}", repl, tpl.body)
    body = body.replace("{{options}}", options_block())
    return body.strip()


# ---------------------------------------------------------------------------------------------------
# Diff and distance (AI-03, AI-07)
# ---------------------------------------------------------------------------------------------------
def _words(v: Any) -> list[str]:
    return re.findall(r"\S+|\s+", "" if v is None else str(v))


def word_diff(current: Any, proposed: Any) -> list[dict]:
    a, b = _words(current), _words(proposed)
    out: list[dict] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append({"op": "equal", "text": "".join(a[i1:i2])})
        else:
            if i2 > i1:
                out.append({"op": "delete", "text": "".join(a[i1:i2])})
            if j2 > j1:
                out.append({"op": "insert", "text": "".join(b[j1:j2])})
    return out


def edit_distance(a: Any, b: Any) -> float:
    """0 = identical, 1 = nothing in common (normalized, word level)."""
    wa, wb = [w for w in _words(a) if w.strip()], [w for w in _words(b) if w.strip()]
    if not wa and not wb:
        return 0.0
    return round(1 - difflib.SequenceMatcher(a=wa, b=wb, autojunk=False).ratio(), 4)


# ---------------------------------------------------------------------------------------------------
# Parsing per task type
# ---------------------------------------------------------------------------------------------------
def _json_block(text: str) -> Any:
    m = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _normalize_option(meta: Metadata, attr: AttributeDefinition, raw: Any) -> Any:
    """Accept a code or a label from the model and return the option code(s)."""
    ol = meta.option_lists.get(attr.option_list_code or "")
    if ol is None:
        return raw
    by_code = {o.code.lower(): o.code for o in ol.values}
    by_label = {o.label.lower(): o.code for o in ol.values}

    def one(x: Any) -> Any:
        s = str(x).strip().lower()
        return by_code.get(s) or by_label.get(s) or x

    if isinstance(raw, list):
        return [one(x) for x in raw]
    return one(raw)


def parse_output(meta: Metadata, tpl: TemplateRow, text: str) -> dict[str, Any]:
    """Returns {attribute_code: value} plus optional '_confidence' and '_findings' keys."""
    tt = tpl.task_type
    if tt in ("generate", "adapt", "expand"):
        return {tpl.target_attribute: text.strip().strip('"')}
    if tt == "classify":
        data = _json_block(text) or {}
        attr = meta.attributes.get(tpl.target_attribute or "")
        code = data.get("code") if isinstance(data, dict) else None
        if code is None:
            code = text.strip().split()[0].strip('".,') if text.strip() else None
        if attr is not None:
            code = _normalize_option(meta, attr, code)
        conf = data.get("confidence") if isinstance(data, dict) else None
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None  # "high" or similar: treated as unknown confidence, so the result is shown, not drafted
        return {tpl.target_attribute: code, "_confidence": conf_f}
    if tt == "check":
        data = _json_block(text) or {}
        findings = data.get("findings", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return {"_findings": [{"kind": f.get("kind", "other"), "message": f.get("message", ""), "severity": f.get("severity", "warning")}
                              for f in findings if isinstance(f, dict)]}
    if tt in ("extract", "restructure"):
        data = _json_block(text)
        if not isinstance(data, dict):
            raise AiTaskError("The model did not return JSON")
        out: dict[str, Any] = {}
        for code in tpl.output_attributes or []:
            attr = meta.attributes.get(code)
            key = code if code in data else ("model_note" if code == "model_profile" else None)
            if attr is None or key is None or data.get(key) in (None, "", []):
                continue
            v = data[key]
            if attr.data_type in ("single_select", "multi_select"):
                v = _normalize_option(meta, attr, v)
            elif isinstance(v, list):
                v = "\n".join(str(x) for x in v)
            if attr.data_type == "reference_entity":
                out[f"_note:{code}"] = v  # a model profile is linked by a person; keep the sentence as a finding
                continue
            out[code] = v
        return out
    raise AiTaskError(f"Unknown task type {tt}")


# ---------------------------------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------------------------------
def _log_event(session: Session):  # noqa: ANN202
    def _log(rec: dict) -> None:
        session.add(AppEvent(kind="ai_call", source="ai", user_email=rec.get("user"), payload=rec))

    return _log


def _current(session: Session, meta: Metadata, ent: ProductEntity, attr: AttributeDefinition, channel: str) -> Any:
    owner = _owner_for(session, ent, attr)
    if owner is None:
        return None
    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == owner.id, ProductValue.attribute_code == attr.code,
                                                    ProductValue.channel_code == channel)).scalar_one_or_none()
    if pv is None and channel:
        pv = session.execute(select(ProductValue).where(ProductValue.entity_id == owner.id, ProductValue.attribute_code == attr.code,
                                                        ProductValue.channel_code == "")).scalar_one_or_none()
    return typed_from_row(pv).as_python() if pv is not None else None


def run_task(session: Session, meta: Metadata, user: CurrentUser, ent: ProductEntity, tpl: TemplateRow, *,
             channel_code: str = "", text: str | None = None, document: dict | None = None,
             image_asset_ids: list[str] | None = None, run_id: str | None = None, service: AIService | None = None,
             inputs: TaskInputs | None = None) -> list[AiOutput]:
    """Run one template on one product. Returns the AiOutput rows (added to the session, not committed)."""
    if tpl.task_type not in TASK_TYPES:
        raise AiTaskError(f"Unsupported task type {tpl.task_type}")
    if tpl.task_type == "adapt" and not (channel_code or tpl.channel_code):
        raise AiTaskError("Adapt needs a channel")
    channel = channel_code or tpl.channel_code or ""
    if tpl.task_type != "adapt":
        channel = channel_code or ""
    inp = inputs or build_inputs(session, meta, user, ent, tpl, channel_code=channel, text=text, document=document, image_asset_ids=image_asset_ids)
    if tpl.accepts_text_input and not inp.text and not inp.image_urls and tpl.task_type == "extract" and not tpl.input_shot_types:
        raise AiTaskError("This template needs supplier text or a document")
    voice = voice_for(session, tpl.brand_code)
    prompt = render_prompt(tpl, inp)
    rt = RenderTemplate(code=tpl.code, version=str(tpl.version), task_type=tpl.task_type, target_attribute=tpl.target_attribute or "",
                        body=prompt, max_length=inp.max_length if tpl.task_type in ("generate", "adapt", "expand") else None)
    svc = service or AIService(logger=_log_event(session))
    facts = {**{f"core.{k}": v for k, v in inp.core.items() if v not in (None, "")}, **inp.attrs}
    outputs: list[AiOutput] = []
    base = dict(run_id=run_id, entity_id=ent.id, channel_code=channel, task_type=tpl.task_type, template_code=tpl.code,
                template_version=tpl.version, created_by=user.email,
                inputs={"text": inp.text or None, "image_asset_ids": list(image_asset_ids or [])})
    try:
        res = svc.run(rt, voice, facts, product_id=ent.id, image_urls=inp.image_urls, has_certificate=inp.has_certificate,
                      user_email=user.email, vision=bool(inp.image_urls) and tpl.model_task == "classify",
                      grounded=tpl.task_type not in STRUCTURED,
                      endpoint=svc.endpoints.get(tpl.model_task), temperature=0.0 if tpl.task_type in STRUCTURED else 0.3)
    except NotConfigured:
        raise
    except Exception as exc:  # noqa: BLE001
        o = AiOutput(**base, attribute_code=tpl.target_attribute or (tpl.output_attributes or ["_"])[0], status="failed",
                     grounding_errors=[f"AI call failed: {str(exc)[:300]}"], model=svc.endpoints.get(tpl.model_task, ""))
        session.add(o)
        return [o]
    usage = dict(model=res.model, prompt_tokens=res.prompt_tokens, completion_tokens=res.completion_tokens,
                 latency_ms=int(res.raw.get("latency_ms", 0)), raw_text=res.text[:8000])
    if res.needs_input:
        o = AiOutput(**base, **usage, attribute_code=tpl.target_attribute or (tpl.output_attributes or ["_"])[0], status="needs_input",
                     needs_input=res.needs_input, grounding_errors=res.grounding_errors)
        session.add(o)
        return [o]
    try:
        parsed = parse_output(meta, tpl, res.text)
    except (AiTaskError, ValueError, TypeError, AttributeError) as exc:
        o = AiOutput(**base, **usage, attribute_code=tpl.target_attribute or (tpl.output_attributes or ["_"])[0], status="failed",
                     grounding_errors=[str(exc)])
        session.add(o)
        return [o]
    if tpl.task_type == "check":
        o = AiOutput(**base, **usage, attribute_code=tpl.target_attribute or "_", status="info", check_findings=parsed.get("_findings", []),
                     current_value={"value": _current(session, meta, ent, meta.attributes[tpl.target_attribute], channel)} if tpl.target_attribute in meta.attributes else {})
        session.add(o)
        return [o]
    confidence = parsed.pop("_confidence", None)
    notes = {k[6:]: v for k, v in list(parsed.items()) if k.startswith("_note:")}
    for k in list(parsed):
        if k.startswith("_"):
            parsed.pop(k)
    threshold = get_settings().ai_classify_confidence_threshold
    for code, value in parsed.items():
        attr = meta.attributes.get(code)
        if attr is None:
            continue
        owner = _owner_for(session, ent, attr)
        current = _current(session, meta, ent, attr, channel)
        o = AiOutput(**base, **usage, attribute_code=code, confidence=confidence, proposed_value={"value": value},
                     current_value={"value": current}, grounding_errors=list(res.grounding_errors))
        if owner is None:
            o.status, o.grounding_errors = "failed", [f"{attr.label} has no owner entity at level {attr.level}"]
        elif res.grounding_errors:
            o.status = "failed"
        else:
            try:
                coerce(meta, attr, value)
            except ValueError_ as exc:
                o.status, o.grounding_errors = "failed", [str(exc)]
            else:
                if tpl.task_type == "classify" and (confidence is None or confidence < threshold):
                    o.status = "info"  # shown with its confidence; a person decides whether to draft it
                elif current == value or (isinstance(current, str) and isinstance(value, str) and current.strip() == value.strip()):
                    o.status = "info"
                    o.grounding_errors = ["Same as the current value"]
                else:
                    draft = _open_draft(session, owner, attr, channel, value, user, run_id)
                    if draft is None:
                        o.status = "info"
                        o.grounding_errors = ["A person's draft is pending on this attribute; decide it in Approvals before applying an AI suggestion"]
                    else:
                        o.draft_id = draft.id
        session.add(o)
        outputs.append(o)
    for code, note in notes.items():
        o = AiOutput(**base, **usage, attribute_code=code, status="info", proposed_value={"value": note}, current_value={},
                     check_findings=[{"kind": "model_profile", "message": f"Link the model profile by hand: {note}", "severity": "warning"}])
        session.add(o)
        outputs.append(o)
    if not outputs:
        o = AiOutput(**base, **usage, attribute_code=tpl.target_attribute or (tpl.output_attributes or ["_"])[0], status="info",
                     grounding_errors=["The model returned nothing usable for the requested attributes"])
        session.add(o)
        outputs.append(o)
    session.flush()
    return outputs


def _open_draft(session: Session, owner: ProductEntity, attr: AttributeDefinition, channel: str, value: Any, user: CurrentUser,
                run_id: str | None) -> ValueDraft | None:
    """One open draft per entity, attribute and channel. A newer AI suggestion replaces the previous AI draft (and
    the outputs that pointed at it are marked superseded); a person's pending draft is never touched (P4), so the
    caller gets None and reports the suggestion as information only."""
    existing = session.execute(select(ValueDraft).where(ValueDraft.entity_id == owner.id, ValueDraft.attribute_code == attr.code,
                                                        ValueDraft.channel_code == channel, ValueDraft.state.in_(["draft", "proposed"]))).scalars().first()
    if existing is not None:
        if not existing.ai_generated:
            return None
        for old in session.execute(select(AiOutput).where(AiOutput.draft_id == existing.id, AiOutput.status.in_(["proposed", "edited"]))).scalars():
            old.status, old.rejection_reason, old.decided_by, old.decided_at = "rejected", "superseded", user.email, utcnow()
        existing.proposed, existing.submitted_by, existing.submitted_at, existing.ai_run_id = {"value": value, "not_applicable": False}, user.email, utcnow(), run_id
        existing.state = "proposed"
        return existing
    d = ValueDraft(entity_level=owner.level, entity_id=owner.id, attribute_code=attr.code, channel_code=channel,
                   proposed={"value": value, "not_applicable": False}, source_type="ai", ai_generated=True, ai_run_id=run_id,
                   submitted_by=user.email, state="proposed")
    session.add(d)
    session.flush()
    return d


# ---------------------------------------------------------------------------------------------------
# Decisions (AI-03) and metrics (AI-07)
# ---------------------------------------------------------------------------------------------------
def accept_output(session: Session, meta: Metadata, user: CurrentUser, o: AiOutput, value: Any = None) -> AiOutput:
    if o.status not in ("proposed", "edited") or not o.draft_id:
        raise AiTaskError("Only an open suggestion can be accepted")
    draft = session.get(ValueDraft, o.draft_id)
    if draft is None or draft.state not in ("draft", "proposed"):
        raise AiTaskError("The suggestion's draft is no longer open")
    attr = meta.attributes[o.attribute_code]
    final = o.proposed_value.get("value") if value is None else value
    if value is not None:
        try:
            coerce(meta, attr, value)
        except ValueError_ as exc:
            raise AiTaskError(str(exc)) from exc
        draft.proposed = {"value": value, "not_applicable": False}
    o.final_value = {"value": final}
    o.edit_distance = edit_distance(o.proposed_value.get("value"), final)
    o.decided_by, o.decided_at = user.email, utcnow()
    if user.can_approve_group(attr.group_code):
        res = decide_drafts(session, meta, user, [draft.id], "approve", "accepted from Ask AI")
        if res and res[0].outcome in ("approved", "unchanged"):
            o.status = "edited" if value is not None and o.edit_distance else "accepted"
        else:
            raise AiTaskError(res[0].message if res else "Approval failed")
    else:
        o.status = "edited" if value is not None else "proposed"  # stays in the approval queue (DM-08)
    return o


def reject_output(session: Session, user: CurrentUser, o: AiOutput, reason: str) -> AiOutput:
    if o.status in ("accepted", "rejected"):
        raise AiTaskError("This suggestion was already decided")
    if o.draft_id:
        d = session.get(ValueDraft, o.draft_id)
        if d is not None and d.state in ("draft", "proposed"):
            d.state, d.decided_by, d.decided_at, d.comment = "rejected", user.email, utcnow(), reason
    o.status, o.rejection_reason, o.decided_by, o.decided_at = "rejected", reason.strip()[:500], user.email, utcnow()
    return o


def metrics(session: Session, template_code: str | None = None) -> list[dict]:
    q = select(AiOutput).where(AiOutput.status.in_(["proposed", "accepted", "edited", "rejected"]))
    if template_code:
        q = q.where(AiOutput.template_code == template_code)
    rows = session.execute(q).scalars().all()
    groups: dict[tuple, list[AiOutput]] = {}
    for o in rows:
        key = (o.template_code, o.template_version if template_code else None)
        groups.setdefault(key, []).append(o)
    out = []
    for (code, ver), items in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
        acc = [o for o in items if o.status in ("accepted", "edited")]
        rej = [o for o in items if o.status == "rejected" and o.rejection_reason != "regenerated"]
        decided = len(acc) + len(rej)
        dists = [o.edit_distance for o in acc if o.edit_distance is not None]
        reasons: dict[str, int] = {}
        for o in rej:
            reasons[o.rejection_reason or "unspecified"] = reasons.get(o.rejection_reason or "unspecified", 0) + 1
        out.append({"template_code": code, "template_version": ver, "outputs": len(items), "accepted": len([o for o in acc if o.status == "accepted"]),
                    "edited": len([o for o in acc if o.status == "edited"]), "rejected": len(rej),
                    "pending": len([o for o in items if o.status == "proposed"]),
                    "acceptance_rate": round(len(acc) / decided, 3) if decided else None,
                    "mean_edit_distance": round(sum(dists) / len(dists), 3) if dists else None,
                    "rejection_reasons": [{"reason": r, "count": c} for r, c in sorted(reasons.items(), key=lambda x: -x[1])],
                    "tokens": {"prompt": sum(o.prompt_tokens for o in items), "completion": sum(o.completion_tokens for o in items)}})
    return out


# ---------------------------------------------------------------------------------------------------
# Bulk runs (AI-04)
# ---------------------------------------------------------------------------------------------------
SAMPLE_SIZE = 5


def start_bulk(session: Session, meta: Metadata, user: CurrentUser, tpl: TemplateRow, entities: list[ProductEntity],
               selection: dict, channel_code: str = "", service: AIService | None = None) -> tuple[AiRun, list[AiOutput]]:
    run = AiRun(kind="bulk", template_code=tpl.code, template_version=tpl.version, task_type=tpl.task_type, channel_code=channel_code or "",
                selection=selection, entity_ids=[e.id for e in entities], sample_entity_ids=[e.id for e in entities[:SAMPLE_SIZE]],
                status="sample_pending", total=len(entities), created_by=user.email)
    session.add(run)
    session.flush()
    outputs: list[AiOutput] = []
    for ent in entities[:SAMPLE_SIZE]:
        outs = run_task(session, meta, user, ent, tpl, channel_code=channel_code, run_id=run.id, service=service)
        outputs.extend(outs)
        _count(run, outs)
    run.done = min(SAMPLE_SIZE, len(entities))
    if len(entities) <= SAMPLE_SIZE:
        run.status, run.finished_at = "completed", utcnow()
    return run, outputs


def _count(run: AiRun, outs: list[AiOutput]) -> None:
    for o in outs:
        if o.status == "proposed":
            run.proposed += 1
        elif o.status == "failed":
            run.failed += 1
        elif o.status == "needs_input":
            run.needs_input += 1


def continue_bulk(session: Session, meta: Metadata, user: CurrentUser, run: AiRun, service: AIService | None = None,
                  batch: int = 50) -> AiRun:
    """Process the products after the samples; commits per batch so progress is visible and a cancel is honored."""
    tpl = session.get(TemplateRow, run.template_code)
    if tpl is None:
        run.status, run.error = "failed", "Template no longer exists"
        return run
    run.status = "running"
    session.commit()
    remaining = [eid for eid in run.entity_ids if eid not in set(run.sample_entity_ids)]
    for i in range(0, len(remaining), batch):
        session.refresh(run)
        if run.status == "cancelled":
            return run
        ents = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_(remaining[i:i + batch]))).scalars()}
        for eid in remaining[i:i + batch]:
            ent = ents.get(eid)
            if ent is None:
                run.failed += 1
                continue
            try:
                outs = run_task(session, meta, user, ent, tpl, channel_code=run.channel_code, run_id=run.id, service=service)
                _count(run, outs)
            except NotConfigured as exc:
                run.status, run.error, run.finished_at = "failed", str(exc), utcnow()
                session.commit()
                return run
            except Exception as exc:  # noqa: BLE001  one bad product never stops the run
                log.exception("bulk AI failed for %s", eid)
                run.failed += 1
                run.report = {**(run.report or {}), "last_error": str(exc)[:300]}
            run.done += 1
        session.commit()
    run.status, run.finished_at = "completed", utcnow()
    session.commit()
    return run


def accept_all(session: Session, meta: Metadata, user: CurrentUser, run: AiRun) -> dict[str, int]:
    outs = session.execute(select(AiOutput).where(AiOutput.run_id == run.id, AiOutput.status == "proposed")).scalars().all()
    accepted = skipped = 0
    for o in outs:
        attr = meta.attributes.get(o.attribute_code)
        if attr is None or not user.can_approve_group(attr.group_code) or not o.draft_id:
            skipped += 1
            continue
        try:
            accept_output(session, meta, user, o)
            accepted += 1
        except AiTaskError:
            skipped += 1
    return {"accepted": accepted, "skipped": skipped}


def user_for_job(session: Session, email: str) -> CurrentUser:
    """The job runs as the person who started the run, with their roles and brand scopes (RBAC-01, RBAC-04)."""
    from pim.auth.identity import build_user
    from pim.models import UserRole

    rows = session.execute(select(UserRole).where(UserRole.email == email.lower())).scalars().all()
    roles = [r.role_code for r in rows] or ["pim_admin"]
    scopes = sorted({sc for r in rows for sc in (r.brand_scopes or [])})
    return build_user(email, None, roles, scopes, session)


def output_out(o: AiOutput, label: str) -> dict:
    cur, prop = o.current_value.get("value") if o.current_value else None, o.proposed_value.get("value") if o.proposed_value else None
    return {"id": o.id, "run_id": o.run_id, "entity_id": o.entity_id, "label": label, "attribute_code": o.attribute_code,
            "channel_code": o.channel_code or "", "task_type": o.task_type, "template_code": o.template_code,
            "template_version": o.template_version, "model": o.model, "status": o.status, "proposed_value": prop, "current_value": cur,
            "final_value": (o.final_value or {}).get("value") if o.final_value else None,
            "diff": word_diff(cur, prop) if isinstance(prop, (str, int, float)) or prop is None else [],
            "draft_id": o.draft_id, "confidence": o.confidence, "needs_input": o.needs_input or [], "grounding_errors": o.grounding_errors or [],
            "check_findings": o.check_findings or [], "rejection_reason": o.rejection_reason, "edit_distance": o.edit_distance,
            "prompt_tokens": o.prompt_tokens, "completion_tokens": o.completion_tokens, "latency_ms": o.latency_ms,
            "created_by": o.created_by, "created_at": o.created_at.isoformat(), "inputs": o.inputs or {},
            "decided_by": o.decided_by, "decided_at": o.decided_at.isoformat() if o.decided_at else None}


def run_out(r: AiRun) -> dict:
    return {"id": r.id, "kind": r.kind, "template_code": r.template_code, "template_version": r.template_version, "task_type": r.task_type,
            "channel_code": r.channel_code or "", "selection": r.selection or {}, "status": r.status, "sample_entity_ids": r.sample_entity_ids or [],
            "total": r.total, "done": r.done, "proposed": r.proposed, "failed": r.failed, "needs_input": r.needs_input,
            "created_by": r.created_by, "created_at": r.created_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "job_run_id": r.job_run_id, "error": r.error, "report": r.report or {}}
