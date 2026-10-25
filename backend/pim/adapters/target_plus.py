"""Target+ item rules (EXP-11). D-02 resolved on 2026-10-25: Target+ goes through Rithum, the same connection as
Nordstrom, so the feed itself is `adapters/rithum.py` (program `targetplus`). This module keeps the family-level
validation entry point (one invalid child fails the family) for callers that only need the rules."""

from __future__ import annotations

from collections.abc import Iterable

from pim.adapters.base import NotConfigured, PublishResult, ValidationResult
from pim.adapters.rithum import RithumFeedAdapter

TITLE_MAX = 150  # UNCONFIRMED vendor source [C17]


class TargetPlusAdapter:
    name = "target_plus"

    def __init__(self) -> None:
        self._rithum = RithumFeedAdapter(program="targetplus", family_rules=True)

    def validate(self, payload: Iterable[dict]) -> ValidationResult:
        rows = list(payload)
        errors = self._rithum._family_errors(rows)
        return ValidationResult(ok=not errors, errors=errors)

    def publish(self, batch: list[dict], dry_run: bool = False) -> PublishResult:
        if dry_run:
            return PublishResult(batch_id="dry-run", accepted=len(batch), status="dry_run")
        raise NotConfigured("Target+ is delivered as a Rithum flat file (D-02): set the channel adapter to rithum")

    def fetch_status(self, batch_id: str) -> dict:
        return {"batch_id": batch_id, "status": "n/a (Rithum flat file, D-02); upload Rithum's error report as feedback"}

    def fetch_errors(self, batch_id: str) -> list[dict]:
        return []
