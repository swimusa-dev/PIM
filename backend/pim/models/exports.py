"""Phase 3 export and image tables: publish items and retailer feedback (EXP-05), eligibility overrides (EXP-12),
image renditions (IMG-07)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pim.db.session import Base
from pim.models._common import IdMixin, utcnow


class PublishItem(Base, IdMixin):
    __tablename__ = "publish_item"
    __table_args__ = (Index("ix_publish_item_publish", "publish_id", "status"), Index("ix_publish_item_entity", "entity_id"))
    publish_id: Mapped[str] = mapped_column(ForeignKey("publish_record.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | valid | invalid | submitted | accepted | rejected | in_review
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    issues: Mapped[list] = mapped_column(JSON, default=list)  # validation issues before sending
    errors: Mapped[list] = mapped_column(JSON, default=list)  # retailer feedback, tagged internal / external
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EligibilityOverride(Base, IdMixin):
    """EXP-12: forcing an ineligible product into a channel needs PIM Admin approval with a logged reason."""

    __tablename__ = "eligibility_override"
    __table_args__ = (UniqueConstraint("entity_id", "channel_code"), Index("ix_override_channel", "channel_code"))
    entity_id: Mapped[str] = mapped_column(ForeignKey("product_entity.id", ondelete="CASCADE"), nullable=False)
    channel_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImageRendition(Base, IdMixin):
    """IMG-07: a channel derivative URL cached per asset version and channel profile; never a stored copy."""

    __tablename__ = "image_rendition"
    __table_args__ = (UniqueConstraint("asset_id", "version_id", "channel_code", "profile_hash"),)
    asset_id: Mapped[str] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_code: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format: Mapped[str] = mapped_column(String(8), default="jpg")
    source: Mapped[str] = mapped_column(String(16), default="air_cdn")  # air_cdn | job | pending
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
