"""EXP-04 channel payloads: build one payload per style-color from the channel mapping (EXP-01), apply the
channel transforms, add channel images (IMG-07 renditions when present), then validate against the loaded target
schema (EXP-02) before anything is sent. Every issue carries the entity, the target field and, where it maps back,
our attribute code so the UI can link the fix (F10).

Payload values come only from approved values (P4); drafts, unconfirmed defaults and rejected values never reach
a channel. Channel overrides (channel_code = channel) win over global values.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from pim.export.schema_loaders import TargetField, TargetSchema
from pim.export.shopify_package import CLEAR, _display_value
from pim.models import AssetLink, Channel, ProductEntity, ProductValue
from pim.services.metadata import Metadata
from pim.services.rules import eval_condition

log = logging.getLogger(__name__)

CORE_FIELDS = ("style_number", "color_code", "size", "sku", "upc", "label", "lifecycle_status", "family_code", "entity_type")
UNIT_FACTORS = {("in", "cm"): 2.54, ("cm", "in"): 1 / 2.54, ("oz", "g"): 28.3495, ("g", "oz"): 1 / 28.3495,
                ("lb", "kg"): 0.453592, ("kg", "lb"): 1 / 0.453592, ("mm", "in"): 1 / 25.4, ("in", "mm"): 25.4}


@dataclass
class PayloadIssue:
    entity_id: str
    label: str
    message: str
    kind: str  # missing_required | invalid_type | enum | length | schema | transform | image
    severity: str = "error"
    field: str | None = None
    attribute_code: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProductPayload:
    entity_id: str
    label: str
    external_id: str | None
    data: dict[str, Any] = field(default_factory=dict)
    images: list[dict] = field(default_factory=list)
    issues: list[PayloadIssue] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)  # target field -> attribute code (for feedback mapping)
    variants: list[dict] = field(default_factory=list)  # EXP-09 one row per SKU: {sku, upc, size, nrf_size}
    feed: dict[str, Any] = field(default_factory=dict)  # EXP-09 feed column header -> value (style-color level)

    @property
    def valid(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)


# ---------------------------------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------------------------------
def load_entity_values(session: Session, entities: list[ProductEntity]) -> tuple[dict[str, dict[tuple[str, str], ProductValue]], dict[str, ProductEntity]]:
    styles = {s.id: s for s in session.execute(select(ProductEntity).where(
        ProductEntity.id.in_({e.parent_id for e in entities if e.parent_id}))).scalars()} if entities else {}
    ids = [e.id for e in entities] + list(styles)
    values: dict[str, dict[tuple[str, str], ProductValue]] = {}
    if ids:
        for pv in session.execute(select(ProductValue).where(ProductValue.entity_id.in_(ids))).scalars():
            values.setdefault(pv.entity_id, {})[(pv.attribute_code, pv.channel_code)] = pv
    return values, styles


def merged_values(values: dict[str, dict], ent: ProductEntity, style: ProductEntity | None) -> dict[tuple[str, str], ProductValue]:
    merged = dict(values.get(style.id, {}) if style else {})
    merged.update(values.get(ent.id, {}))
    return merged


def _core(ent: ProductEntity, style: ProductEntity | None, name: str) -> Any:
    if name in ("style_number", "color_code", "size", "sku", "upc", "label", "lifecycle_status", "family_code", "entity_type"):
        v = getattr(ent, name, None)
        if v in (None, "") and style is not None:
            v = getattr(style, name, None)
        return v
    erp = (ent.erp_fields or {}) or (style.erp_fields if style else {}) or {}
    return erp.get(name)


RefValues = dict[tuple[str, str], ProductValue]  # (reference entity id, attribute code) -> global value


def load_ref_values(session: Session, meta: Metadata, values: dict[str, dict[tuple[str, str], ProductValue]]) -> RefValues:
    """One query for every referenced entity's values (fabric.*, print.*) instead of a lookup per product and path."""
    ref_ids: set[str] = set()
    for per_entity in values.values():
        for (code, _ch), pv in per_entity.items():
            attr = meta.attributes.get(code)
            if attr is not None and attr.data_type == "reference_entity" and pv.value_ref:
                ref_ids.add(pv.value_ref)
    out: RefValues = {}
    if ref_ids:
        for pv in session.execute(select(ProductValue).where(ProductValue.entity_id.in_(ref_ids), ProductValue.channel_code == "")).scalars():
            out[(pv.entity_id, pv.attribute_code)] = pv
    return out


