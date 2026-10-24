"""Phase 4 tables: AI-02 brand voices and versioned prompt templates, AI-03/AI-04 runs and outputs, AI-07 evaluation
set and runs, GOV-03 quality settings and snapshots."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from pim.db.session import Base
from pim.models._common import IdMixin, utcnow


class BrandVoice(Base):
    __tablename__ = "brand_voice"
    brand_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    tone: Mapped[str] = mapped_column(Text, default="")
    do_rules: Mapped[list] = mapped_column(JSON, default=list)
    dont_rules: Mapped[list] = mapped_column(JSON, default=list)
    blocked_terms: Mapped[list] = mapped_column(JSON, default=list)
    trademark_terms: Mapped[dict] = mapped_column(JSON, default=dict)
    punctuation_rules: Mapped[list] = mapped_column(JSON, default=list)
    examples: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)


class PromptTemplate(Base):
    """AI-02: one row per template code; the body history lives in prompt_template_version."""

    __tablename__ = "prompt_template"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    task_type: Mapped[str] = mapped_column(String(16), nullable=False)  # AI-05 task types
    target_attribute: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_attributes: Mapped[list] = mapped_column(JSON, default=list)
    channel_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    family_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    brand_code: Mapped[str] = mapped_column(String(64), default="vitamin_a")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    input_attributes: Mapped[list] = mapped_column(JSON, default=list)
    input_shot_types: Mapped[list] = mapped_column(JSON, default=list)
    accepts_text_input: Mapped[bool] = mapped_column(Boolean, default=False)
    accepts_document: Mapped[bool] = mapped_column(Boolean, default=False)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_task: Mapped[str] = mapped_column(String(16), default="copy")  # copy | classify (AI-01 endpoint choice)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | active | retired
    eval_gate: Mapped[dict] = mapped_column(JSON, default=dict)  # AI-07 {last_run_id, last_score, blocked}
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)


class PromptTemplateVersion(Base, IdMixin):
    __tablename__ = "prompt_template_version"
    __table_args__ = (UniqueConstraint("code", "version"),)
    code: Mapped[str] = mapped_column(ForeignKey("prompt_template.code", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)


class AiRun(Base, IdMixin):
    """AI-04 bulk run (and the container for single asks and eval runs)."""

    __tablename__ = "ai_run"
    __table_args__ = (Index("ix_ai_run_status", "status"),)
    kind: Mapped[str] = mapped_column(String(8), default="bulk")  # single | bulk | eval
    template_code: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, default=1)
    task_type: Mapped[str] = mapped_column(String(16), nullable=False)
    channel_code: Mapped[str] = mapped_column(String(64), default="")
    selection: Mapped[dict] = mapped_column(JSON, default=dict)
    entity_ids: Mapped[list] = mapped_column(JSON, default=list)
    sample_entity_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="sample_pending")
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    proposed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    needs_input: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    job_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[dict] = mapped_column(JSON, default=dict)


class AiOutput(Base, IdMixin):
    """AI-03 one suggestion (or check / classify result) with everything AI-07 needs to measure it."""

    __tablename__ = "ai_output"
    __table_args__ = (Index("ix_ai_output_entity", "entity_id"), Index("ix_ai_output_run", "run_id"),
                      Index("ix_ai_output_template", "template_code", "status"))
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attribute_code: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_code: Mapped[str] = mapped_column(String(64), default="")
    task_type: Mapped[str] = mapped_column(String(16), nullable=False)
    template_code: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, default=1)
    model: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed | accepted | edited | rejected | failed | needs_input | info
    proposed_value: Mapped[dict] = mapped_column(JSON, default=dict)  # {"value": ...}
    current_value: Mapped[dict] = mapped_column(JSON, default=dict)
    final_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    draft_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_input: Mapped[list] = mapped_column(JSON, default=list)
    grounding_errors: Mapped[list] = mapped_column(JSON, default=list)
    check_findings: Mapped[list] = mapped_column(JSON, default=list)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    edit_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)  # {text, image_asset_ids} so regenerate can replay them
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiEvalCase(Base, IdMixin):
    __tablename__ = "ai_eval_case"
    __table_args__ = (UniqueConstraint("entity_id", "attribute_code"),)
    entity_id: Mapped[str] = mapped_column(ForeignKey("product_entity.id", ondelete="CASCADE"), nullable=False)
    attribute_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiEvalRun(Base, IdMixin):
    __tablename__ = "ai_eval_run"
    template_code: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, default=1)
    model: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | passed | blocked | failed
    cases: Mapped[int] = mapped_column(Integer, default=0)
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    baseline_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    baseline_composite: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float] = mapped_column(Float, default=0.05)
    mlflow_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sample: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class QualitySettings(Base):
    """GOV-03 singleton (id = "default")."""

    __tablename__ = "quality_settings"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="default")
    excluded_groups: Mapped[list] = mapped_column(JSON, default=list)
    enabled_checks: Mapped[list] = mapped_column(JSON, default=list)
    weights: Mapped[dict] = mapped_column(JSON, default=dict)
    grade_bands: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)


class QualitySnapshot(Base):
    __tablename__ = "quality_snapshot"
    __table_args__ = (Index("ix_quality_channel_grade", "channel_code", "grade"),)
    entity_id: Mapped[str] = mapped_column(ForeignKey("product_entity.id", ondelete="CASCADE"), primary_key=True)
    channel_code: Mapped[str] = mapped_column(String(64), primary_key=True, default="")  # "" = overall
    grade: Mapped[str] = mapped_column(String(1), default="E")
    score: Mapped[int] = mapped_column(Integer, default=0)
    checks: Mapped[list] = mapped_column(JSON, default=list)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
