"""Shopify Admin GraphQL adapter (EXP-07 write path is Phase 2 and feature-flagged off; EXP-13 uses the read path).

Read path (Phase 1): `read_products` scope only. Pulls product, variant, and metafield state with a bulk query
so EXP-13 can diff against it. Also parses a Shopify product CSV export when API read access is not approved.

Write path (Phase 2): every mutation is guarded by `PIM_FEATURE_SHOPIFY_DIRECT_WRITE`; calling it while the flag is
off raises. When it is built out, it must read protected metafields first and send them back unchanged, because
productSet deletes metafields omitted from the input [C2] (D-09: Layer's recommendation metafields are protected).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from collections.abc import Iterable

import httpx

from pim.adapters.base import NotConfigured, PublishResult, ValidationResult
from pim.config import get_settings

log = logging.getLogger(__name__)

PRODUCT_QUERY = """
{
  products {
    edges { node {
      id handle title descriptionHtml productType vendor tags status
      category { id fullName }
      seo { title description }
      metafields(first: 50) { edges { node { namespace key value type } } }
      variants(first: 100) { edges { node {
        id sku barcode price compareAtPrice
        selectedOptions { name value }
        metafields(first: 20) { edges { node { namespace key value type } } }
      } } }
    } }
  }
}
"""


class ShopifySnapshot:
    """Current Shopify product state keyed by handle, in a transport-neutral shape used by EXP-13."""

    def __init__(self) -> None:
        self.products: dict[str, dict] = {}
        self.taken_at: str | None = None
        self._sku_index: dict[str, tuple[dict, dict]] | None = None

    def by_handle(self, handle: str) -> dict | None:
        return self.products.get(handle.lower())

    def by_sku(self, sku: str | None) -> tuple[dict, dict] | None:
        if not sku:
            return None
        if self._sku_index is None:
            self.reindex()
        assert self._sku_index is not None
        return self._sku_index.get(sku.upper())

    def reindex(self) -> None:
        """Build the SKU index once; a 100,000-SKU selection would otherwise scan every variant per lookup."""
        index: dict[str, tuple[dict, dict]] = {}
        for p in self.products.values():
            for v in p.get("variants", []):
                if v.get("sku"):
                    index.setdefault(str(v["sku"]).upper(), (p, v))
        self._sku_index = index

    def add(self, product: dict) -> None:
        self.products[product["handle"].lower()] = product
        self._sku_index = None


class ShopifyAdminClient:
    name = "shopify_admin"

    def __init__(self, store_domain: str | None = None, token: str | None = None, api_version: str | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        s = get_settings()
        self.store = store_domain or s.shopify_store_domain
        self.token = token or s.shopify_read_token
        self.version = api_version or s.shopify_api_version
        self.direct_write = s.feature_shopify_direct_write
        if not self.store or not self.token:
            raise NotConfigured("Shopify store domain and read token are not configured")
        self._client = httpx.Client(base_url=f"https://{self.store}/admin/api/{self.version}", timeout=60.0,
                                    transport=transport, headers={"X-Shopify-Access-Token": self.token,
                                                                   "Content-Type": "application/json"})

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        for _attempt in range(5):
            resp = self._client.post("/graphql.json", json={"query": query, "variables": variables or {}})
            if resp.status_code == 429:
                time.sleep(float(resp.headers.get("Retry-After", "2")))
                continue
            resp.raise_for_status()
            data = resp.json()
            throttle = (data.get("extensions") or {}).get("cost", {}).get("throttleStatus", {})
            if throttle and throttle.get("currentlyAvailable", 1000) < 100:  # cost-based limits [C1]
                time.sleep(1.0)
            if data.get("errors"):
                raise RuntimeError(f"Shopify GraphQL errors: {data['errors']}")
            return data["data"]
        raise RuntimeError("Shopify GraphQL kept throttling")

    # ---- read path (EXP-13 step 1) ----------------------------------------------------------------------
    def snapshot_via_bulk(self, poll_seconds: float = 5.0, max_wait: float = 1800.0) -> ShopifySnapshot:
        """Runs bulkOperationRunQuery and reads the JSONL result [C3]."""
        start = self.graphql(
            'mutation($q: String!) { bulkOperationRunQuery(query: $q) { bulkOperation { id status } userErrors { field message } } }',
            {"q": PRODUCT_QUERY},
        )
        errs = start["bulkOperationRunQuery"]["userErrors"]
        if errs:
            raise RuntimeError(f"bulk query refused: {errs}")
        waited = 0.0
        url = None
        while waited < max_wait:
            cur = self.graphql("{ currentBulkOperation { id status errorCode url objectCount } }")["currentBulkOperation"]
            if cur["status"] == "COMPLETED":
                url = cur["url"]
                break
            if cur["status"] in ("FAILED", "CANCELED"):
                raise RuntimeError(f"bulk query {cur['status']}: {cur.get('errorCode')}")
            time.sleep(poll_seconds)
            waited += poll_seconds
        if not url:
            raise RuntimeError("bulk query timed out")
        text = httpx.get(url, timeout=120.0).text
        return parse_bulk_jsonl(text)

    # ---- write path (EXP-07, Phase 2, flag off) ---------------------------------------------------------
    def _guard(self) -> None:
        if not self.direct_write:
            raise NotConfigured("Direct Shopify writes are disabled (PIM_FEATURE_SHOPIFY_DIRECT_WRITE=false). Use EXP-13 packages.")

    def validate(self, payload: Iterable[dict]) -> ValidationResult:
        errors = []
        for p in payload:
            if len(p.get("variants", [])) > 2048:
                errors.append({"handle": p.get("handle"), "message": "more than 2048 variants"})
            if len(p.get("options", [])) > 3:
                errors.append({"handle": p.get("handle"), "message": "more than 3 options"})
        return ValidationResult(ok=not errors, errors=errors)

    def publish(self, batch: list[dict], dry_run: bool = False) -> PublishResult:
        if dry_run:
            return PublishResult(batch_id="dry-run", accepted=len(batch), status="dry_run")
        self._guard()
        raise NotImplementedError("TODO(decision: D-03): targeted mutations vs productSet, pending field ownership")

    def fetch_status(self, batch_id: str) -> dict:
        return {"batch_id": batch_id, "status": "unknown"}

    def fetch_errors(self, batch_id: str) -> list[dict]:
        return []


# ---------------------------------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------------------------------
def parse_bulk_jsonl(text: str) -> ShopifySnapshot:
    snap = ShopifySnapshot()
    products: dict[str, dict] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        parent = obj.get("__parentId")
        gid = obj.get("id", "")
        if parent is None and "handle" in obj:
            products[gid] = {
                "id": gid, "handle": obj["handle"], "title": obj.get("title"), "body_html": obj.get("descriptionHtml"),
                "product_type": obj.get("productType"), "vendor": obj.get("vendor"), "tags": obj.get("tags") or [],
                "status": obj.get("status"), "category": (obj.get("category") or {}).get("fullName"),
                "seo_title": (obj.get("seo") or {}).get("title"), "seo_description": (obj.get("seo") or {}).get("description"),
                "metafields": {}, "variants": [],
            }
        elif parent in products and "namespace" in obj:
            products[parent]["metafields"][f"{obj['namespace']}.{obj['key']}"] = obj.get("value")
        elif parent in products and ("sku" in obj or "selectedOptions" in obj):
            products[parent]["variants"].append({
                "id": gid, "sku": obj.get("sku"), "barcode": obj.get("barcode"), "price": obj.get("price"),
                "options": {o["name"]: o["value"] for o in obj.get("selectedOptions", [])}, "metafields": {},
            })
        else:
            # variant metafield: parent is a variant id
            for p in products.values():
                for v in p["variants"]:
                    if v["id"] == parent and "namespace" in obj:
                        v["metafields"][f"{obj['namespace']}.{obj['key']}"] = obj.get("value")
    for p in products.values():
        snap.add(p)
    return snap


def parse_product_csv(content: bytes | str) -> ShopifySnapshot:
    """Parses Shopify's product CSV export (EXP-13 step 1 fallback). Metafield columns look like
    `Short description (product.metafields.custom.short_description)`."""
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    reader = csv.DictReader(io.StringIO(text))
    snap = ShopifySnapshot()
    current: dict | None = None
    for row in reader:
        handle = (row.get("Handle") or "").strip()
        if not handle:
            continue
        if current is None or current["handle"].lower() != handle.lower():
            current = snap.by_handle(handle)
            if current is None:
                current = {"handle": handle, "title": row.get("Title"), "body_html": row.get("Body (HTML)"),
                           "product_type": row.get("Type"), "vendor": row.get("Vendor"),
                           "tags": [t.strip() for t in (row.get("Tags") or "").split(",") if t.strip()],
                           "status": row.get("Status"), "category": row.get("Product Category"),
                           "seo_title": row.get("SEO Title"), "seo_description": row.get("SEO Description"),
                           "metafields": {}, "variants": [], "columns": {}}
                for col, val in row.items():
                    if col and "(product.metafields." in col:
                        key = col.split("(product.metafields.", 1)[1].rstrip(")")
                        current["metafields"][key] = val
                    elif col:
                        current["columns"][col] = val
                snap.add(current)
        options = {}
        for i in (1, 2, 3):
            n, v = row.get(f"Option{i} Name"), row.get(f"Option{i} Value")
            if n and v:
                options[n] = v
            elif v and current["variants"]:
                options[list(current["variants"][0]["options"].keys())[i - 1] if len(current["variants"][0]["options"]) >= i else f"Option{i}"] = v
        if row.get("Variant SKU") or options:
            current["variants"].append({"sku": row.get("Variant SKU"), "barcode": row.get("Variant Barcode"),
                                        "price": row.get("Variant Price"), "options": options, "metafields": {}})
    snap.reindex()  # variants were appended after add()
    return snap
