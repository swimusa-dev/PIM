"""Mirakl seller API adapter (EXP-10 alternative path) [C23][C24]. D-01 resolved on 2026-10-25: Nordstrom goes
through Rithum drop-ship, so this path is not built. The documented endpoints stay named so the schema loader
(EXP-02, Mirakl H11/PM11/VL11 files) and a future marketplace channel have a home; every call reports that."""

from __future__ import annotations

from collections.abc import Iterable

from pim.adapters.base import NotConfigured, PublishResult, ValidationResult

ENDPOINTS = {"hierarchies": "H11", "attributes": "PM11", "value_lists": "VL11", "import": "P41",
             "import_status": "P42", "non_integrated_report": "P44", "transformation_errors": "P47"}
MIN_IMPORT_INTERVAL_MINUTES = 15  # no more often than every 15 minutes; hourly recommended
NOT_BUILT = "Mirakl marketplace path not built: Nordstrom goes through Rithum drop-ship (D-01, 2026-10-25)"


class MiraklSellerAdapter:
    name = "mirakl_seller"

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url, self.api_key = base_url, api_key

    def load_target_schema(self) -> dict:
        raise NotConfigured(NOT_BUILT)

    def validate(self, payload: Iterable[dict]) -> ValidationResult:
        return ValidationResult(ok=True)

    def publish(self, batch: list[dict], dry_run: bool = False) -> PublishResult:
        if dry_run:
            return PublishResult(batch_id="dry-run", accepted=len(batch), status="dry_run")
        raise NotConfigured(NOT_BUILT)

    def fetch_status(self, batch_id: str) -> dict:
        raise NotConfigured(NOT_BUILT)

    def fetch_errors(self, batch_id: str) -> list[dict]:
        raise NotConfigured(NOT_BUILT)
