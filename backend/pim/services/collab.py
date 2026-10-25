"""DM-09 comments with @mentions and in-app notifications; DM-07 and DM-09 email digest. The digest goes out through
the SMTP settings the EXP-09 email transport uses (PIM_SMTP_*); without them it logs what it would send."""

from __future__ import annotations

import logging
import re
import smtplib
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.config import get_settings
from pim.models import Comment, Notification, ProductEntity, UserSetting
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


DIGEST_FREQUENCIES = ("daily", "weekly", "off")


def user_setting(session: Session, email: str) -> UserSetting:
    us = session.get(UserSetting, email.lower())
    if us is None:
        us = UserSetting(email=email.lower(), digest_frequency="daily")
        session.add(us)
        session.flush()
    return us


def set_digest_frequency(session: Session, email: str, frequency: str) -> UserSetting:
    if frequency not in DIGEST_FREQUENCIES:
        raise ValueError("digest_frequency must be daily, weekly or off")
    us = user_setting(session, email)
    us.digest_frequency = frequency
    session.flush()
    return us


def digest_due(us: UserSetting | None, now) -> bool:  # noqa: ANN001
    freq = us.digest_frequency if us else "daily"
    if freq == "off":
        return False
    if freq == "weekly" and us is not None and us.last_digest_at and now - us.last_digest_at < timedelta(days=7):
        return False
    return True


def compose_digest(email: str, notes: list[Notification], base_url: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Swim USA PIM: {len(notes)} new notification{'s' if len(notes) != 1 else ''}"
    msg["To"] = email
    lines = [f"You have {len(notes)} new notification{'s' if len(notes) != 1 else ''} in the Swim USA PIM.", ""]
    by_kind: dict[str, list[Notification]] = {}
    for n in notes:
        by_kind.setdefault(n.kind, []).append(n)
    for kind, group in by_kind.items():
        lines.append(f"{kind.replace('_', ' ').title()} ({len(group)})")
        for n in group[:25]:
            link = f"{base_url.rstrip('/')}{n.link}" if base_url and n.link else (n.link or "")
            lines.append(f"  - {n.title}" + (f" ({n.body[:120]})" if n.body else "") + (f"\n    {link}" if link else ""))
        if len(group) > 25:
            lines.append(f"  and {len(group) - 25} more")
        lines.append("")
    lines.append("Change how often you get this digest from the bell menu in the PIM.")
    msg.set_content("\n".join(lines))
    return msg


def send_digest(session: Session, smtp_factory=None, now=None) -> dict[str, int]:  # noqa: ANN001
    """DM-07, DM-09: one email per user with everything not yet emailed, honoring the user's daily, weekly or off
    setting. With no SMTP host and no factory this logs and marks the notifications emailed (the Phase 2 seam)."""
    s = get_settings()
    now = now or utcnow()
    pending = session.execute(select(Notification).where(Notification.emailed_at.is_(None)).order_by(Notification.created_at)).scalars().all()
    by_user: dict[str, list[Notification]] = {}
    for n in pending:
        by_user.setdefault(n.user_email, []).append(n)
    settings = {u.email: u for u in session.execute(select(UserSetting).where(UserSetting.email.in_(list(by_user)))).scalars()} if by_user else {}
    sent: dict[str, int] = {}
    can_send = smtp_factory is not None or bool(s.smtp_host)
    for email, notes in by_user.items():
        us = settings.get(email)
        if not digest_due(us, now):
            continue
        if can_send:
            msg = compose_digest(email, notes, s.app_base_url)
            msg["From"] = s.smtp_from or s.smtp_user or "pim@swimusa.com"
            factory = smtp_factory or (lambda: smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30))
            try:
                with factory() as smtp:
                    if smtp_factory is None:
                        smtp.starttls()
                        if s.smtp_user:
                            smtp.login(s.smtp_user, s.smtp_password or "")
                    smtp.send_message(msg)
            except Exception:  # noqa: BLE001
                log.exception("digest to %s failed; notifications stay queued for the next run", email)
                continue
        else:
            log.info("digest for %s: %d notification(s): %s", email, len(notes), "; ".join(n.title for n in notes[:10]))
        for n in notes:
            n.emailed_at = now
        if us is None:
            us = user_setting(session, email)
        us.last_digest_at = now
        sent[email] = len(notes)
    session.flush()
    return sent
