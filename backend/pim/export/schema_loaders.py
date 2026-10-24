"""EXP-02 target schema loaders. Each loader turns a retailer's own spec into the common TargetSchema shape
(docs/api-contract-phase3.md) so mappings, validation (EXP-04) and readiness (EXP-03) work the same for every
channel. Supported sources:

- walmart_spec: Walmart Marketplace item spec JSON Schema (MP_ITEM spec v5, one product type) [C9]
- mirakl: Nordstrom Marketplace Mirakl exports H11 (hierarchies), PM11 (attributes), VL11 (value lists) as CSV
  or a ZIP of them [C23]
- shopify: Shopify metafield definitions JSON (Admin API `metafieldDefinitions` payload or a saved copy) plus the
  fixed product CSV columns
- retailer_xlsx: a retailer's data feed template workbook (header row = fields; a second row of hints is optional)

`diff_schemas` reports added and removed fields, required flips and enum changes between two loads.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from openpyxl import load_workbook

SOURCES = ("walmart_spec", "mirakl", "shopify", "retailer_xlsx", "manual")

SHOPIFY_FIXED_COLUMNS: list[tuple[str, str, bool, int | None]] = [
    ("Handle", "string", True, 255), ("Title", "string", True, 255), ("Body (HTML)", "string", False, None),
    ("Vendor", "string", False, 255), ("Product Category", "string", False, None), ("Type", "string", False, 255),
    ("Tags", "string", False, None), ("Published", "boolean", False, None), ("Option1 Name", "string", False, None),
    ("Option1 Value", "string", False, None), ("Option2 Name", "string", False, None), ("Option2 Value", "string", False, None),
    ("Option3 Name", "string", False, None), ("Option3 Value", "string", False, None), ("Variant SKU", "string", False, None),
    ("Variant Barcode", "string", False, None), ("Variant Price", "number", False, None), ("Image Src", "string", False, None),
    ("Image Position", "integer", False, None), ("Image Alt Text", "string", False, 512), ("SEO Title", "string", False, 70),
    ("SEO Description", "string", False, 320), ("Status", "enum", False, None),
]


@dataclass
class TargetField:
    name: str
    type: str = "string"
    required: bool = False
    enum: list[str] | None = None
    max_length: int | None = None
    min: float | None = None
    max: float | None = None
    group: str | None = None
    description: str | None = None
    path: str | None = None

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items()}


@dataclass
class TargetSchema:
    source: str
    fields: list[TargetField] = field(default_factory=list)
    version: str | None = None
    product_type: str | None = None
    loaded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    raw_available: bool = False

    def as_dict(self) -> dict:
        return {"source": self.source, "version": self.version, "product_type": self.product_type, "loaded_at": self.loaded_at,
                "fields": [f.as_dict() for f in self.fields], "raw_available": self.raw_available}

    @classmethod
    def from_dict(cls, d: dict | None) -> TargetSchema:
        d = d or {}
        fields = [TargetField(**{k: v for k, v in f.items() if k in TargetField.__dataclass_fields__}) for f in d.get("fields", [])]
        return cls(source=d.get("source", "manual"), fields=fields, version=d.get("version"), product_type=d.get("product_type"),
                   loaded_at=d.get("loaded_at") or datetime.now(UTC).isoformat(), raw_available=bool(d.get("raw_available")))

    def by_name(self) -> dict[str, TargetField]:
        return {f.name: f for f in self.fields}


class SchemaLoadError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------------
# Walmart MP_ITEM spec (JSON Schema)
# ---------------------------------------------------------------------------------------------------
_JSON_TYPES = {"string": "string", "number": "number", "integer": "integer", "boolean": "boolean", "array": "array", "object": "object"}


def _walk_json_schema(node: dict, path: str, group: str | None, required_here: set[str], out: list[TargetField], depth: int = 0) -> None:
    props = node.get("properties") or {}
    for name, spec in props.items():
        if not isinstance(spec, dict):
            continue
        full_path = f"{path}/{name}"
        sub_required = set(spec.get("required") or [])
        jtype = spec.get("type")
        if isinstance(jtype, list):
            jtype = next((t for t in jtype if t != "null"), "string")
        if jtype == "object" and spec.get("properties") and depth < 4:
            _walk_json_schema(spec, full_path, name, sub_required, out, depth + 1)
            continue
        enum = spec.get("enum")
        if jtype == "array" and isinstance(spec.get("items"), dict) and spec["items"].get("enum"):
            enum = spec["items"]["enum"]
        ftype = "enum" if enum and jtype in (None, "string") else _JSON_TYPES.get(str(jtype), "string")
        if spec.get("format") in ("date", "date-time"):
            ftype = "date"
        out.append(TargetField(name=name, type=ftype, required=name in required_here, enum=[str(e) for e in enum] if enum else None,
                               max_length=spec.get("maxLength"), min=spec.get("minimum"), max=spec.get("maximum"),
                               group=group, description=(spec.get("description") or spec.get("title") or None), path=full_path))


def load_walmart_spec(content: bytes, product_type: str | None = None) -> TargetSchema:
    """Walmart publishes one JSON Schema per product type; the spec file may hold one type or a map of types."""
    try:
        doc = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaLoadError(f"Walmart spec is not valid JSON: {exc}") from exc
    version = str(doc.get("version") or doc.get("$id") or doc.get("title") or "")
    node = doc
    # Walmart spec v5: properties.MPItem.items.properties.{Orderable,Visible}.properties.<ProductType>
    props = doc.get("properties") or {}
    if "MPItem" in props:
        item = props["MPItem"].get("items") or props["MPItem"]
        node = item
        visible = (item.get("properties") or {}).get("Visible") or {}
        types = list((visible.get("properties") or {}).keys())
        if product_type and product_type not in types:
            raise SchemaLoadError(f"Product type {product_type!r} not in spec; available: {', '.join(types[:20]) or 'none (no Visible section)'}")
        if not product_type and len(types) == 1:
            product_type = types[0]
        if product_type:
            vis_props = {product_type: visible["properties"][product_type]}
            node = {"properties": {"Orderable": (item.get("properties") or {}).get("Orderable", {}),
                                   "Visible": {"type": "object", "properties": vis_props, "required": [product_type]}},
                    "required": item.get("required") or ["Orderable", "Visible"]}
    elif product_type and product_type in props:
        node = props[product_type]
    fields: list[TargetField] = []
    _walk_json_schema(node, "", None, set(node.get("required") or []), fields)
    if not fields:
        raise SchemaLoadError("No properties found in the Walmart spec")
    return TargetSchema(source="walmart_spec", fields=fields, version=version or None, product_type=product_type, raw_available=True)


# ---------------------------------------------------------------------------------------------------
# Mirakl PM11 / VL11 / H11
# ---------------------------------------------------------------------------------------------------
def _read_csv(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig", errors="replace")
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rows]


def _first(row: dict, *keys: str) -> str:
    for k in keys:
        if row.get(k):
            return row[k]
    return ""


def load_mirakl(files: dict[str, bytes]) -> TargetSchema:
    """`files` maps a name to content; names containing pm11/attributes, vl11/values, h11/hierarch are recognized.
    A single ZIP under any name is expanded first."""
    expanded: dict[str, bytes] = {}
    for name, content in files.items():
        if name.lower().endswith(".zip") or content[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for info in zf.infolist():
                    if not info.is_dir():
                        expanded[info.filename] = zf.read(info)
        else:
            expanded[name] = content
    pm, vl = [], []
    for name, content in expanded.items():
        n = name.lower()
        if "pm11" in n or "attribut" in n:
            pm = _read_csv(content)
        elif "vl11" in n or "value" in n:
            vl = _read_csv(content)
    if not pm:
        raise SchemaLoadError("Mirakl load needs the PM11 attributes export (CSV or inside the ZIP)")
    values: dict[str, list[str]] = {}
    for r in vl:
        code = _first(r, "list code", "values list code", "values_list_code", "code")
        val = _first(r, "value code", "value", "value_code")
        if code and val:
            values.setdefault(code, []).append(val)
    fields: list[TargetField] = []
    for r in pm:
        code = _first(r, "code", "attribute code", "attribute_code")
        if not code:
            continue
        mtype = _first(r, "type", "attribute type").upper()
        list_code = _first(r, "values list", "values_list", "value list code", "values list code")
        ftype = {"TEXT": "string", "LONG_TEXT": "string", "INTEGER": "integer", "DECIMAL": "number", "NUMERIC": "number",
                 "BOOLEAN": "boolean", "DATE": "date", "LIST": "enum", "LIST_MULTIPLE_VALUES": "array", "MEDIA": "string",
                 "REGEX": "string", "URL": "string"}.get(mtype, "string")
        if list_code and ftype == "string":
            ftype = "enum"
        size = _first(r, "type parameter", "size", "max length")
        max_len = int(size) if size.isdigit() else None
        req = _first(r, "required", "requirement level", "is required").lower() in ("true", "yes", "required", "1")
        fields.append(TargetField(name=code, type=ftype, required=req, enum=values.get(list_code) if list_code else None,
                                  max_length=max_len, group=_first(r, "hierarchy code", "hierarchy", "category") or None,
                                  description=_first(r, "label", "description") or None, path=None))
    if not fields:
        raise SchemaLoadError("PM11 export had no attribute rows")
    return TargetSchema(source="mirakl", fields=fields, raw_available=True)


# ---------------------------------------------------------------------------------------------------
# Shopify: fixed columns plus metafield definitions
# ---------------------------------------------------------------------------------------------------
_SHOPIFY_MF_TYPES = {"single_line_text_field": "string", "multi_line_text_field": "string", "rich_text_field": "string",
                     "number_integer": "integer", "number_decimal": "number", "boolean": "boolean", "date": "date",
                     "date_time": "date", "url": "string", "json": "object", "list.single_line_text_field": "array",
                     "list.number_integer": "array", "list.number_decimal": "array", "color": "string", "weight": "object",
                     "dimension": "object", "volume": "object", "rating": "object", "money": "object"}


def load_shopify(content: bytes | None) -> TargetSchema:
    fields = [TargetField(name=n, type=t, required=r, max_length=ml, group="product",
                          enum=["active", "draft", "archived"] if n == "Status" else None) for n, t, r, ml in SHOPIFY_FIXED_COLUMNS]
    version = None
    if content:
        try:
            doc = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SchemaLoadError(f"Metafield definitions are not valid JSON: {exc}") from exc
        defs = doc
        if isinstance(doc, dict):
            data = doc.get("data", doc)
            node = data.get("metafieldDefinitions") if isinstance(data, dict) else None
            if isinstance(node, dict):
                defs = [e.get("node", e) for e in node.get("edges", node.get("nodes", []))]
            else:
                defs = data.get("definitions") or data.get("metafield_definitions") or node or []
            version = str(doc.get("api_version") or "") or None
        for d in defs or []:
            if not isinstance(d, dict):
                continue
            ns, key = d.get("namespace") or "custom", d.get("key") or d.get("name")
            if not key:
                continue
            owner = (d.get("ownerType") or d.get("owner_type") or "PRODUCT").lower()
            mtype = d.get("type", {}).get("name") if isinstance(d.get("type"), dict) else d.get("type")
            enum = None
            for v in d.get("validations") or []:
                if v.get("name") == "choices":
                    try:
                        enum = [str(x) for x in json.loads(v.get("value", "[]"))]
                    except json.JSONDecodeError:
                        enum = None
            ftype = _SHOPIFY_MF_TYPES.get(str(mtype), "string")
            if enum:
                ftype = "enum"
            max_len = None
            for v in d.get("validations") or []:
                if v.get("name") == "max" and ftype == "string" and str(v.get("value", "")).isdigit():
                    max_len = int(v["value"])
            fields.append(TargetField(name=f"{ns}.{key}", type=ftype, required=False, enum=enum, max_length=max_len,
                                      group=f"{owner}_metafield", description=d.get("description") or d.get("name"),
                                      path=f"/metafields/{ns}.{key}"))
    return TargetSchema(source="shopify", fields=fields, version=version, raw_available=bool(content))


# ---------------------------------------------------------------------------------------------------
# Retailer XLSX template (EXP-09 feeds)
# ---------------------------------------------------------------------------------------------------
def load_retailer_xlsx(content: bytes, header_row: int = 1) -> TargetSchema:
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise SchemaLoadError(f"Not a readable XLSX template: {exc}") from exc
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(min_row=header_row, max_row=header_row + 2, values_only=True))
    if not rows or not any(rows[0]):
        raise SchemaLoadError("The template has no header row")
    hints = rows[1] if len(rows) > 1 else ()
    fields: list[TargetField] = []
    for idx, name in enumerate(rows[0]):
        if name is None or str(name).strip() == "":
            continue
        label = str(name).strip()
        raw_hint = str(hints[idx]).strip() if idx < len(hints) and hints[idx] is not None else ""
        hint = raw_hint.lower()
        required = label.endswith("*") or "required" in hint or "mandatory" in hint
        ftype = "string"
        enum = None
        if "|" in raw_hint and len(raw_hint) < 400:
            enum = [h.strip() for h in raw_hint.split("|") if h.strip()]
            ftype = "enum"
        elif any(w in hint for w in ("number", "numeric", "decimal", "price")):
            ftype = "number"
        elif "date" in hint:
            ftype = "date"
        elif hint in ("yes/no", "y/n", "boolean", "true/false"):
            ftype = "boolean"
        fields.append(TargetField(name=label.rstrip("*").strip(), type=ftype, required=required, enum=enum,
                                  group=ws.title, description=raw_hint or None))
    wb.close()
    return TargetSchema(source="retailer_xlsx", fields=fields, raw_available=True)


# ---------------------------------------------------------------------------------------------------
# Dispatch and diff
# ---------------------------------------------------------------------------------------------------
def load_for_adapter(adapter: str, files: dict[str, bytes] | None, product_type: str | None = None) -> TargetSchema:
    files = files or {}
    first = next(iter(files.values()), None)
    if adapter == "walmart_mp":
        if first is None:
            raise SchemaLoadError("Upload the Walmart item spec JSON for the product type (the spec API needs Phase 5 credentials)")
        return load_walmart_spec(first, product_type)
    if adapter == "mirakl_seller":
        if not files:
            raise SchemaLoadError("Upload the Mirakl PM11 and VL11 exports (CSV or ZIP)")
        return load_mirakl(files)
    if adapter == "shopify_admin":
        return load_shopify(first)
    if adapter in ("feed_file", "target_plus"):
        if first is None:
            raise SchemaLoadError("Upload the retailer's XLSX template")
        return load_retailer_xlsx(first)
    raise SchemaLoadError(f"No schema loader for adapter {adapter!r}")


def diff_schemas(before: TargetSchema | None, after: TargetSchema) -> dict:
    old = before.by_name() if before else {}
    new = after.by_name()
    added = [f.as_dict() for n, f in new.items() if n not in old]
    removed = [f.as_dict() for n, f in old.items() if n not in new]
    required_changed = [{"name": n, "before": old[n].required, "after": f.required}
                        for n, f in new.items() if n in old and old[n].required != f.required]
    enum_changed = []
    for n, f in new.items():
        if n in old and (old[n].enum or f.enum):
            o, c = set(old[n].enum or []), set(f.enum or [])
            if o != c:
                enum_changed.append({"name": n, "added": sorted(c - o), "removed": sorted(o - c)})
    return {"added": added, "removed": removed, "required_changed": required_changed, "enum_changed": enum_changed}