def ready_value(meta: Metadata, merged: dict[tuple[str, str], ProductValue], path: str, channel_code: str,
                refs: RefValues) -> tuple[Any, ProductValue | None]:
    """Same rules as shopify_package._channel_ready_value (approved only, no unconfirmed defaults, channel override
    wins) without per-call queries: reference paths resolve through the preloaded `refs`."""
    code, _, inner = path.partition(".")
    pv = merged.get((code, channel_code)) or merged.get((code, ""))
    if pv is None or pv.approval_state != "approved" or (pv.source_type == "default" and not pv.confirmed_default):
        return None, pv
    if pv.not_applicable:
        return CLEAR, pv
    if inner:
        if not pv.value_ref:
            return None, pv
        inner_pv = refs.get((pv.value_ref, inner))
        if inner_pv is None:
            return None, pv
        return _display_value(meta, inner, inner_pv), inner_pv
    return _display_value(meta, code, pv), pv


def resolve_source(meta: Metadata, channel: Channel, ent: ProductEntity, style: ProductEntity | None,
                   merged: dict[tuple[str, str], ProductValue], source: str, refs: RefValues) -> tuple[Any, str | None]:
    """A mapping source is `attr`, `ref_attr.inner`, `core.<field>` or `erp.<field>`. Returns (value, attribute_code)."""
    if source.startswith("core.") or source.startswith("erp."):
        return _core(ent, style, source.split(".", 1)[1]), None
    if source in CORE_FIELDS and source not in meta.attributes:
        return _core(ent, style, source), None
    v, pv = ready_value(meta, merged, source, channel.code, refs)
    if v is CLEAR:
        return None, source.split(".", 1)[0]
    attr = meta.attributes.get(source.rsplit(".", 1)[-1]) if "." in source else meta.attributes.get(source)
    if attr is not None and pv is not None and attr.data_type in ("single_select", "multi_select") and attr.option_list_code:
        v = _channel_option_value(meta, attr, pv, channel.code, v)
    return v, source.split(".", 1)[0]


def _channel_option_value(meta: Metadata, attr, pv: ProductValue, channel_code: str, fallback: Any) -> Any:  # noqa: ANN001
    """DM-14: an option value can carry the retailer's own wording per channel; the label is the default."""
    from pim.services.values import typed_from_row

    t = typed_from_row(pv)
    ol = meta.option_lists.get(attr.option_list_code)
    if ol is None:
        return fallback
    by_code = {o.code: o for o in ol.values}

    def one(code: str | None) -> Any:
        o = by_code.get(code or "")
        if o is None:
            return code
        return (o.channel_mappings or {}).get(channel_code) or o.label or code

    if attr.data_type == "single_select":
        return one(t.text)
    if isinstance(t.json, list):
        return [one(c) for c in t.json]
    return fallback


