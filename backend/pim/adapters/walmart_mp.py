"""Walmart Marketplace adapter (EXP-08) [C8][C9][C12][C14][C15].

Mechanics built here, all behind PIM_FEATURE_CHANNEL_SEND until the client id and secret are bound (GOV-05):
- OAuth client credentials token (`POST /v3/token`), refreshed before expiry, with the WM_* headers on every call
- MP_ITEM feeds (`POST /v3/feeds?feedType=MP_ITEM`) with MPItemFeedHeader and items split into Orderable and Visible,
  batched at the account's feed item limit (10,000 typical, 5,000 on some accounts; the channel profile pins it)
- Item Spec version pinned in the channel profile [C9]
- Variant groups: stable variantGroupId per style, the same variantAttributeNames (at most 3) across the group, exactly
  one isPrimaryVariant, and a swatch image per variant [C12]; MP_MAINTENANCE adds variants to an existing group
- Feed and item status polling on Walmart's cadence (15 minutes, 1 hour, 2 hours, then every 4 hours), storing
  ingestion errors including the case where the feed is PROCESSED while an item is still INPROGRESS [C14]
- Listing Quality score per item for the channel health view [C15]

Endpoint paths follow the public developer docs cited above; the listing quality item endpoint shape is
UNCONFIRMED against a live account and is isolated in `listing_quality`.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

import httpx

from pim.adapters.base import NotConfigured, PublishResult, ValidationResult
from pim.config import get_settings

log = logging.getLogger(__name__)

POLL_CADENCE_MINUTES = [15, 60, 120, 240]  # then every 4 hours [C14]
STATUS_PAGE_SIZE = 1000  # /v3/feeds/{id}?includeDetails=true pages item statuses at 1,000
LISTING_QUALITY_BATCH = 200
FEED_TERMINAL_STATUSES = ("PROCESSED", "ERROR")
FEED_FAILED_STATUSES = ("ERROR",)


def _feed_error(data: dict) -> str:
    errs = data.get("ingestionErrors")
    if isinstance(errs, dict):
        errs = errs.get("ingestionError") or []
    parts = [f"{e.get('code', '')}: {e.get('description', '')}".strip(": ") for e in (errs or []) if isinstance(e, dict)]
    return "; ".join(x for x in parts if x) or "feed rejected by Walmart"


ITEM_STATUS_MAP = {"SUCCESS": "accepted", "PUBLISHED": "accepted", "DATA_ERROR": "rejected", "SYSTEM_ERROR": "rejected",
                   "TIMEOUT_ERROR": "rejected", "INPROGRESS": "in_review", "RECEIVED": "in_review", "PROCESSING": "in_review",
                   "ERROR": "rejected"}


def next_poll_at(polls_done: int, now: datetime) -> datetime:
    minutes = POLL_CADENCE_MINUTES[min(polls_done, len(POLL_CADENCE_MINUTES) - 1)]
    return now + timedelta(minutes=minutes)


class WalmartMarketplaceAdapter:
    name = "walmart_mp"

    def __init__(self, client_id: str | None = None, client_secret: str | None = None, spec_version: str = "5.0",
                 max_items_per_feed: int = 5000, base_url: str | None = None, transport: httpx.BaseTransport | None = None,
                 service_name: str = "Swim USA PIM") -> None:
        s = get_settings()
        self.client_id = client_id or getattr(s, "walmart_client_id", None)
        self.client_secret = client_secret or getattr(s, "walmart_client_secret", None)
        self.spec_version = spec_version
        self.max_items = max(1, int(max_items_per_feed or 5000))
        self.base_url = (base_url or getattr(s, "walmart_base_url", "https://marketplace.walmartapis.com")).rstrip("/")
        self.service_name = service_name
        self._client = httpx.Client(base_url=self.base_url, timeout=60.0, transport=transport)
        self._token: str | None = None
        self._token_expires = 0.0

    # ---- auth and headers --------------------------------------------------------------------------
    def _headers(self, with_token: bool = True) -> dict[str, str]:
        h = {"WM_SVC.NAME": self.service_name, "WM_QOS.CORRELATION_ID": str(uuid.uuid4()), "Accept": "application/json"}
        if with_token:
            h["WM_SEC.ACCESS_TOKEN"] = self.token()
        return h

    def token(self) -> str:
        if not self.client_id or not self.client_secret:
            raise NotConfigured("Walmart credentials not bound (secrets walmart-client-id and walmart-client-secret, GOV-05)")
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = self._client.post("/v3/token", data={"grant_type": "client_credentials"},
                                 headers={**self._headers(with_token=False), "Authorization": f"Basic {basic}",
                                          "Content-Type": "application/x-www-form-urlencoded"})
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires = time.time() + float(data.get("expires_in", 900))
        return self._token

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        delay = 2.0
        for _attempt in range(5):
            resp = self._client.request(method, path, headers={**self._headers(), **kw.pop("headers", {})}, **kw)
            if resp.status_code in (429, 503):
                time.sleep(float(resp.headers.get("Retry-After", delay)))
                delay = min(delay * 2, 30)
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError(f"Walmart API kept throttling: {method} {path}")

    # ---- feed shape ---------------------------------------------------------------------------------
    def build_feed(self, items: list[dict], process_mode: str = "REPLACE") -> list[dict]:
        """Split items into MP_ITEM feeds with header, Orderable and Visible sections [C8]."""
        feeds = []
        for i in range(0, len(items), self.max_items):
            feeds.append({
                "MPItemFeedHeader": {"sellingChannel": "mpsetupbymatch" if process_mode == "MATCH" else "marketplace",
                                     "processMode": process_mode, "subset": "EXTERNAL", "locale": "en", "version": self.spec_version},
                "MPItem": [{"Orderable": it.get("orderable", {}), "Visible": it.get("visible", {})} for it in items[i:i + self.max_items]],
            })
        return feeds

    def build_maintenance_feed(self, items: list[dict]) -> dict:
        """MP_MAINTENANCE: add variants to an existing variant group or update attributes without a full item [C12]."""
        return {"MPItemFeedHeader": {"processMode": "PARTIAL_UPDATE", "subset": "EXTERNAL", "locale": "en", "version": self.spec_version},
                "MPItem": [{"Orderable": it.get("orderable", {}), "Visible": it.get("visible", {})} for it in items]}

    @staticmethod
    def group_variants(items: list[dict], attribute_names: list[str] | None = None) -> list[dict]:
        """Assign variantGroupId, variantAttributeNames and isPrimaryVariant per style when the payload carries a
        `variant_group` key (the style number); the first item of a group with an image is primary [C12]."""
        names = list(attribute_names or [])[:3]
        groups: dict[str, list[dict]] = {}
        for it in items:
            g = it.get("variant_group")
            if g:
                groups.setdefault(str(g), []).append(it)
        for gid, members in groups.items():
            if len(members) < 2:
                continue
            primary_set = False
            for it in members:
                o = it.setdefault("orderable", {})
                o["variantGroupId"] = gid
                if names:
                    o["variantAttributeNames"] = names
                has_image = bool((it.get("visible") or {}).get("mainImageUrl") or _deep_get(it.get("visible") or {}, "mainImageUrl"))
                if not primary_set and has_image:
                    o["isPrimaryVariant"] = "Yes"
                    primary_set = True
                else:
                    o["isPrimaryVariant"] = "No"
            if not primary_set:
                members[0]["orderable"]["isPrimaryVariant"] = "Yes"
        return items

    def validate(self, payload: Iterable[dict]) -> ValidationResult:
        errors: list[dict] = []
        warnings: list[dict] = []
        groups: dict[str, list[dict]] = {}
        items = list(payload)
        for it in items:
            o = it.get("orderable", {})
            vg = o.get("variantGroupId")
            if vg:
                groups.setdefault(vg, []).append(it)
        for vg, members in groups.items():
            names = {tuple(sorted(i.get("orderable", {}).get("variantAttributeNames", []))) for i in members}
            if len(names) > 1:
                errors.append({"variantGroupId": vg, "message": "variantAttributeNames differ within the group", "kind": "internal"})
            if any(len(n) > 3 for n in names):
                errors.append({"variantGroupId": vg, "message": "more than 3 variant attributes", "kind": "internal"})
            primaries = sum(1 for i in members if str(i.get("orderable", {}).get("isPrimaryVariant", "")).lower() in ("yes", "true"))
            if primaries != 1:
                errors.append({"variantGroupId": vg, "message": f"exactly one isPrimaryVariant required, found {primaries}", "kind": "internal"})
            for i in members:
                vis = i.get("visible") or {}
                if not (vis.get("swatchImages") or _deep_get(vis, "swatchImages")):
                    warnings.append({"variantGroupId": vg, "sku": i.get("orderable", {}).get("sku"), "message": "variant has no swatch image [C12]", "kind": "internal"})
        return ValidationResult(ok=not errors, errors=errors, warnings=warnings)

    # ---- submit and poll ---------------------------------------------------------------------------
    def publish(self, batch: list[dict], dry_run: bool = False) -> PublishResult:
        feeds = self.build_feed(batch)
        if dry_run:
            return PublishResult(batch_id="dry-run", accepted=len(batch), status="dry_run", detail={"feeds": len(feeds)})
        if not get_settings().feature_channel_send:
            raise NotConfigured("PIM_FEATURE_CHANNEL_SEND is off; the feed was built and validated but not sent")
        feed_ids: list[str] = []
        for feed in feeds:
            resp = self._request("POST", "/v3/feeds", params={"feedType": "MP_ITEM"},
                                 files={"file": ("feed.json", json.dumps(feed).encode(), "application/json")})
            feed_ids.append(str(resp.json().get("feedId")))
        return PublishResult(batch_id=feed_ids[0] if feed_ids else "", accepted=len(batch), status="submitted",
                             detail={"feed_ids": feed_ids, "feeds": len(feeds), "spec_version": self.spec_version})

    def fetch_status(self, batch_id: str) -> dict:
        """Feed status with item details; a PROCESSED feed can still carry INPROGRESS items [C14]."""
        # Item statuses page 1,000 at a time; a feed can hold up to max_items_per_feed items, so every page is read
        # before `complete` is decided (a partial read would mark a feed done while later items still process).
        data: dict = {}
        raw_items: list[dict] = []
        offset = 0
        while True:
            page = self._request("GET", f"/v3/feeds/{batch_id}",
                                 params={"includeDetails": "true", "limit": str(STATUS_PAGE_SIZE), "offset": str(offset)}).json()
            if not data:
                data = page
            chunk = (page.get("itemDetails") or {}).get("itemIngestionStatus", []) or []
            raw_items.extend(chunk)
            offset += len(chunk)
            received = page.get("itemsReceived")
            if len(chunk) < STATUS_PAGE_SIZE or (isinstance(received, int) and offset >= received):
                break
        items = []
        for it in raw_items:
            raw = str(it.get("ingestionStatus", "")).upper()
            errors = it.get("ingestionErrors", {}).get("ingestionError", []) if isinstance(it.get("ingestionErrors"), dict) else (it.get("ingestionErrors") or [])
            msg = "; ".join(f"{e.get('code', '')}: {e.get('description', '')}".strip(": ") for e in errors if isinstance(e, dict))
            items.append({"external_id": it.get("sku"), "status": ITEM_STATUS_MAP.get(raw, "in_review"), "message": msg,
                          "field": (errors[0].get("field") if errors and isinstance(errors[0], dict) else None), "wpid": it.get("wpid"),
                          "raw_status": raw})
        feed_status = str(data.get("feedStatus", "")).upper()
        in_progress = sum(1 for i in items if i["status"] == "in_review")
        return {"batch_id": batch_id, "status": feed_status, "items": items, "items_received": data.get("itemsReceived"),
                "items_succeeded": data.get("itemsSucceeded"), "items_failed": data.get("itemsFailed"),
                "items_processing": data.get("itemsProcessing", in_progress),
                "error": _feed_error(data) if feed_status in FEED_FAILED_STATUSES else None,
                # PROCESSED and ERROR are both terminal: an ERROR feed is never polled again, its items are rejected
                "complete": feed_status in FEED_TERMINAL_STATUSES and in_progress == 0}

    def fetch_errors(self, batch_id: str) -> list[dict]:
        return [i for i in self.fetch_status(batch_id)["items"] if i["status"] == "rejected"]

    def listing_quality(self, skus: list[str]) -> dict[str, float]:
        """Listing Quality score per item [C15]. Endpoint shape UNCONFIRMED against a live account; failures are
        logged and leave the health view without scores rather than failing the poll."""
        out: dict[str, float] = {}
        for start in range(0, len(skus), LISTING_QUALITY_BATCH):  # every SKU is scored, 200 per request
            chunk = skus[start:start + LISTING_QUALITY_BATCH]
            try:
                data = self._request("POST", "/v3/insights/items/listingQuality/items", json={"skus": chunk}).json()
            except Exception as exc:  # noqa: BLE001
                log.warning("listing quality unavailable: %s", exc)
                return out
            payload = data.get("payload", data)
            for it in payload if isinstance(payload, list) else payload.get("items", []) or []:
                sku = it.get("sku")
                score = (it.get("itemQualityScore") or it.get("qualityScore") or {})
                val = score.get("score") if isinstance(score, dict) else score
                if sku and val is not None:
                    try:
                        out[str(sku)] = float(val)
                    except (TypeError, ValueError):
                        continue
        return out


def _deep_get(d: dict, key: str) -> Any:
    for k, v in d.items():
        if k == key:
            return v
        if isinstance(v, dict):
            found = _deep_get(v, key)
            if found is not None:
                return found
    return None
