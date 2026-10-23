"""Air DAM adapter (IMG-01, IMG-06, IMG-07) [C29][C30][C31][C32].

- API key + workspace id from app secret resources (GOV-05).
- 15 requests/second and 10 concurrent per key: a simple token bucket plus exponential backoff on 429.
- No webhooks and no updatedSince filter: polling is scoped by board and creation date.
- Semantic search (`semantic=true`) is UNCONFIRMED for our workspace; `search_assets` exposes the flag.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx

from pim.adapters.base import NotConfigured
from pim.config import get_settings

log = logging.getLogger(__name__)


class _RateLimiter:
    def __init__(self, per_second: float = 12.0) -> None:
        self.interval = 1.0 / per_second
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next:
                time.sleep(self._next - now)
            self._next = max(now, self._next) + self.interval


class AirClient:
    name = "air_dam"

    def __init__(self, api_key: str | None = None, workspace_id: str | None = None, base_url: str | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        s = get_settings()
        self.api_key = api_key or s.air_api_key
        self.workspace_id = workspace_id or s.air_workspace_id
        self.base_url = (base_url or s.air_base_url).rstrip("/")
        if not self.api_key:
            raise NotConfigured("PIM_AIR_API_KEY is not set (bind the air-api-key secret resource)")
        self._client = httpx.Client(base_url=self.base_url, timeout=30.0, transport=transport,
                                    headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"})
        self._limiter = _RateLimiter()

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        delay = 1.0
        for _attempt in range(6):
            self._limiter.wait()
            resp = self._client.request(method, path, **kw)
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = float(resp.headers.get("Retry-After", delay))
                log.warning("Air %s %s -> %s, retrying in %.1fs", method, path, resp.status_code, retry_after)
                time.sleep(retry_after)
                delay = min(delay * 2, 30)
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError(f"Air API kept failing: {method} {path}")

    # ---- reads -------------------------------------------------------------------------------------
    def list_assets(self, board_id: str | None = None, created_after: datetime | None = None,
                    limit: int = 500) -> Iterator[dict]:
        """Pages through /v1/assets (500 max per call) scoped by board and creation date."""
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": limit}
            if self.workspace_id:
                params["workspaceId"] = self.workspace_id
            if board_id:
                params["boardId"] = board_id
            if created_after:
                params["createdAfter"] = created_after.isoformat()
            if cursor:
                params["cursor"] = cursor
            data = self._request("GET", "/v1/assets", params=params).json()
            yield from data.get("data", data.get("assets", []))
            cursor = (data.get("pagination") or {}).get("cursor") or data.get("nextCursor")
            if not cursor:
                break

    def search_assets(self, query: str, board_id: str | None = None, semantic: bool = True, limit: int = 20) -> list[dict]:
        params: dict[str, Any] = {"q": query, "semantic": str(semantic).lower(), "limit": limit}
        if self.workspace_id:
            params["workspaceId"] = self.workspace_id
        if board_id:
            params["boardId"] = board_id
        return self._request("GET", "/v1/assets/search", params=params).json().get("data", [])

    # ---- writes (IMG-06) -----------------------------------------------------------------------------
    def set_custom_fields(self, asset_id: str, fields: dict[str, Any]) -> None:
        self._request("PATCH", f"/v1/assets/{asset_id}/custom-fields", json={"fields": fields})

    # ---- renditions (IMG-07) -------------------------------------------------------------------------
    def cdn_url(self, asset_id: str, width: int | None = None, height: int | None = None, fmt: str = "jpg") -> str:
        data = self._request("POST", f"/v1/assets/{asset_id}/cdn-links",
                             json={"transform": {"width": width, "height": height, "format": fmt}}).json()
        return data.get("url") or data.get("data", {}).get("url", "")


def normalize_asset(item: dict) -> dict:
    """Map an Air asset payload to our `asset` table columns. Field names follow Air's public API; adjust once
    PLT-00 step 10 runs against the real workspace."""
    custom = {}
    for cf in item.get("customFields", []) or []:
        name = cf.get("name") or cf.get("fieldName") or cf.get("id")
        custom[str(name)] = cf.get("value") if "value" in cf else cf.get("values")
    if isinstance(item.get("customFields"), dict):
        custom = item["customFields"]
    boards = item.get("boards") or []
    board_path = " / ".join(b.get("title", "") for b in boards) if isinstance(boards, list) else str(boards)
    return {
        "id": str(item.get("id")),
        "version_id": str(item.get("versionId") or item.get("version", {}).get("id") or ""),
        "filename": item.get("title") or item.get("filename") or item.get("name") or "",
        "board_path": board_path or None,
        "tags": [t.get("label", t) if isinstance(t, dict) else t for t in item.get("tags", []) or []],
        "custom_fields": custom,
        "smart_tags": [t.get("label", t) if isinstance(t, dict) else t for t in item.get("smartTags", []) or []],
        "width": item.get("width") or (item.get("dimensions") or {}).get("width"),
        "height": item.get("height") or (item.get("dimensions") or {}).get("height"),
        "thumbnail_url": item.get("thumbnailUrl") or (item.get("thumbnail") or {}).get("url"),
        "air_created_at": _parse_dt(item.get("createdAt")),
    }


def _parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