# ---------------------------------------------------------------------------------------------------
# Transforms (EXP-01 transformation rules)
# ---------------------------------------------------------------------------------------------------
def _tmpl(template: str, data: dict[str, Any], flat: dict[str, Any]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        v = flat.get(key.removeprefix("attr."), data.get(key))
        return "" if v is None else str(v)

    return re.sub(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}", repl, template)


def apply_transform(tr: dict, data: dict[str, Any], flat: dict[str, Any], ent: ProductEntity) -> tuple[Any, str | None]:
    """Returns (new value for tr['target'], error message or None)."""
    op, args, target = tr.get("op"), tr.get("args") or {}, tr.get("target")
    cur = data.get(target)
    try:
        if op == "concatenate":
            parts = [flat.get(p.removeprefix("attr."), data.get(p)) for p in args.get("parts", [])]
            return (args.get("separator", " ")).join(str(p) for p in parts if p not in (None, "")), None
        if op == "format":
            return _tmpl(str(args.get("template", "")), data, flat), None
        if op == "unit_convert":
            if cur in (None, ""):
                return cur, None
            factor = UNIT_FACTORS.get((str(args.get("from", "")).lower(), str(args.get("to", "")).lower()))
            if factor is None:
                return cur, f"unknown unit conversion {args.get('from')} to {args.get('to')}"
            return round(float(cur) * factor, int(args.get("precision", 2))), None
        if op == "conditional":
            hit = eval_condition(args.get("when") or {}, ent, flat)
            chosen = args.get("then") if hit else args.get("else", cur)
            return (_tmpl(chosen, data, flat) if isinstance(chosen, str) and "{{" in chosen else chosen), None
        if op == "case":
            from pim.adapters.feed_file import transform_case

            return transform_case(None if cur is None else str(cur), str(args.get("mode", "as_is"))), None
        if op == "truncate":
            n = int(args.get("max_length", 0))
            if cur is None or n <= 0:
                return cur, None
            s = str(cur)
            return (s[: n - 1].rstrip() + ("…" if args.get("ellipsis") else "")) if len(s) > n and args.get("ellipsis") else s[:n], None
        if op == "value_map":
            m = args.get("map") or {}
            return m.get(str(cur), cur), None
        return cur, f"unknown transform op {op!r}"
    except (TypeError, ValueError) as exc:
        return cur, f"transform {op} failed: {exc}"


# ---------------------------------------------------------------------------------------------------
# Validation against the target schema
# ---------------------------------------------------------------------------------------------------
_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def _type_ok(f: TargetField, v: Any) -> bool:
    if v is None:
        return True
    t = f.type
    if t == "string" or t == "enum":
        return isinstance(v, (str, int, float))
    if t == "integer":
        return (isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, str) and v.strip().lstrip("-").isdigit())
    if t == "number":
        return (isinstance(v, (int, float)) and not isinstance(v, bool)) or (isinstance(v, str) and bool(_NUM.match(v.strip())))
    if t == "boolean":
        return isinstance(v, bool) or str(v).lower() in ("true", "false", "yes", "no", "1", "0")
    if t == "array":
        return isinstance(v, (list, tuple))
    if t == "object":
        return isinstance(v, dict)
    if t == "date":
        if isinstance(v, (date, datetime)):
            return True
        try:
            datetime.fromisoformat(str(v))
            return True
        except ValueError:
            return False
    return True


def validate_payload(p: ProductPayload, schema: TargetSchema | None, channel: Channel, raw_schema: dict | None = None) -> None:
    if schema is None or not schema.fields:
        return
    for f in schema.fields:
        v = p.data.get(f.name)
        attr = p.sources.get(f.name)
        if f.required and (v is None or v == "" or v == []):
            p.issues.append(PayloadIssue(p.entity_id, p.label, f"{f.name} is required by the channel", "missing_required",
                                         field=f.name, attribute_code=attr))
            continue
        if v is None:
            continue
        if not _type_ok(f, v):
            p.issues.append(PayloadIssue(p.entity_id, p.label, f"{f.name} must be {f.type}, got {type(v).__name__}", "invalid_type",
                                         field=f.name, attribute_code=attr))
            continue
        if f.enum:
            vals = v if isinstance(v, list) else [v]
            bad = [str(x) for x in vals if str(x) not in f.enum]
            if bad:
                p.issues.append(PayloadIssue(p.entity_id, p.label, f"{f.name} value {bad[0]!r} is not in the channel's list",
                                             "enum", field=f.name, attribute_code=attr))
        if f.max_length and isinstance(v, str) and len(v) > f.max_length:
            p.issues.append(PayloadIssue(p.entity_id, p.label, f"{f.name} exceeds {f.max_length} characters ({len(v)})", "length",
                                         field=f.name, attribute_code=attr))
        if f.type in ("number", "integer") and (f.min is not None or f.max is not None):
            try:
                n = float(v)
                if f.min is not None and n < f.min or f.max is not None and n > f.max:
                    p.issues.append(PayloadIssue(p.entity_id, p.label, f"{f.name} is outside {f.min} to {f.max}", "schema",
                                                 field=f.name, attribute_code=attr))
            except (TypeError, ValueError):
                pass
    if raw_schema and schema.source == "walmart_spec":
        _validate_jsonschema(p, schema, raw_schema)


