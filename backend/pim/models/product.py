"""Product hierarchy (DM-01), EAV values with provenance (ARC-03), drafts (DM-08), history (GOV-02)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pim.db.session import Base
from pim.models._common import IdMixin, TimestampMixin, new_id, utcnow

SOURCE_TYPES = ("erp", "import", "user", "ai", "rule", "default")
APPROVAL_STATES = ("draft", "proposed", "approved", "rejected")


class ProductEntity(Base, IdMixin, TimestampMixin):
    """One row per style, style-color, or SKU. Prepacks are entities too (entity_type = prepack)."""

    __tablename__ = "product_entity"
    __table_args__ = (
        UniqueConstraint("level", "style_number", "color_code", "size", name="uq_entity_keys"),
        Index("ix_entity_level_style", "level", "style_number"),
        Index("ix_entity_parent", "parent_id"),
        Index("ix_entity_sku", "sku"),
        Index("ix_entity_upc", "upc"),
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), default="product")  # product | prepack
    style_number: Mapped[str] = mapped_column(String(64), nullable=False)
    color_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    upc: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("product_entity.id"), nullable=True)
    family_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(16), default="active")  # new | active | discontinued
    brand_scopes: Mapped[list] = mapped_column(JSON, default=list)  # RBAC-04
    brand_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)  # EXP-12
    erp_fields: Mapped[dict] = mapped_column(JSON, default=dict)  # raw ERP row subset (division, sub-division...)
    label: Mapped[str] = mapped_column(String(300), default="")
    launch_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # Ecomm launch date (DM-10)
    erp_last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    size_unmapped: Mapped[bool] = mapped_column(Boolean, default=False)  # DM-14 flag

    parent: Mapped[ProductEntity | None] = relationship(remote_side="ProductEntity.id", backref="children")
    aliases: Mapped[list[IdentifierAlias]] = relationship(cascade="all, delete-orphan", back_populates="entity")


class PrepackComponent(Base):
    __tablename__ = "prepack_component"
    prepack_id: Mapped[str] = mapped_column(ForeignKey("product_entity.id", ondelete="CASCADE"), primary_key=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("product_entity.id", ondelete="CASCADE"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)


class IdentifierAlias(Base):
    """DM-01 (F7): every known identifier format for an entity, normalized for matching."""

    __tablename__ = "identifier_alias"
    __table_args__ = (
        UniqueConstraint("alias_type", "normalized", name="uq_alias"),
        Index("ix_alias_normalized", "normalized"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_id: Mapped[str] = mapped_column(ForeignKey("product_entity.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    alias_type: Mapped[str] = mapped_column(String(32), nullable=False)  # style, style_color, sku, upc, gms, image_relay, legacy
    normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="erp")
    entity: Mapped[ProductEntity] = relationship(back_populates="aliases")


class ChangeSet(Base):
    """A reversible unit of change: an import batch, a bulk action, an AI run, a single edit (GOV-02, IMP-07)."""

    __tablename__ = "change_set"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # edit | import | bulk | ai | ingest | rule | restore
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProductValue(Base):
    """ARC-03 EAV row. A null channel_code is the global value; non-null is a channel override."""

    __tablename__ = "product_value"
    __table_args__ = (
        UniqueConstraint("entity_level", "entity_id", "attribute_code", "channel_code", "locale", name="uq_value"),
        Index("ix_value_entity", "entity_id"),
        Index("ix_value_attr", "attribute_code"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_level: Mapped[str] = mapped_column(String(64), nullable=False)  # style | style_color | sku | ref:<type>
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attribute_code: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")  # "" = global
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    # typed columns
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_number: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    value_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)  # multi-select, references
    value_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)  # reference entity / product id
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # IMP-11 ERP raw next to normalized
    not_applicable: Mapped[bool] = mapped_column(Boolean, default=False)  # IMP-10
    # provenance (P2)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    set_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_template_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_state: Mapped[str] = mapped_column(String(16), default="approved")
    version: Mapped[int] = mapped_column(Integer, default=1)
    change_set_id: Mapped[str | None] = mapped_column(ForeignKey("change_set.id"), nullable=True)
    confirmed_default: Mapped[bool] = mapped_column(Boolean, default=False)  # GOV-06


class ValueDraft(Base):
    """DM-08: edits by users with Edit but not Approve rights, and AI proposals (AI-03), awaiting approval."""

    __tablename__ = "value_draft"
    __table_args__ = (Index("ix_draft_entity", "entity_id"), Index("ix_draft_state", "state"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_level: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attribute_code: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_code: Mapped[str] = mapped_column(String(64), default="")
    proposed: Mapped[dict] = mapped_column(JSON, nullable=False)  # {"value": ..., "not_applicable": bool}
    source_type: Mapped[str] = mapped_column(String(16), default="user")
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    submitted_by: Mapped[str] = mapped_column(String(200), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    state: Mapped[str] = mapped_column(String(16), default="draft")  # draft | proposed | approved | rejected
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class ValueHistory(Base):
    """GOV-02 field-level audit: old, new, source, who, change set, when. Kept 2 years hot (configurable)."""

    __tablename__ = "value_history"
    __table_args__ = (Index("ix_history_entity", "entity_id", "attribute_code"), Index("ix_history_at", "set_at"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_level: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attribute_code: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_code: Mapped[str] = mapped_column(String(64), default="")
    old_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    set_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    change_set_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ReferenceEntity(Base, IdMixin, TimestampMixin):
    """DM-11 record (Print, Fabric, Model profile). Its values live in product_value with entity_level = ref:<type>."""

    __tablename__ = "reference_entity"
    __table_args__ = (UniqueConstraint("type_code", "code"),)
    type_code: Mapped[str] = mapped_column(ForeignKey("reference_entity_type.code"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    certificate_refs: Mapped[list] = mapped_column(JSON, default=list)  # AI-06 certificate records for Fabric


class ReadinessSnapshot(Base):
    """EXP-03 / DM-05 cache: completeness and readiness per entity and channel, recomputed on value change
    and by the nightly job, so grids can filter and sort on it server-side (DM-02)."""

    __tablename__ = "readiness_snapshot"
    __table_args__ = (Index("ix_readiness_channel_ready", "channel_code", "ready"),)
    entity_id: Mapped[str] = mapped_column(ForeignKey("product_entity.id", ondelete="CASCADE"), primary_key=True)
    channel_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    completeness_pct: Mapped[int] = mapped_column(Integer, default=0)
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
