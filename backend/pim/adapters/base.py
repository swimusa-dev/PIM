from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class SourceAdapter(Protocol):
    name: str

    def read_changes(self, since: datetime | None = None) -> Iterator[dict[str, Any]]: ...


@dataclass
class ValidationResult:
    ok: bool
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)


@dataclass
class PublishResult:
    batch_id: str
    accepted: int = 0
    rejected: int = 0
    status: str = "submitted"
    detail: dict = field(default_factory=dict)


class ChannelAdapter(Protocol):
    name: str

    def validate(self, payload: Iterable[dict]) -> ValidationResult: ...
    def publish(self, batch: list[dict], dry_run: bool = False) -> PublishResult: ...
    def fetch_status(self, batch_id: str) -> dict: ...
    def fetch_errors(self, batch_id: str) -> list[dict]: ...


class NotConfigured(RuntimeError):
    """Raised when an adapter is used before its decision or credentials exist (Section 11)."""
