"""DM-09 comments with @mentions and in-app notifications. Email delivery is a seam: `send_digest` logs what it
would send until an email adapter is configured."""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.config import get_settings
from pim.models import Comment, Notification, ProductEntity
from pim.models._common import utcnow

log = logging.getLogger(__name__)
MENTION_RE = re.compile(r"@([A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|[A-Za-z0-9._-]+)")


def parse_mentions(body: str) -> list[str]:
    domain = getattr(get_settings(), "mention_domain", "swimusa.com")
    out: list[str] = []
    for m in MENTION_RE.findall(body or ""):
        email = m.lower() if "@" in m else f"{m.lower()}@{domain}"
        if email not in out:
            out.append(email)
    return out


def notify(session: Session, email: str, kind: str, title: str, body: str | None = None, link: str | None = None) -> Notification:
    n = Notification(user_email=email.lower(), kind=kind, title=title[:300], body=body, link=link)
    session.add(n)
    return n


def add_comment(session: Session, author: str, ent: ProductEntity, body: str, attribute_code: str | None = None) -> Comment:
    mentions = parse_mentions(body)
    c = Comment(entity_id=ent.id, attribute_code=attribute_code, author=author, body=body, mentions=mentions)
    session.add(c)
    for email in mentions:
        if email != author:
            notify(session, email, "mention", f"{author} mentioned you on {ent.label}", body[:500], f"/products/{ent.id}")
    return c


def comments_for(session: Session, ent: ProductEntity) -> list[Comment]:
    ids = [ent.id] + ([ent.parent_id] if ent.parent_id else [])
    return session.execute(select(Comment).where(Comment.entity_id.in_(ids)).order_by(Comment.created_at.desc())).scalars().all()


def mark_read(session: Session, email: str, ids: list[str] | None) -> int:
    q = select(Notification).where(Notification.user_email == email.lower(), Notification.read_at.is_(None))
    if ids:
        q = q.where(Notification.id.in_(ids))
    n = 0
    for note in session.execute(q).scalars():
        note.read_at = utcnow()
        n += 1
    return n


def send_digest(session: Session) -> dict[str, int]:
    """Daily or weekly email digest (DM-07, DM-09). Without an email adapter this logs and marks notifications emailed."""
    pending = session.execute(select(Notification).where(Notification.emailed_at.is_(None))).scalars().all()
    by_user: dict[str, list[Notification]] = {}
    for n in pending:
        by_user.setdefault(n.user_email, []).append(n)
    for email, notes in by_user.items():
        log.info("digest for %s: %d notification(s): %s", email, len(notes), "; ".join(n.title for n in notes[:10]))
        for n in notes:
            n.emailed_at = utcnow()
    return {u: len(v) for u, v in by_user.items()}
