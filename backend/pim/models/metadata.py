"""Metadata layer (spec 1.3). The attribute model is data, never code (rule 4 in section 0)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pim.db.session import Base
from pim.models._common import TimestampMixin, new_id, utcnow

LEVELS = ("style", "style_color", "sku")
DATA_TYPES = (
    "text",
    "rich_text",
    "number",
    "boolean",
    "date",
    "single_select",
    "multi_select",
    "asset_ref",
    "product_ref",
    "reference_entity",
)
ATTRIBUTE_STATUSES = ("proposed", "confirmed", "deprecated")
SOURCES_OF_TRUTH = ("erp", "plm", "pim", "channel")


class AttributeGroup(Base, TimestampMixin):
    __tablename__ = "attribute_group"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    owning_role: Mapped[str] = mapped_column(String(64), nullable=False, default="pim_admin")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    read_only: Mapped[bool] = mapped_column(Boolean, default=False)  # ERP (read-only) group, P1
    survivorship: Mapped[str] = mapped_column(String(32), default="fill_empty_only")  # IMP-06
    exclude_from_quality: Mapped[bool] = mapped_column(Boolean, default=False)  # GOV-03
    channel_code: Mapped[str | None] = mapped_column(String(64), nullable=True)  # channel-only group

    attributes: Mapped[list[AttributeDefinition]] = relationship(back_populates="group")


class AttributeDefinition(Base, TimestampMixin):
    __tablename__ = "attribute_definition"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    data_type: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(String(64), nullable=False)  # style | style_color | sku | ref:<type>
    group_code: Mapped[str] = mapped_column(ForeignKey("attribute_group.code"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    option_list_code: Mapped[str | None] = mapped_column(ForeignKey("option_list.code"), nullable=True)
    reference_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    channel_scopable: Mapped[bool] = mapped_column(Boolean, default=False)
    allows_not_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    default_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_families: Mapped[list] = mapped_column(JSON, default=list)  # GOV-06 limit default to families
    owner_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    source_of_truth: Mapped[str] = mapped_column(String(16), default="pim")
    help_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    example_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    erp_column: Mapped[str | None] = mapped_column(String(128), nullable=True)  # IMP-09 mapping to Style Master
    not_required_means_na: Mapped[bool] = mapped_column(Boolean, default=False)  # IMP-10
    cost_restricted: Mapped[bool] = mapped_column(Boolean, default=False)  # D-05 masked unless role allowed

    group: Mapped[AttributeGroup] = relationship(back_populates="attributes")
    comments: Mapped[list[AttributeComment]] = relationship(back_populates="attribute")

    @property
    def is_erp(self) -> bool:
        return self.source_of_truth == "erp"


class AttributeComment(Base):
    """Definition questions like the ones written into today's request sheet (F14)."""

    __tablename__ = "attribute_comment"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    attribute_code: Mapped[str] = mapped_column(ForeignKey("attribute_definition.code"), nullable=False)
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    attribute: Mapped[AttributeDefinition] = relationship(back_populates="comments")


class OptionList(Base, TimestampMixin):
    __tablename__ = "option_list"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="option")  # option | size_scale (DM-14)
    size_group: Mapped[str | None] = mapped_column(String(32), nullable=True)  # missy, womens_plus, cup, one_size
    values: Mapped[list[OptionValue]] = relationship(
        back_populates="option_list", cascade="all, delete-orphan", order_by="OptionValue.sort_order"
    )


class OptionValue(Base):
    __tablename__ = "option_value"
    __table_args__ = (UniqueConstraint("list_code", "code"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    list_code: Mapped[str] = mapped_column(ForeignKey("option_list.code", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    channel_mappings: Mapped[dict] = mapped_column(JSON, default=dict)  # channel_code -> channel value
    option_list: Mapped[OptionList] = relationship(back_populates="values")


class ValueMapping(Base):
    """IMP-03 / IMP-11: incoming raw value (per source) -> option code. Remembered per source."""

    __tablename__ = "value_mapping"
    __table_args__ = (UniqueConstraint("source_code", "list_code", "raw_normalized"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False)  # erp | shopify | vendor:<name>
    list_code: Mapped[str] = mapped_column(ForeignKey("option_list.code"), nullable=False)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    raw_normalized: Mapped[str] = mapped_column(String(400), nullable=False)
    option_code: Mapped[str | None] = mapped_column(String(64), nullable=True)  # None = treat as defect
    created_by: Mapped[str] = mapped_column(String(200), default="seed")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PlaceholderToken(Base):
    """IMP-10 placeholder list. Matched case-insensitively after trimming."""

    __tablename__ = "placeholder_token"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    means_not_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Family(Base, TimestampMixin):
    __tablename__ = "family"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    erp_match: Mapped[dict] = mapped_column(JSON, default=dict)  # rule over ERP fields assigning the family
    groups: Mapped[list[FamilyGroup]] = relationship(
        cascade="all, delete-orphan", order_by="FamilyGroup.sort_order"
    )


class FamilyGroup(Base):
    __tablename__ = "family_group"
    family_code: Mapped[str] = mapped_column(ForeignKey("family.code", ondelete="CASCADE"), primary_key=True)
    group_code: Mapped[str] = mapped_column(ForeignKey("attribute_group.code"), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ReferenceEntityType(Base):
    """DM-11: Print, Fabric, Model profile. Attributes for a type use level = 'ref:<code>'."""

    __tablename__ = "reference_entity_type"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    label_attribute: Mapped[str] = mapped_column(String(64), nullable=False)  # attribute used as display label


class ShotType(Base):
    __tablename__ = "shot_type"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ChannelRequirementSet(Base, TimestampMixin):
    """Reusable readiness set (Plytix-style), attached to channel + family (Akeneo-style)."""

    __tablename__ = "channel_requirement_set"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    image_rules: Mapped[dict] = mapped_column(JSON, default=dict)  # IMG-02: min_width, min_height, aspect_ratio...
    requirements: Mapped[list[ChannelRequirement]] = relationship(cascade="all, delete-orphan")


class ChannelRequirement(Base):
    __tablename__ = "channel_requirement"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    set_code: Mapped[str] = mapped_column(
        ForeignKey("channel_requirement_set.code", ondelete="CASCADE"), nullable=False
    )
    attribute_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shot_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)  # channel length limit


class ChannelRequirementBinding(Base):
    __tablename__ = "channel_requirement_binding"
    channel_code: Mapped[str] = mapped_column(ForeignKey("channel.code", ondelete="CASCADE"), primary_key=True)
    family_code: Mapped[str] = mapped_column(String(64), primary_key=True, default="*")  # "*" = any family
    set_code: Mapped[str] = mapped_column(ForeignKey("channel_requirement_set.code"), nullable=False)


class Channel(Base, TimestampMixin):
    """EXP-01 channel profile. Versioned; every publish records the version."""

    __tablename__ = "channel"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)  # shopify_admin | walmart_mp | ...
    kind: Mapped[str] = mapped_column(String(16), default="dtc")  # dtc | marketplace | retailer
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    protected_fields: Mapped[list] = mapped_column(JSON, default=list)  # EXP-07 v1.3, never written
    attribute_mapping: Mapped[dict] = mapped_column(JSON, default=dict)  # our attr code -> target field
    target_schema: Mapped[dict] = mapped_column(JSON, default=dict)  # EXP-02 loaded schema
    eligibility: Mapped[dict] = mapped_column(JSON, default=dict)  # EXP-12 rules
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # transport, file format, schedule, image profile
