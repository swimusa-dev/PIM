"""DM-13 product relationships (v1.1, narrowed in v1.3): admin-defined relationship types and product-to-product links.

Layer owns Shopify cross-sell data (D-09), so no Shopify metafield is written from these rows; they feed retailer
and marketplace channels through the `related:<type>` feed source (EXP-09) and are checked in readiness (EXP-03)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pim.db.session import Base
from pim.models._common import IdMixin, utcnow


class RelationshipType(Base):
    """Seeded from seeds/relationships.yml; editable under Admin. `direction` one_way or two_way; `level` style or
    style_color decides which entities may be linked; `allows_quantity` for sets."""

    __tablename__ = "relationship_type"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), default="one_way")  # one_way | two_way
    level: Mapped[str] = mapped_column(String(16), default="style_color")  # style | style_color
    allows_quantity: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    help_text: Mapped[str | None] = mapped_column(String(300), nullable=True)


class ProductRelationship(Base, IdMixin):
    """One directed link. A two-way type stores both directions (the reverse row carries `mirror_of`)."""

    __tablename__ = "product_relationship"
    __table_args__ = (
        UniqueConstraint("type_code", "from_entity_id", "to_entity_id", name="uq_relationship"),
        Index("ix_relationship_from", "from_entity_id"),
        Index("ix_relationship_to", "to_entity_id"),
    )
    type_code: Mapped[str] = mapped_column(ForeignKey("relationship_type.code"), nullable=False)
    from_entity_id: Mapped[str] = mapped_column(ForeignKey("product_entity.id", ondelete="CASCADE"), nullable=False)
    to_entity_id: Mapped[str] = mapped_column(ForeignKey("product_entity.id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mirror_of: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
