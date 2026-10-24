"""Target+ adapter stub (EXP-11). No public developer docs exist; the integrator defines the format
(TODO(decision: D-02)). Validation checks a parent/child family as a unit (one invalid child fails the family)."""

from __future__ import annotations

from collections.abc import Iterable

from pim.adapters.base import NotConfigured, PublishResult, ValidationResult

TITLE_MAX = 150  # UNCONFIRMED vendor source [C17]


class TargetPlusAdapter:
    name = "target_plus"

    def validate(self, payload: Iterable[dict]) -> ValidationResult:
        errors = []
        families: dict[str, list[dict]] = {}
        for it in payload:
            families.setdefault(it.get("family_id", it.get("handle", "")), []).append(it)
        for fam, items in families.items():
            bad = [i for i in items if len(i.get("title", "")) > TITLE_MAX or not i.get("upc")]
            if bad:
                errors.append({"family": fam, "message": f"{len(bad)} child item(s) invalid; whole family fails"})
        return ValidationResult(ok=not errors, errors=errors)

    def publish(self, batch: list[dict], dry_run: bool = False) -> PublishResult:
        if dry_run:
            return PublishResult(batch_id="dry-run", accepted=len(batch), status="dry_run")
        raise NotConfigured("TODO(decision: D-02): Target+ integrator not chosen")

    def fetch_status(self, batch_id: str) -> dict:
        raise NotConfigured("TODO(decision: D-02)")

    def fetch_errors(self, batch_id: str) -> list[dict]:
        raise NotConfigured("TODO(decision: D-02)")
