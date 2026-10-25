"""Comments and notifications (DM-09)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pim.db.session import Base
from pim.models._common import IdMixin, utcnow


class Comment(Base, IdMixin):
    __tablename__ = "comment"
    __table_args__ = (Index("ix_comment_entity", "entity_id", "created_at"),)
    entity_id: Mapped[str] = mapped_column(ForeignKey("product_entity.id", ondelete="CASCADE"), nullable=False)
    attribute_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    mentions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict)  # workflow rejection, step, etc.


class Notification(Base, IdMixin):
    __tablename__ = "notification"
    __table_args__ = (Index("ix_notification_user", "user_email", "read_at"),)
    user_email: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSetting(Base):
    """Per-user preferences (DM-07, DM-09): how often the notification digest is emailed."""

    __tablename__ = "user_setting"
    email: Mapped[str] = mapped_column(String(200), primary_key=True)
    digest_frequency: Mapped[str] = mapped_column(String(8), default="daily")  # daily | weekly | off
    last_digest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
