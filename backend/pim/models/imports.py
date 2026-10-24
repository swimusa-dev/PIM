"""Import staging (IMP-01 to IMP-08), keyed worksheets (IMP-12), bulk actions (DM-04), rules (GOV-01)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pim.db.session import Base
from pim.models._common import IdMixin, TimestampMixin, utcnow

BATCH_STATUSES = ("uploaded", "mapped", "validated", "matched", "reviewed", "committing", "committed", "failed", "rolled_back")


class ImportSource(Base, TimestampMixin):
    __tablename__ = "import_source"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="supplier")  # supplier | retailer | shopify | worksheet | other
    default_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    # IMP-06 trusted-source rank; lower is more trusted. erp=0, user approved=1, retailer=2, supplier=3, shopify=4, ai=5
    trust_rank: Mapped[int] = mapped_column(Integer, default=3)


class MappingTemplate(Base, IdMixin, TimestampMixin):
    __tablename__ = "mapping_template"
    __table_args__ = (Index("ix_template_signature", "structure_signature"),)
    source_code: Mapped[str] = mapped_column(ForeignKey("import_source.code"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    structure_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    header_row: Mapped[int] = mapped_column(Integer, default=1)
    group_header_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_start_row: Mapped[int] = mapped_column(Integer, default=2)
    level: Mapped[str] = mapped_column(String(16), default="style_color")
    columns: Mapped[list] = mapped_column(JSON, default=list)
    match_keys: Mapped[list] = mapped_column(JSON, default=list)
    unmatched_policy: Mapped[str] = mapped_column(String(32), default="update_only")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    is_retailer_export_layout: Mapped[bool] = mapped_column(Boolean, default=False)  # IMP-08 / EXP-09 reuse


class ImportBatch(Base, IdMixin, TimestampMixin):
    __tablename__ = "import_batch"
    __table_args__ = (Index("ix_batch_status", "status"),)
    status: Mapped[str] = mapped_column(String(16), default="uploaded")
    source_code: Mapped[str] = mapped_column(ForeignKey("import_source.code"), nullable=False)
    template_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    level: Mapped[str] = mapped_column(String(16), default="style_color")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    files: Mapped[list] = mapped_column(JSON, default=list)
    mapping: Mapped[list] = mapped_column(JSON, default=list)
    match_keys: Mapped[list] = mapped_column(JSON, default=list)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    diff: Mapped[dict] = mapped_column(JSON, default=dict)
    worksheet_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    change_set_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    job_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows: Mapped[list[ImportRow]] = relationship(cascade="all, delete-orphan", back_populates="batch",
                                                 order_by="(ImportRow.file_index, ImportRow.row_number)")


class ImportRow(Base, IdMixin):
    __tablename__ = "import_row"
    __table_args__ = (Index("ix_import_row_batch", "batch_id"), Index("ix_import_row_match", "batch_id", "match_status"))
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False)
    file_index: Mapped[int] = mapped_column(Integer, default=0)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    mapped: Mapped[dict] = mapped_column(JSON, default=dict)
    match_status: Mapped[str] = mapped_column(String(16), default="unmatched")
    match_key_used: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    action: Mapped[str] = mapped_column(String(16), default="update")
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    batch: Mapped[ImportBatch] = relationship(back_populates="rows")


class ImportConflict(Base, IdMixin):
    __tablename__ = "import_conflict"
    __table_args__ = (Index("ix_conflict_batch", "batch_id", "status"),)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False)
    row_id: Mapped[str] = mapped_column(String(36), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attribute_code: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_code: Mapped[str] = mapped_column(String(64), default="")
    current: Mapped[dict] = mapped_column(JSON, default=dict)
    incoming: Mapped[dict] = mapped_column(JSON, default=dict)
    policy: Mapped[str] = mapped_column(String(32), default="fill_empty_only")
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | accepted | rejected | edited
    resolved_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorksheetExport(Base, IdMixin):
    """IMP-12 keyed worksheet. The id and a checksum secret are embedded in the file so returns are recognized."""

    __tablename__ = "worksheet_export"
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    selection: Mapped[dict] = mapped_column(JSON, default=dict)
    level: Mapped[str] = mapped_column(String(16), default="style_color")
    group_codes: Mapped[list] = mapped_column(JSON, default=list)
    attribute_codes: Mapped[list] = mapped_column(JSON, default=list)
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    file_name: Mapped[str] = mapped_column(String(300), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)


class BulkAction(Base, IdMixin, TimestampMixin):
    __tablename__ = "bulk_action"
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    selection: Mapped[dict] = mapped_column(JSON, default=dict)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="preview")
    preview: Mapped[dict] = mapped_column(JSON, default=dict)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    change_set_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    job_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Rule(Base, IdMixin, TimestampMixin):
    """GOV-01 condition/action rule. Draft until a preview passes GOV-06 checks and an admin activates it."""

    __tablename__ = "rule"
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | active
    trigger: Mapped[str] = mapped_column(String(16), default="all")  # on_save | on_import | nightly | all
    level: Mapped[str] = mapped_column(String(16), default="style_color")
    condition: Mapped[dict] = mapped_column(JSON, default=dict)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    brand_scopes: Mapped[list] = mapped_column(JSON, default=list)
    last_preview: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    activation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), default="system")


class RuleRun(Base, IdMixin):
    __tablename__ = "rule_run"
    __table_args__ = (Index("ix_rule_run_rule", "rule_id", "run_at"),)
    rule_id: Mapped[str] = mapped_column(ForeignKey("rule.id", ondelete="CASCADE"), nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    affected: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    change_set_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
