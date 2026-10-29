"""Operational tables: jobs (ARC-04), ingest runs (IMP-09), assets and links (IMG-01, IMG-05),
packages and publishes (EXP-05, EXP-13), workflows (DM-07), telemetry (GOV-04), ERP defects (IMP-11)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pim.db.session import Base
from pim.models._common import IdMixin, TimestampMixin, new_id, utcnow


class JobRun(Base, IdMixin):
    __tablename__ = "job_run"
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # ingest | air_poll | image_match | package | bulk | ai
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | running | succeeded | failed | skipped
    requested_by: Mapped[str] = mapped_column(String(200), default="system")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    databricks_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class IngestRun(Base, IdMixin):
    """IMP-09 Style Master load. The latest succeeded run drives the header banner."""

    __tablename__ = "ingest_run"
    source: Mapped[str] = mapped_column(String(32), default="bluecherry")
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    discontinued: Mapped[int] = mapped_column(Integer, default=0)
    placeholders_removed: Mapped[int] = mapped_column(Integer, default=0)
    defects_found: Mapped[int] = mapped_column(Integer, default=0)
    workflows_started: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceStyleHash(Base):
    """Fingerprint of a style's Style Master rows as last loaded. The incremental ingest skips a style whose fingerprint
    has not changed."""

    __tablename__ = "source_style_hash"
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    style_number: Mapped[str] = mapped_column(String(64), primary_key=True)
    row_hash: Mapped[str] = mapped_column(String(40), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ErpDefect(Base, IdMixin):
    """IMP-11: ERP values that match no mapping or look like test data; reported back to BlueCherry owners."""

    __tablename__ = "erp_defect"
    __table_args__ = (Index("ix_defect_attr", "attribute_code"),)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attribute_code: Mapped[str] = mapped_column(String(64), nullable=False)
    erp_column: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)  # unmapped | test_value | date_in_text | not_in_scale
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Asset(Base, TimestampMixin):
    """IMG-01 snapshot of Air assets."""

    __tablename__ = "asset"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Air asset id
    version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filename: Mapped[str] = mapped_column(String(400), nullable=False)
    board_path: Mapped[str | None] = mapped_column(String(600), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    custom_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    smart_tags: Mapped[list] = mapped_column(JSON, default=list)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    air_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_generated_image: Mapped[bool] = mapped_column(Boolean, default=False)  # IMG-06
    parse_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | parsed | unparsed
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FilenamePattern(Base, IdMixin):
    """IMG-03 tier 1: admin-managed regex with named groups style, color, shot, seq."""

    __tablename__ = "filename_pattern"
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    regex: Mapped[str] = mapped_column(Text, nullable=False)
    shot_map: Mapped[dict] = mapped_column(JSON, default=dict)  # parsed shot token -> shot_type code
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AssetLink(Base, IdMixin, TimestampMixin):
    """IMG-03/IMG-05 proposed or confirmed link between an asset and a style-color."""

    __tablename__ = "asset_link"
    __table_args__ = (Index("ix_link_entity", "entity_id"), Index("ix_link_asset", "asset_id"))
    asset_id: Mapped[str] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[str] = mapped_column(ForeignKey("product_entity.id", ondelete="CASCADE"), nullable=False)
    shot_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tier: Mapped[int] = mapped_column(Integer, default=1)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed | confirmed | rejected
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    written_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # IMG-06
    asset: Mapped[Asset] = relationship()


class PublishRecord(Base, IdMixin):
    """EXP-05 record of every publish or package generation."""

    __tablename__ = "publish_record"
    channel_code: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_version: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(32), default="package")  # package | dry_run | publish | scheduled
    mode: Mapped[str] = mapped_column(String(8), default="full")  # delta | full (EXP-06)
    status: Mapped[str] = mapped_column(String(16), default="completed")  # running | completed | failed | skipped | submitted | accepted | partial | rejected
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    product_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    selection: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    files: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    package_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    external_batch_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class UpdatePackage(Base, IdMixin, TimestampMixin):
    """EXP-13 Shopify update package. Versioned, stored in a UC Volume, logged like a publish."""

    __tablename__ = "update_package"
    channel_code: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    selection: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot_mode: Mapped[str] = mapped_column(String(16), default="api")  # api | csv_upload
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_count: Mapped[int] = mapped_column(Integer, default=0)
    change_count: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    files: Mapped[list] = mapped_column(JSON, default=list)  # [{name, size, kind}]
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    downloads: Mapped[list] = mapped_column(JSON, default=list)  # [{by, at, file}]
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    rows: Mapped[list[UpdatePackageRow]] = relationship(cascade="all, delete-orphan", back_populates="package")


class UpdatePackageRow(Base, IdMixin):
    __tablename__ = "update_package_row"
    __table_args__ = (Index("ix_pkg_row_pkg", "package_id"),)
    package_id: Mapped[str] = mapped_column(ForeignKey("update_package.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    handle: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str | None] = mapped_column(String(400), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), default="product")  # product | variant | variant_metafield
    variant_key: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # option name/value pairs for variant rows
    field: Mapped[str] = mapped_column(String(200), nullable=False)  # Shopify column or metafield key
    attribute_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_clear: Mapped[bool] = mapped_column(Boolean, default=False)  # intentional blank, listed separately
    source_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    approval_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    include: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconcile_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # applied | not_applied | changed_differently
    reconcile_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    package: Mapped[UpdatePackage] = relationship(back_populates="rows")


class WorkflowDefinition(Base, IdMixin, TimestampMixin):
    """DM-07 (Phase 2 UI). Seeded: New style-color launch, started by IMP-09 for new style-colors."""

    __tablename__ = "workflow_definition"
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    entry_rule: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    steps: Mapped[list[WorkflowStep]] = relationship(cascade="all, delete-orphan", order_by="WorkflowStep.position")


class WorkflowStep(Base, IdMixin):
    __tablename__ = "workflow_step"
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_definition.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="enrich")  # enrich | review
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    group_codes: Mapped[list] = mapped_column(JSON, default=list)
    channel_codes: Mapped[list] = mapped_column(JSON, default=list)
    due_in_days: Mapped[int] = mapped_column(Integer, default=5)


class WorkflowItem(Base, IdMixin, TimestampMixin):
    __tablename__ = "workflow_item"
    __table_args__ = (Index("ix_wf_item_entity", "entity_id"), Index("ix_wf_item_state", "state"))
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_definition.id"), nullable=False)
    entity_id: Mapped[str] = mapped_column(ForeignKey("product_entity.id", ondelete="CASCADE"), nullable=False)
    current_step_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="open")  # open | done | cancelled
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    history: Mapped[list] = mapped_column(JSON, default=list)


class AppEvent(Base):
    """GOV-04 structured operational events (adapter errors, AI spend, request failures)."""

    __tablename__ = "app_event"
    __table_args__ = (Index("ix_event_kind_at", "kind", "at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # adapter_error | ai_call | request_error | job
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
