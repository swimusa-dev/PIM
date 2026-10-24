"""Walmart Marketplace adapter (EXP-08) [C8][C9][C12][C14][C15]. Phase 5. Skeleton with the documented
mechanics in place: MP_ITEM feed shape, spec pinning, feed status polling cadence, status mapping."""

from __future__ import annotations

from collections.abc import Iterable

from pim.adapters.base import NotConfigured, PublishResult, ValidationResult

POLL_CADENCE_MINUTES = [15, 60, 120, 240]  # then every 4 hours [C14]


class WalmartMarketplaceAdapter:
    name = "walmart_mp"

    def __init__(self, client_id: str | None = None, client_secret: str | None = None, spec_version: str = "5.0",
                 max_items_per_feed: int = 5000) -> None:
        self.client_id, self.client_secret = client_id, client_secret
        self.spec_version = spec_version
        self.max_items = max_items_per_feed

    def build_feed(self, items: list[dict]) -> list[dict]:
        """Split items into MP_ITEM feeds with header, Orderable and Visible sections [C8]."""
        feeds = []
        for i in range(0, len(items), self.max_items):
            feeds.append({
                "MPItemFeedHeader": {"sellingChannel": "mpsetupbymatch", "processMode": "REPLACE",
                                     "subset": "EXTERNAL", "locale": "en", "version": self.spec_version},
                "MPItem": [{"Orderable": it.get("orderable", {}), "Visible": it.get("visible", {})} for it in items[i:i + self.max_items]],
            })
        return feeds

    def validate(self, payload: Iterable[dict]) -> ValidationResult:
        errors = []
        groups: dict[str, list[dict]] = {}
        for it in payload:
            vg = it.get("orderable", {}).get("variantGroupId")
            if vg:
                groups.setdefault(vg, []).append(it)
        for vg, items in groups.items():
            names = {tuple(sorted(i.get("orderable", {}).get("variantAttributeNames", []))) for i in items}
            if len(names) > 1:
                errors.append({"variantGroupId": vg, "message": "variantAttributeNames differ within the group"})
            if any(len(n) > 3 for n in names):
                errors.append({"variantGroupId": vg, "message": "more than 3 variant attributes"})
            if sum(1 for i in items if i.get("orderable", {}).get("isPrimaryVariant")) != 1:
                errors.append({"variantGroupId": vg, "message": "exactly one isPrimaryVariant required"})
        return ValidationResult(ok=not errors, errors=errors)

    def publish(self, batch: list[dict], dry_run: bool = False) -> PublishResult:
        if dry_run:
            return PublishResult(batch_id="dry-run", accepted=len(batch), status="dry_run",
                                 detail={"feeds": len(self.build_feed(batch))})
        if not self.client_id:
            raise NotConfigured("Walmart credentials not bound (GOV-05)")
        raise NotImplementedError("Phase 5: POST /v3/feeds?feedType=MP_ITEM")

    def fetch_status(self, batch_id: str) -> dict:
        raise NotImplementedError("Phase 5: GET /v3/feeds/{feedId}?includeDetails=true")

    def fetch_errors(self, batch_id: str) -> list[dict]:
        raise NotImplementedError("Phase 5")