def validate_feed(channel: Channel, payloads: list[ProductPayload]) -> None:
    """EXP-09 required feed columns per row and the Rithum program rules (Target+ family as a unit)."""
    rows, cols = feed_rows(channel, payloads)
    if not cols:
        return
    adapter = feed_adapter_for(channel)
    by_entity = {p.entity_id: p for p in payloads}
    required = [c for c in adapter.columns if c.required]
    for r in rows:
        p = by_entity.get(r.get("_entity_id"))
        if p is None:
            continue
        for c in required:
            if r.get(c.header) in (None, "", []):
                src = next((fc.get("source") for fc in cols if fc.get("header") == c.header), None)
                if not any(i.field == c.header and i.kind == "missing_required" for i in p.issues):
                    p.issues.append(PayloadIssue(p.entity_id, p.label, f"{c.header} is required by the feed", "missing_required", field=c.header,
                                                 attribute_code=p.sources.get(c.header) or (src if src in p.sources.values() else None)))
    if getattr(adapter, "family_rules", False):
        keyed = []
        for r in rows:
            p = by_entity.get(r.get("_entity_id"))
            img = (p.images[0] if p and p.images else {}) or {}
            keyed.append({"core.style_number": r.get(next((c["header"] for c in cols if c.get("source") == "core.style_number"), ""), None),
                          "core.sku": r.get(next((c["header"] for c in cols if c.get("source") == "core.sku"), ""), None),
                          "product_title": r.get(next((c["header"] for c in cols if c.get("source") == "product_title"), ""), None),
                          "gtin": r.get(next((c["header"] for c in cols if c.get("source") in ("gtin", "core.upc")), ""), None),
                          "image_width": img.get("width"), "image_height": img.get("height"), "_entity_id": r.get("_entity_id")})
        for err in adapter._family_errors(keyed):
            for p in payloads:
                if (p.feed.get(next((c["header"] for c in cols if c.get("source") == "core.style_number"), "")) or "") == err["family"] or any(
                        d.startswith(str(v.get("sku"))) for v in p.variants for d in err.get("details", [])):
                    if not any(i.kind == "schema" and i.message == err["message"] for i in p.issues):
                        p.issues.append(PayloadIssue(p.entity_id, p.label, err["message"] + ": " + "; ".join(err.get("details", [])[:3]), "schema"))


