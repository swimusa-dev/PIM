"""Mirakl seller API adapter for Nordstrom Marketplace (EXP-10, path decision D-01) [C23][C24]. Phase 5 stub
with the documented endpoints named so the schema loader (EXP-02) and feedback loop (EXP-05) have a home."""

from __future__ import annotations

from collections.abc import Iterable

from pim.adapters.base import NotConfigured, PublishResult, ValidationResult

ENDPOINTS = {"hierarchies": "H11", "attributes": "PM11", "value_lists": "VL11", "import": "P41",
             "import_status": "P42", "non_integrated_report": "P44", "transformation_errors": "P47"}
MIN_IMPORT_INTERVAL_MINUTES = 15  # no more often than every 15 minutes; hourly recommended


class MiraklSellerAdapter:
    name = "mirakl_seller"

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url, self.api_key = base_url, api_key

    def load_target_schema(self) -> dict:
        raise NotConfigured("TODO(decision: D-01): Nordstrom path not decided")

    def validate(self, payload: Iterable[dict]) -> ValidationResult:
        return ValidationResult(ok=True)

    def publish(self, batch: list[dict], dry_run: bool = False) -> PublishResult:
        if dry_run:
            return PublishResult(batch_id="dry-run", accepted=len(batch), status="dry_run")
        raise NotConfigured("TODO(decision: D-01)")

    def fetch_status(self, batch_id: str) -> dict:
        raise NotConfigured("TODO(decision: D-01)")

    def fetch_errors(self, batch_id: str) -> list[dict]:
        raise NotConfigured("TODO(decision: D-01)")
