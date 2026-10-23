"""EXP-13: the Shopify update package. In Phase 1 the PIM never writes to Shopify. It produces:

1. a snapshot of current Shopify state (Admin API read-only token, or an uploaded Shopify product CSV export),
2. a field-level diff of PIM channel-ready values against that snapshot, excluding protected fields (D-09),
3. a review workbook (XLSX) with current and proposed values and an Include (Y/N) column,
4. import-ready CSV files that follow Shopify's documented overwrite rules [C38][C39]:
   - only changed columns, plus the required Handle and Title columns,
   - never a blank cell in an included column unless the change is an intentional clear (listed separately),
   - product-level changes in files with no variant columns; variant-level changes in separate files that always
     include the Option name and value columns (missing Option1 columns delete variants),
   - variant metafields go to the workbook only, marked "needs manual entry or API",
   - files split under 15 MB,
5. a reconcile step that marks each proposed change applied, not applied, or changed differently in Shopify.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.adapters.shopify_admin import ShopifySnapshot
from pim.auth.identity import CurrentUser
from pim.models import (
    Channel,
    IdentifierAlias,
    ProductEntity,
    ProductValue,
    PublishRecord,
    ReferenceEntity,
    SavedView,
    UpdatePackage,
    UpdatePackageRow,
)
from pim.models._common import utcnow
from pim.services.metadata import Metadata
from pim.services.readiness import compute_readiness
from pim.services.storage import Storage
from pim.services.values import typed_from_row

TEAL = "3B859C"
CLEAR = object()  # sentinel: the PIM value is an explicit Not applicable, so the Shopify field should be cleared
MAX_FILE_BYTES = 15 * 1024 * 1024
_WS = re.compile(r"\s+")


def _norm(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v)
    return _WS.sub(" ", str(v)).strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


@dataclass
class Target:
    """Where a mapped attribute lands in Shopify."""

    raw: str
    scope: str  # product | variant | metafield | variant_metafield
    column: str  # CSV column header or metafield key

    @classmethod
    def parse(cls, target: str) -> Target:
        if target.startswith("metafield:"):
            return cls(target, "metafield", target.split(":", 1)[1])
        if target.startswith("variant_metafield:"):
            return cls(target, "variant_metafield", target.split(":", 1)[1])
        if target.startswith("variant:"):
            return cls(target, "variant", target.split(":", 1)[1])
        return cls(target, "product", target)

    def csv_header(self) -> str:
        if self.scope == "metafield":
            label = self.column.split(".")[-1].replace("_", " ").capitalize()
            return f"{label} (product.metafields.{self.column})"
        return self.column


@dataclass
class Skipped:
    entity_id: str
    label: str
    reason: str


@dataclass
class DiffResult:
    rows: list[UpdatePackageRow] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    products: int = 0


# ---------------------------------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------------------------------
def resolve_selection(session: Session, selection: dict) -> list[ProductEntity]:
    ids = selection.get("entity_ids") or []
    if ids:
        ents = session.execute(select(ProductEntity).where(ProductEntity.id.in_(ids))).scalars().all()
    elif selection.get("view_id"):
        view = session.get(SavedView, selection["view_id"])
        if view is None:
            return []
        from pim.services.grid import GridQuery, run_grid_query  # local import to avoid cycle

        d = view.definition or {}
        q = GridQuery(level=view.level, page=1, page_size=5000, filters=d.get("filters", []), search=d.get("search"),
                      columns=["style_number"])
        from pim.auth.identity import CurrentUser as _CU
        from pim.services.metadata import load_metadata

        sys_user = _CU(email="system", user_id=None, roles=["pim_admin"], data_rights={"*": "approve"})
        res = run_grid_query(session, load_metadata(session), sys_user, q)
        ents = session.execute(select(ProductEntity).where(ProductEntity.id.in_([r["entity_id"] for r in res["rows"]]))).scalars().all()
    elif selection.get("changed_since"):
        since = datetime.fromisoformat(selection["changed_since"])
        sub = select(ProductValue.entity_id).where(ProductValue.set_at >= since).distinct()
        ents = session.execute(select(ProductEntity).where(ProductEntity.id.in_(sub))).scalars().all()
    else:
        ents = []
    # Normalize to style-colors (one Shopify product per style-color; config seam `product_level`).
    out: dict[str, ProductEntity] = {}
    for e in ents:
        if e.level == "style_color":
            out[e.id] = e
        elif e.level == "style":
            for c in session.execute(select(ProductEntity).where(ProductEntity.parent_id == e.id,
                                                                  ProductEntity.level == "style_color")).scalars():
                out[c.id] = c
        elif e.level == "sku" and e.parent_id:
            p = session.get(ProductEntity, e.parent_id)
            if p:
                out[p.id] = p
    return list(out.values())


# ---------------------------------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------------------------------
def _channel_ready_value(session: Session, meta: Metadata, values: dict[tuple[str, str], ProductValue],
                         path: str, channel_code: str) -> tuple[Any, ProductValue | None]:
    """Resolve `attr` or `ref_attr.inner_attr`; channel override wins over global; only approved, non-default values."""
    code, _, inner = path.partition(".")
    pv = values.get((code, channel_code)) or values.get((code, ""))
    if pv is None or pv.approval_state != "approved" or (pv.source_type == "default" and not pv.confirmed_default):
        return None, pv
    if pv.not_applicable:
        return CLEAR, pv
    if inner:
        if not pv.value_ref:
            return None, pv
        ref = session.get(ReferenceEntity, pv.value_ref)
        if ref is None:
            return None, pv
        inner_pv = session.execute(select(ProductValue).where(ProductValue.entity_id == ref.id,
                                                              ProductValue.attribute_code == inner,
                                                              ProductValue.channel_code == "")).scalar_one_or_none()
        if inner_pv is None:
            return None, pv
        return _display_value(meta, inner, inner_pv), inner_pv
    return _display_value(meta, code, pv), pv


def _display_value(meta: Metadata, code: str, pv: ProductValue) -> Any:
    attr = meta.attributes.get(code)
    t = typed_from_row(pv)
    if t.not_applicable:
        return None
    if attr and attr.data_type == "single_select":
        return meta.option_label(attr.option_list_code, t.text) or t.text
    if attr and attr.data_type == "multi_select" and isinstance(t.json, list):
        return ", ".join(meta.option_label(attr.option_list_code, c) or c for c in t.json)
    if attr and attr.data_type == "boolean" and t.boolean is not None:
        return "true" if t.boolean else "false"
    return t.as_python()


def _current_value(product: dict, target: Target, variant: dict | None = None) -> Any:
    if target.scope == "product":
        mapping = {"Title": "title", "Body (HTML)": "body_html", "Type": "product_type", "Vendor": "vendor",
                   "Tags": "tags", "SEO Title": "seo_title", "SEO Description": "seo_description",
                   "Product Category": "category", "Status": "status"}
        key = mapping.get(target.column)
        if key:
            return product.get(key)
        return (product.get("columns") or {}).get(target.column)
    if target.scope == "metafield":
        return (product.get("metafields") or {}).get(target.column)
    if variant is not None and target.scope == "variant":
        if target.column.startswith("Option"):
            opts = list(variant.get("options", {}).values())
            idx = int(target.column[6]) - 1
            return opts[idx] if idx < len(opts) else None
        return variant.get({"Variant SKU": "sku", "Variant Barcode": "barcode", "Variant Price": "price"}.get(target.column, target.column))
    if variant is not None and target.scope == "variant_metafield":
        return (variant.get("metafields") or {}).get(target.column)
    return None


def find_handle(session: Session, snap: ShopifySnapshot, sc: ProductEntity, skus: list[ProductEntity],
                title: str | None) -> str | None:
    alias = session.execute(select(IdentifierAlias).where(IdentifierAlias.entity_id == sc.id,
                                                          IdentifierAlias.alias_type == "shopify_handle")).scalar_one_or_none()
    if alias and snap.by_handle(alias.alias):
        return alias.alias
    for s in skus:
        if s.sku:
            hit = snap.by_sku(s.sku)
            if hit:
                handle = hit[0]["handle"]
                session.add(IdentifierAlias(entity_id=sc.id, alias=handle, alias_type="shopify_handle",
                                            normalized=handle.lower(), source="shopify"))
                return handle
    if title and snap.by_handle(slugify(title)):
        return slugify(title)
    return None


# ---------------------------------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------------------------------
def compute_diff(session: Session, meta: Metadata, channel: Channel, snap: ShopifySnapshot,
                 style_colors: list[ProductEntity], package_id: str) -> DiffResult:
    res = DiffResult()
    protected = set(channel.protected_fields or [])
    mapping = channel.attribute_mapping or {}
    handle_attr = (channel.config or {}).get("handle_attribute", "product_title")
    for sc in style_colors:
        style = session.get(ProductEntity, sc.parent_id) if sc.parent_id else None
        skus = session.execute(select(ProductEntity).where(ProductEntity.parent_id == sc.id)).scalars().all()
        ids = [sc.id] + ([style.id] if style else []) + [s.id for s in skus]
        values: dict[str, dict[tuple[str, str], ProductValue]] = defaultdict(dict)
        for pv in session.execute(select(ProductValue).where(ProductValue.entity_id.in_(ids))).scalars():
            values[pv.entity_id][(pv.attribute_code, pv.channel_code)] = pv
        merged: dict[tuple[str, str], ProductValue] = {}
        if style:
            merged.update(values[style.id])
        merged.update(values[sc.id])
        r = compute_readiness(session, meta, sc, channel, merged, style)
        if not r.eligible:
            res.skipped.append(Skipped(sc.id, sc.label, "Not eligible: " + "; ".join(r.reasons)))
            continue
        if not r.ready:
            res.skipped.append(Skipped(sc.id, sc.label, "Not ready: " + "; ".join(r.reasons)))
            continue
        title_val, _ = _channel_ready_value(session, meta, merged, handle_attr, channel.code)
        handle = find_handle(session, snap, sc, skus, title_val)
        if not handle:
            res.skipped.append(Skipped(sc.id, sc.label, "Not in Shopify snapshot (new product; Phase 1 packages update existing products)"))
            continue
        product = snap.by_handle(handle) or {}
        res.products += 1
        for path, target_raw in mapping.items():
            if target_raw in protected or target_raw.replace("metafield:", "") in protected:
                continue
            target = Target.parse(target_raw)
            if target.scope in ("product", "metafield"):
                proposed, pv = _channel_ready_value(session, meta, merged, path, channel.code)
                current = _current_value(product, target)
                if proposed is None or proposed == "":
                    continue  # no PIM value means no change proposed; never an implicit clear
                is_clear = proposed is CLEAR
                if is_clear and _norm(current) == "":
                    continue
                if not is_clear and _norm(proposed) == _norm(current):
                    continue
                res.rows.append(UpdatePackageRow(
                    package_id=package_id, entity_id=sc.id, handle=handle, title=product.get("title"),
                    scope="product", field=target.csv_header(), attribute_code=path, current_value=_norm(current) or None,
                    proposed_value=None if is_clear else (_norm(proposed) or None), is_clear=is_clear,
                    source_type=pv.source_type if pv else None, approval_state=pv.approval_state if pv else None,
                    ai_generated=bool(pv.ai_generated) if pv else False, include=True))
            else:
                # variant-level: compare per SKU against the matching Shopify variant
                for sku_ent in skus:
                    hit = snap.by_sku(sku_ent.sku) if sku_ent.sku else None
                    if not hit:
                        continue
                    _, variant = hit
                    vals = dict(merged)
                    vals.update(values[sku_ent.id])
                    proposed, pv = _channel_ready_value(session, meta, vals, path, channel.code)
                    current = _current_value(product, target, variant)
                    if proposed is None or proposed == "":
                        continue
                    is_clear = proposed is CLEAR
                    if (is_clear and _norm(current) == "") or (not is_clear and _norm(proposed) == _norm(current)):
                        continue
                    note = "needs manual entry or API (variant metafields are not supported in product CSVs)" \
                        if target.scope == "variant_metafield" else None
                    res.rows.append(UpdatePackageRow(
                        package_id=package_id, entity_id=sku_ent.id, handle=handle, title=product.get("title"),
                        scope="variant_metafield" if target.scope == "variant_metafield" else "variant",
                        variant_key={"options": variant.get("options", {}), "sku": variant.get("sku")},
                        field=target.column, attribute_code=path, current_value=_norm(current) or None,
                        proposed_value=None if is_clear else (_norm(proposed) or None), is_clear=is_clear,
                        source_type=pv.source_type if pv else None, approval_state=pv.approval_state if pv else None,
                        ai_generated=bool(pv.ai_generated) if pv else False, include=True, note=note))
    return res


# ---------------------------------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------------------------------
def build_review_workbook(pkg: UpdatePackage, rows: list[UpdatePackageRow], skipped: list[Skipped]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Changes"
    headers = ["Handle", "Product title", "Scope", "Variant", "Field", "Current Shopify value", "Proposed value",
               "Source", "Approval state", "AI generated", "Include (Y/N)", "Note", "Row id"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=TEAL)
    for r in rows:
        variant = ""
        if r.variant_key:
            variant = " / ".join(f"{k}: {v}" for k, v in (r.variant_key.get("options") or {}).items()) or (r.variant_key.get("sku") or "")
        ws.append([r.handle, r.title, r.scope, variant, r.field, r.current_value, r.proposed_value, r.source_type,
                   r.approval_state, "Y" if r.ai_generated else "N", "Y" if r.include else "N", r.note, r.id])
    ws.freeze_panes = "A2"
    ws.column_dimensions["F"].width = 50
    ws.column_dimensions["G"].width = 50
    s = wb.create_sheet("Summary")
    s.append(["Package", pkg.id])
    s.append(["Channel", pkg.channel_code])
    s.append(["Version", pkg.version])
    s.append(["Snapshot taken", pkg.snapshot_at.isoformat() if pkg.snapshot_at else "n/a"])
    s.append(["Products with changes", len({r.handle for r in rows})])
    s.append(["Changed fields", len(rows)])
    s.append([])
    s.append(["Changes by field", "Count"])
    for f, n in Counter(r.field for r in rows).most_common():
        s.append([f, n])
    s.append([])
    s.append(["Changes by product", "Count"])
    for h, n in Counter(r.handle for r in rows).most_common():
        s.append([h, n])
    s.append([])
    s.append(["Intentional clears (blank cells on purpose)", "Field"])
    for r in rows:
        if r.is_clear:
            s.append([r.handle, r.field])
    s.append([])
    s.append(["Products skipped", "Reason"])
    for sk in skipped:
        s.append([sk.label, sk.reason])
    i = wb.create_sheet("Instructions")
    for line in [
        "How to use this package",
        "1. Review each row on the Changes tab. Current Shopify value is what the site has now; Proposed value is what the PIM holds.",
        "2. Set Include (Y/N) to N for any change you do not want. Leave the Row id column untouched.",
        "3. Upload this workbook back to the PIM (Packages > Upload reviewed workbook) to regenerate the import CSVs.",
        "4. Import the CSV files with Shopify's product CSV importer with 'Overwrite products with matching handles' on.",
        "5. Variant metafield rows cannot be imported by CSV; enter them in Shopify or wait for the API path (Phase 2).",
        "6. The PIM reconciles the next snapshot and marks each change applied, not applied, or changed differently.",
    ]:
        i.append([line])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_import_csvs(rows: list[UpdatePackageRow], snap: ShopifySnapshot) -> list[tuple[str, bytes]]:
    """Returns [(filename, bytes)] following Shopify's overwrite rules."""
    files: list[tuple[str, bytes]] = []
    included = [r for r in rows if r.include]
    # Product-level: one row per handle; columns = Handle, Title + changed columns. Never blank unless is_clear.
    product_rows = [r for r in included if r.scope == "product"]
    by_handle: dict[str, dict[str, str]] = defaultdict(dict)
    titles: dict[str, str] = {}
    for r in product_rows:
        by_handle[r.handle][r.field] = "" if r.is_clear else (r.proposed_value or "")
        titles[r.handle] = r.title or (snap.by_handle(r.handle) or {}).get("title") or ""
    if by_handle:
        # Shopify leaves omitted columns unchanged but overwrites blanks. A column included for one product must not
        # be blank for another, so group handles by their exact set of changed columns.
        groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
        for h, cols in by_handle.items():
            groups[tuple(sorted(cols))].append(h)
        for n, (cols, handles) in enumerate(groups.items(), start=1):
            header = ["Handle", "Title", *[c for c in cols if c != "Title"]]
            data = []
            for h in handles:
                row = {"Handle": h, "Title": by_handle[h].get("Title", titles[h])}
                for c in cols:
                    if c != "Title":
                        row[c] = by_handle[h][c]
                data.append(row)
            files.extend(_split_csv(f"products_{n:02d}", header, data))
    # Variant-level: always include Option name/value columns and Variant SKU (missing Option1 deletes variants).
    variant_rows = [r for r in included if r.scope == "variant"]
    if variant_rows:
        by_variant: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
        keys: dict[tuple[str, str], dict] = {}
        for r in variant_rows:
            k = (r.handle, (r.variant_key or {}).get("sku") or "")
            by_variant[k][r.field] = "" if r.is_clear else (r.proposed_value or "")
            keys[k] = r.variant_key or {}
            titles[r.handle] = r.title or ""
        groups_v: dict[tuple[str, ...], list[tuple[str, str]]] = defaultdict(list)
        for k, cols in by_variant.items():
            groups_v[tuple(sorted(cols))].append(k)
        for n, (cols, ks) in enumerate(groups_v.items(), start=1):
            max_opts = max(len(keys[k].get("options") or {}) for k in ks) or 1
            opt_cols = []
            for i in range(1, max_opts + 1):
                opt_cols += [f"Option{i} Name", f"Option{i} Value"]
            header = ["Handle", "Title", *opt_cols, "Variant SKU", *[c for c in cols if not c.startswith("Option")]]
            data = []
            for k in ks:
                handle, sku = k
                row = {"Handle": handle, "Title": titles.get(handle, ""), "Variant SKU": sku}
                opts = list((keys[k].get("options") or {}).items())
                for i in range(1, max_opts + 1):
                    name, val = opts[i - 1] if i - 1 < len(opts) else ("", "")
                    row[f"Option{i} Name"], row[f"Option{i} Value"] = name, val
                for c in cols:
                    if c.startswith("Option") and c.endswith("Value"):
                        row[c] = by_variant[k][c]  # proposed option value replaces the current one
                    elif not c.startswith("Option"):
                        row[c] = by_variant[k][c]
                data.append(row)
            files.extend(_split_csv(f"variants_{n:02d}", header, data))
    return files


