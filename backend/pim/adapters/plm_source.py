"""Yunique PLM source: intentionally NOT ingested in v1 (D-08, IMP-09 v1.2). Kept behind the source adapter
interface so it can be added later as a read-only reference for styles still in development."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from pim.adapters.base import NotConfigured


class PlmSource:
    name = "yunique_plm"

    def read_changes(self, since: datetime | None = None) -> Iterator[dict[str, Any]]:
        raise NotConfigured("TODO(decision: D-08 follow-up): PLM is not a source in v1")