def load_raw_schema(channel: Channel) -> dict | None:
    """The Walmart spec is kept on the volume (config.raw_schema_path); load it once per run."""
    cfg = channel.config or {}
    if isinstance(cfg.get("raw_schema"), dict):
        return cfg["raw_schema"]
    path = cfg.get("raw_schema_path")
    if not path:
        return None
    try:
        from pim.export.publishing import storage

        return json.loads(storage().read(path).decode("utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        log.warning("raw schema for %s could not be loaded from %s: %s", channel.code, path, exc)
        return None


def _validate_jsonschema(p: ProductPayload, schema: TargetSchema, raw: dict) -> None:
    """Walmart publishes real JSON Schema; the item is validated as the nested MPItem the spec describes."""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        return
    item = nest(p.data, schema)
    item_schema = raw
    props = raw.get("properties") or {}
    if "MPItem" in props:  # validate one item against the MPItem item schema, not the feed envelope
        item_schema = {"$schema": raw.get("$schema", "http://json-schema.org/draft-07/schema#"), **(props["MPItem"].get("items") or {})}
    try:
        validator = jsonschema.Draft7Validator(item_schema)
        errors = list(validator.iter_errors(item))
    except jsonschema.exceptions.SchemaError as exc:  # noqa: BLE001
        log.warning("Walmart spec is not a usable JSON Schema: %s", exc)
        return
    seen = {i.field for i in p.issues if i.field}
    for err in errors:
        path = "/".join(str(x) for x in err.absolute_path)
        if err.validator == "required":  # report each missing property under its own name, like the flat check
            present = err.instance if isinstance(err.instance, dict) else {}
            for name in err.validator_value or []:
                if name not in present and name not in seen:
                    seen.add(name)
                    p.issues.append(PayloadIssue(p.entity_id, p.label, f"{name} is required by the channel spec", "missing_required",
                                                 field=name, attribute_code=p.sources.get(name)))
            continue
        leaf = str(err.absolute_path[-1]) if err.absolute_path else (path or None)
        key = f"{leaf}:{err.validator}"
        if key in seen:
            continue
        seen.add(key)
        p.issues.append(PayloadIssue(p.entity_id, p.label, err.message[:300], "schema", field=leaf, attribute_code=p.sources.get(leaf or "")))


def nest(flat: dict[str, Any], schema: TargetSchema | None = None) -> dict[str, Any]:
    """Builds the nested object API channels expect. A field whose schema entry carries a JSON pointer `path`
    (Walmart: /Orderable/sku, /Visible/Swimwear/productName) lands there; otherwise `/a/b` or `a.b` keys nest
    by their own segments and plain names stay at the root."""
    paths = {f.name: f.path for f in (schema.fields if schema else []) if f.path}
    out: dict[str, Any] = {}
    for k, v in flat.items():
        key = paths.get(k, k)
        parts = [x for x in re.split(r"[/.]", key) if x] if (key.startswith("/") or "." in key) else [key]
        cur = out
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = v
    return out


# ---------------------------------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------------------------------
def build_payloads(session: Session, meta: Metadata, channel: Channel, entities: list[ProductEntity],
                   schema: TargetSchema | None = None, renditions: dict[str, list[dict]] | None = None) -> list[ProductPayload]:
    schema = schema or TargetSchema.from_dict(channel.target_schema)
    values, styles = load_entity_values(session, entities)
    refs = load_ref_values(session, meta, values)
    raw_schema = load_raw_schema(channel) if schema.source == "walmart_spec" else None
    links: dict[str, list[AssetLink]] = {}
    if entities:
        for lk in session.execute(select(AssetLink).options(selectinload(AssetLink.asset))
                                  .where(AssetLink.entity_id.in_([e.id for e in entities]), AssetLink.status == "confirmed")
                                  .order_by(AssetLink.sort_order)).scalars():
            links.setdefault(lk.entity_id, []).append(lk)
    mapping: dict[str, str] = channel.attribute_mapping or {}
    out: list[ProductPayload] = []
    profile = channel.image_profile or {}
    wanted_shots = profile.get("shot_types") or []
    feed_cols: list[dict] = default_feed_columns(channel)
    variants_by_parent: dict[str, list[dict]] = {}
    if feed_cols and entities:
        size_attr = next((a for a in meta.attributes.values() if a.code == "size_scale"), None)
        for sku in session.execute(select(ProductEntity).where(ProductEntity.parent_id.in_([e.id for e in entities]),
                                                               ProductEntity.level == "sku").order_by(ProductEntity.sku)).scalars():
            nrf_size = None
            if sku.size:
                for lst in meta.option_lists.values():
                    if lst.kind == "size_scale":
                        opt = next((o for o in lst.values if o.code.upper() == str(sku.size).upper()), None)
                        if opt is not None:
                            from pim.adapters.rithum import nrf_code

                            nrf_size = nrf_code(opt, "size")
                            break
            variants_by_parent.setdefault(sku.parent_id, []).append({"sku": sku.sku, "upc": sku.upc, "size": sku.size, "nrf_size": nrf_size,
                                                                       "entity_id": sku.id})
        _ = size_attr
    for ent in entities:
        style = styles.get(ent.parent_id or "")
        merged = merged_values(values, ent, style)
        p = ProductPayload(entity_id=ent.id, label=ent.label, external_id=_external_id(ent, style, channel))
        flat: dict[str, Any] = {name: _core(ent, style, name) for name in CORE_FIELDS}
        for (code, ch), pv in merged.items():
            if ch in ("", channel.code) and pv.approval_state == "approved":
                v, _ = ready_value(meta, merged, code, channel.code, refs)
                flat[code] = None if v is CLEAR else v
        for source, target in mapping.items():
            if not target:
                continue
            v, attr = resolve_source(meta, channel, ent, style, merged, source, refs)
            p.data[target] = v
            if attr:
                p.sources[target] = attr
        for tr in channel.transforms or []:
            target = tr.get("target")
            if not target:
                continue
            v, err = apply_transform(tr, p.data, flat, ent)
            p.data[target] = v
            if err:
                p.issues.append(PayloadIssue(ent.id, ent.label, err, "transform", field=target, attribute_code=p.sources.get(target)))
        for lk in links.get(ent.id, []):
            if wanted_shots and lk.shot_type not in wanted_shots:
                continue
            rend = next((r for r in (renditions or {}).get(lk.asset_id, []) if r.get("channel_code") == channel.code), None)
            p.images.append({"asset_id": lk.asset_id, "shot_type": lk.shot_type, "sort_order": lk.sort_order,
                             "url": (rend or {}).get("url") or (lk.asset.thumbnail_url if lk.asset else None),
                             "rendition": bool(rend), "ai_generated": bool(lk.asset and lk.asset.ai_generated_image),
                             "width": (rend or {}).get("width") or (lk.asset.width if lk.asset else None),
                             "height": (rend or {}).get("height") or (lk.asset.height if lk.asset else None)})
        if wanted_shots and not p.images:
            p.issues.append(PayloadIssue(ent.id, ent.label, "No confirmed image for the channel's shot types", "image", severity="warning"))
        _apply_image_naming(p, ent, flat, profile if profile.get("naming") else {**profile, "naming": (channel.config or {}).get("image_profile_naming")})
        if feed_cols:
            p.variants = variants_by_parent.get(ent.id, [])
            _render_feed(meta, channel, p, ent, style, merged, refs, flat, feed_cols)
        validate_payload(p, schema, channel, raw_schema)
        out.append(p)
    if feed_cols:
        validate_feed(channel, out)
    return out


def _apply_image_naming(p: ProductPayload, ent: ProductEntity, flat: dict[str, Any], profile: dict) -> None:
    """IMG-07 / EXP-10: the channel image profile's naming template (for example VPN-SupplierColorName-01) names each
    image in the payload; placeholders are core fields, attribute codes and {{seq}}."""
    naming = (profile or {}).get("naming")
    if not naming:
        return
    for i, img in enumerate(p.images, start=1):
        img["name"] = re.sub(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}", lambda m, seq=i: _naming_value(m.group(1), seq, flat, ent), naming)


def _naming_value(key: str, seq: int, flat: dict[str, Any], ent: ProductEntity) -> str:
    if key == "seq":
        return f"{seq:02d}"
    v = flat.get(key, getattr(ent, key, None))
    if key in ("customer_color_name", "supplier_color_name") and v:
        v = re.sub(r"[^A-Za-z0-9]+", "", str(v).title())
    return "" if v is None else str(v)


def _nrf(meta: Metadata, attr_code: str, code: Any, kind: str) -> Any:
    from pim.adapters.rithum import nrf_code

    attr = meta.attributes.get(attr_code)
    if attr is None or not attr.option_list_code or code in (None, ""):
        return None
    ol = meta.option_lists.get(attr.option_list_code)
    opt = next((o for o in (ol.values if ol else []) if o.code == str(code)), None)
    return nrf_code(opt, kind)


def _render_feed(meta: Metadata, channel: Channel, p: ProductPayload, ent: ProductEntity, style: ProductEntity | None,
                 merged: dict, refs: RefValues, flat: dict[str, Any], feed_cols: list[dict]) -> None:
    """EXP-09: resolve every feed column source at the style-color level; SKU-level sources (core.sku, core.upc,
    core.size, gtin, nrf_size) are filled per variant when the file is written."""
    from pim.adapters.feed_file import transform_case

    color_attr = next((a.code for a in meta.attributes.values() if a.code == "color_family"), None)
    for c in feed_cols:
        src, header = c.get("source") or "", c.get("header")
        if not header:
            continue
        val: Any = None
        if src.startswith("const:"):
            val = src[6:]
        elif src.startswith("image:"):
            idx = int(src.split(":", 1)[1] or 1) - 1
            img = p.images[idx] if 0 <= idx < len(p.images) else None
            val = (img or {}).get("url")
            if img and img.get("name"):
                p.feed.setdefault("_image_names", {})[header] = img["name"]
        elif src == "image_ai_flag":
            val = "Yes" if any(i.get("ai_generated") for i in p.images) else "No"
        elif src == "nrf_color":
            pv = merged.get((color_attr, channel.code)) or merged.get((color_attr, "")) if color_attr else None
            val = _nrf(meta, color_attr, typed_code(pv), "color") if pv is not None else None
        elif src in ("core.sku", "core.upc", "core.size", "gtin", "nrf_size"):
            val = None  # per variant
        else:
            v, _attr = resolve_source(meta, channel, ent, style, merged, src, refs)
            val = v
        if isinstance(val, list):
            val = ", ".join(str(x) for x in val)
        if val is not None and c.get("value_map"):
            val = (c.get("value_map") or {}).get(str(val), val)
        if isinstance(val, str):
            val = transform_case(val, c.get("case_transform", "as_is"))
        p.feed[header] = val
        if src and not src.startswith(("core.", "erp.", "image", "const:", "nrf", "gtin")) and "." not in src:
            p.sources[header] = src


def typed_code(pv: ProductValue) -> Any:
    from pim.services.values import typed_from_row

    t = typed_from_row(pv)
    return t.text if t.text is not None else (t.json[0] if isinstance(t.json, list) and t.json else None)


def _external_id(ent: ProductEntity, style: ProductEntity | None, channel: Channel) -> str | None:
    key = (channel.config or {}).get("external_id") or "style_color"
    if key == "style_color":
        return f"{ent.style_number}-{ent.color_code}" if ent.color_code else ent.style_number
    return _core(ent, style, key)


# ---------------------------------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------------------------------
def feed_rows(channel: Channel, payloads: list[ProductPayload]) -> tuple[list[dict], list[dict]]:
    """EXP-09: rows for the feed renderer. `row_level: sku` (the default for Rithum programs) writes one row per SKU
    with the variant's sku, upc, size and NRF size code; otherwise one row per style-color. Returns (rows, columns)."""
    cfg = channel.config or {}
    cols = default_feed_columns(channel)
    level = cfg.get("row_level") or ("sku" if channel.adapter == "rithum" else "style_color")
    rows: list[dict] = []
    for p in payloads:
        base = {c["header"]: p.feed.get(c["header"]) for c in cols}
        base["_entity_id"], base["_label"] = p.entity_id, p.label
        variants = p.variants if level == "sku" and p.variants else [None]
        for v in variants:
            row = dict(base)
            for c in cols:
                src = c.get("source") or ""
                if v is not None and src in ("core.sku", "core.upc", "core.size", "gtin", "nrf_size"):
                    row[c["header"]] = {"core.sku": v.get("sku"), "core.upc": v.get("upc"), "gtin": v.get("upc"), "core.size": v.get("size"),
                                        "nrf_size": v.get("nrf_size")}[src]
            rows.append(row)
    return rows, cols


def default_feed_columns(channel: Channel) -> list[dict]:
    """Feed columns from the transport profile; a Rithum channel without its own columns and without an attribute
    mapping (a plain mapped channel keeps the Phase 3 path) starts from the program's placeholder columns."""
    cfg = channel.config or {}
    cols = list(cfg.get("feed_columns") or [])
    if not cols and channel.adapter == "rithum" and not (channel.attribute_mapping or {}):
        from pim.adapters.rithum import DEFAULT_COLUMNS

        cols = DEFAULT_COLUMNS.get((cfg.get("rithum") or {}).get("program") or "nordstrom_dropship", [])
    return cols


def feed_adapter_for(channel: Channel, template_bytes: bytes | None = None):  # noqa: ANN201
    from pim.adapters.feed_file import FeedColumn, FeedFileAdapter
    from pim.adapters.rithum import rithum_for_channel

    if channel.adapter == "rithum":
        return rithum_for_channel(channel, template_bytes)
    cols = [FeedColumn(header=c["header"], source=c["header"], always_include=bool(c.get("always_include")), required=bool(c.get("required")))
            for c in (channel.config or {}).get("feed_columns") or []]
    return FeedFileAdapter(cols, template_bytes=template_bytes, header_row=int((channel.config or {}).get("header_row") or 1))


def payload_files(channel: Channel, payloads: list[ProductPayload], schema: TargetSchema | None,
                  template_bytes: bytes | None = None) -> list[tuple[str, bytes, str]]:
    """Returns [(name, content, kind)]: the payload in the channel's file format plus a validation report CSV."""
    fmt = (channel.config or {}).get("file_format") or ("json" if channel.adapter in ("walmart_mp", "mirakl_seller", "target_plus") else "csv")
    valid = [p for p in payloads if p.valid]
    files: list[tuple[str, bytes, str]] = []
    columns = [f.name for f in (schema.fields if schema else [])] or sorted({k for p in payloads for k in p.data})
    if default_feed_columns(channel) and fmt in ("csv", "xlsx"):
        # EXP-09 / EXP-10 / EXP-11: template-based retailer feed, one row per SKU, through the feed renderer
        rows, cols = feed_rows(channel, valid)
        adapter = feed_adapter_for(channel, template_bytes)
        keyed = [{c.source: r.get(c.header) for c in adapter.columns} | {"_label": r.get("_label")} for r in rows]
        # the renderer reads values by source; the rows above are already header-keyed, so map them back
        keyed = [{**{c.source: r.get(c.header) for c in adapter.columns}, "core.style_number": r.get(next((c["header"] for c in cols if c.get("source") == "core.style_number"), ""), None)} for r in rows]
        content = adapter.to_xlsx(keyed) if fmt == "xlsx" else adapter.to_csv(keyed)
        files.append((f"feed.{fmt}", content, "payload"))
        _append_report(files, payloads)
        return files
    if fmt == "json":
        body = [{"external_id": p.external_id, **nest(p.data, schema), "images": p.images} for p in valid]
        if channel.adapter == "walmart_mp":
            from pim.adapters.walmart_mp import WalmartMarketplaceAdapter

            feeds = WalmartMarketplaceAdapter().build_feed([{"orderable": nest(p.data, schema).get("Orderable", {}),
                                                              "visible": nest(p.data, schema).get("Visible", {})} for p in valid])
            body = feeds[0] if len(feeds) == 1 else feeds
        files.append(("payload.json", json.dumps(body, indent=2, default=str).encode(), "payload"))
    elif fmt == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "feed"
        ws.append(columns)
        for p in valid:
            ws.append([_cell(p.data.get(c)) for c in columns])
        buf = io.BytesIO()
        wb.save(buf)
        files.append(("payload.xlsx", buf.getvalue(), "payload"))
    else:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(columns)
        for p in valid:
            w.writerow([_cell(p.data.get(c)) for c in columns])
        files.append(("payload.csv", buf.getvalue().encode("utf-8-sig"), "payload"))
    _append_report(files, payloads)
    return files


def _append_report(files: list[tuple[str, bytes, str]], payloads: list[ProductPayload]) -> None:
    rep = io.StringIO()
    w = csv.writer(rep)
    w.writerow(["entity_id", "product", "severity", "kind", "field", "attribute_code", "message"])
    for p in payloads:
        for i in p.issues:
            w.writerow([i.entity_id, i.label, i.severity, i.kind, i.field or "", i.attribute_code or "", i.message])
    files.append(("validation_report.csv", rep.getvalue().encode("utf-8-sig"), "report"))


def _cell(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v)
    return v