def _split_csv(stem: str, header: list[str], rows: list[dict]) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    part, buf, w = 1, io.StringIO(), None

    def flush() -> None:
        nonlocal part, buf, w
        if w is not None and buf.tell() > 0:
            out.append((f"{stem}_part{part}.csv", buf.getvalue().encode("utf-8")))
            part += 1
        buf = io.StringIO()
        w = None

    for r in rows:
        if w is None:
            w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
            w.writeheader()
        w.writerow({h: r.get(h, "") for h in header})
        if buf.tell() > MAX_FILE_BYTES * 0.95:
            flush()
    flush()
    return out


# ---------------------------------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------------------------------
def build_package(session: Session, meta: Metadata, user: CurrentUser | None, pkg: UpdatePackage,
                  snap: ShopifySnapshot, storage: Storage) -> UpdatePackage:
    channel = meta.channels[pkg.channel_code]
    pkg.status = "building"
    session.flush()
    for old in list(pkg.rows):
        session.delete(old)
    style_colors = resolve_selection(session, pkg.selection or {})
    diff = compute_diff(session, meta, channel, snap, style_colors, pkg.id)
    pkg.rows = list(diff.rows)
    session.flush()
    pkg.product_count, pkg.change_count = diff.products, len(diff.rows)
    pkg.summary = {
        "by_field": dict(Counter(r.field for r in diff.rows)),
        "by_product": dict(Counter(r.handle for r in diff.rows)),
        "skipped": [{"entity_id": s.entity_id, "label": s.label, "reason": s.reason} for s in diff.skipped],
        "intentional_clears": [{"handle": r.handle, "field": r.field} for r in diff.rows if r.is_clear],
        "variant_metafield_rows": sum(1 for r in diff.rows if r.scope == "variant_metafield"),
        "selected": len(style_colors),
    }
    write_files(session, pkg, diff.rows, diff.skipped, snap, storage)
    pkg.status = "ready"
    session.add(PublishRecord(channel_code=channel.code, channel_version=channel.version, kind="package",
                              created_by=pkg.created_by, product_count=diff.products, payload_path=pkg.storage_path,
                              result={"changes": len(diff.rows), "skipped": len(diff.skipped)}, package_id=pkg.id))
    return pkg


