"""GOV-04 operational telemetry helpers: adapter errors as structured app events (never with credentials), and the
error rate per adapter over a window for the admin page."""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.models import AppEvent, PublishRecord
from pim.models._common import utcnow

log = logging.getLogger(__name__)
_SECRET_RE = re.compile(r"(?i)\b([a-z_\-]*(?:token|secret|password|passwd|authorization|api[_-]?key|apikey)[a-z_\-]*)\s*[:=]\s*(?:bearer\s+|basic\s+)?\S+")
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{8,}")


def scrub(text: str) -> str:
    """Drop anything that looks like a credential from an error string (GOV-05): `key=value`, `key: value`,
    `Authorization: Bearer x` and bare `Bearer x` forms all lose the value."""
    s = _SECRET_RE.sub(lambda m: f"{m.group(1)}=<redacted>", str(text))
    s = _BEARER_RE.sub(lambda m: f"{m.group(1)} <redacted>", s)
    return s[:1000]


def record_adapter_error(session: Session, adapter: str, error: str | Exception, context: dict | None = None,
                         request_id: str | None = None, user_email: str | None = None) -> AppEvent:
    ev = AppEvent(kind="adapter_error", source=adapter, request_id=request_id, user_email=user_email,
                  payload={"error": scrub(str(error)), **{k: (str(v)[:200] if v is not None else None) for k, v in (context or {}).items()}})
    session.add(ev)
    log.warning("adapter_error %s: %s", adapter, scrub(str(error)))
    return ev


def adapter_error_rates(session: Session, days: int = 30) -> list[dict]:
    """Per channel (the event source is the channel code; the adapter name rides in the payload): publish attempts
    versus failures over the window. Sources without publish records (the Air poll) list their errors with no rate."""
    since = utcnow() - timedelta(days=days)
    recs = session.execute(select(PublishRecord).where(PublishRecord.created_at >= since,
                                                       PublishRecord.kind.in_(["publish", "scheduled", "package"]))).scalars().all()
    events = session.execute(select(AppEvent).where(AppEvent.kind == "adapter_error", AppEvent.at >= since)).scalars().all()
    calls: Counter = Counter()
    failed: Counter = Counter()
    last_error: dict[str, dict] = {}
    for r in recs:
        adapter = r.channel_code
        calls[adapter] += 1
        if r.status == "failed":
            failed[adapter] += 1
    errors_by_adapter: Counter = Counter()
    for e in events:
        src = e.source or "unknown"
        errors_by_adapter[src] += 1
        if src not in last_error or e.at > last_error[src]["at_dt"]:
            last_error[src] = {"at": e.at.isoformat(), "at_dt": e.at, "message": str((e.payload or {}).get("error", ""))[:300]}
    adapters = sorted(set(calls) | set(errors_by_adapter))
    out = []
    for a in adapters:
        n_calls = calls[a]
        n_err = max(failed[a], errors_by_adapter[a]) if n_calls else errors_by_adapter[a]
        out.append({"adapter": a, "window_days": days, "calls": n_calls, "errors": n_err,
                    "error_rate": round(min(n_err, n_calls) / n_calls, 3) if n_calls else None,
                    "last_error_at": last_error.get(a, {}).get("at"), "last_error": last_error.get(a, {}).get("message")})
    return out