def write_files(session: Session, pkg: UpdatePackage, rows: list[UpdatePackageRow], skipped: list[Skipped],
                snap: ShopifySnapshot, storage: Storage) -> None:
    base = f"{pkg.id}/v{pkg.version}"
    files = [("review_workbook.xlsx", build_review_workbook(pkg, rows, skipped))]
    files += build_import_csvs(rows, snap)
    pkg.files = []
    for name, data in files:
        full = storage.write(f"{base}/{name}", data)
        kind = "workbook" if name.endswith(".xlsx") else "import_csv"
        pkg.files.append({"name": name, "size": len(data), "kind": kind, "path": full})
    pkg.storage_path = storage.path(base)


def apply_review_workbook(session: Session, pkg: UpdatePackage, content: bytes, snap: ShopifySnapshot, storage: Storage) -> int:
    """EXP-13 step 5: rows marked N are dropped and the CSVs regenerate as a new version."""
    wb = load_workbook(io.BytesIO(content), read_only=True)
    ws = wb["Changes"]
    header = [str(c.value) if c.value is not None else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    idx_inc, idx_id = header.index("Include (Y/N)"), header.index("Row id")
    rows_by_id = {r.id: r for r in pkg.rows}
    changed = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        rid = row[idx_id]
        if rid in rows_by_id:
            inc = str(row[idx_inc] or "Y").strip().upper().startswith("Y")
            if rows_by_id[rid].include != inc:
                rows_by_id[rid].include = inc
                changed += 1
    pkg.version += 1
    skipped = [Skipped(s["entity_id"], s["label"], s["reason"]) for s in (pkg.summary or {}).get("skipped", [])]
    write_files(session, pkg, list(pkg.rows), skipped, snap, storage)
    return changed


def reconcile(pkg: UpdatePackage, fresh: ShopifySnapshot) -> dict[str, int]:
    """EXP-13 step 6: compare each proposed change with a fresh snapshot."""
    counts = Counter()
    for r in pkg.rows:
        product = fresh.by_handle(r.handle)
        if product is None:
            r.reconcile_status = "not_applied"
            counts["not_applied"] += 1
            continue
        variant = None
        if r.variant_key:
            hit = fresh.by_sku(r.variant_key.get("sku") or "")
            variant = hit[1] if hit else None
        target = Target.parse(_target_from_field(r))
        now = _norm(_current_value(product, target, variant))
        if now == _norm(r.proposed_value):
            r.reconcile_status = "applied"
        elif now == _norm(r.current_value):
            r.reconcile_status = "not_applied"
        else:
            r.reconcile_status = "changed_differently"
        r.reconcile_value = now or None
        counts[r.reconcile_status] += 1
    pkg.reconciled_at = utcnow()
    pkg.status = "reconciled"
    return dict(counts)


def _target_from_field(r: UpdatePackageRow) -> str:
    if r.scope == "product" and "(product.metafields." in r.field:
        return "metafield:" + r.field.split("(product.metafields.", 1)[1].rstrip(")")
    if r.scope == "variant":
        return "variant:" + r.field
    if r.scope == "variant_metafield":
        return "variant_metafield:" + r.field
    return r.field
