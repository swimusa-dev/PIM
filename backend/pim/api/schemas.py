"""Pydantic request bodies (responses are plain dicts shaped per docs/api-contract.md)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GridQueryBody(BaseModel):
    level: str = "style_color"
    page: int = Field(1, ge=1)
    page_size: int = Field(100, ge=1, le=500)
    sort: list[dict] = []
    filters: list[dict] = []
    search: str | None = None
    columns: list[str] = []
    view_id: str | None = None
    channel_code: str | None = None


class ValuesBody(BaseModel):
    channel_code: str | None = None
    values: dict[str, Any]


class ClearBody(BaseModel):
    attribute_codes: list[str]
    channel_code: str | None = None


class ViewBody(BaseModel):
    name: str
    level: str
    shared_with: str = "private"
    is_default: bool = False
    definition: dict = {}


class ViewPatch(BaseModel):
    name: str | None = None
    level: str | None = None
    shared_with: str | None = None
    is_default: bool | None = None
    definition: dict | None = None


class DecideBody(BaseModel):
    draft_ids: list[str]
    decision: str
    comment: str | None = None


class PackageBody(BaseModel):
    channel_code: str
    selection: dict = {}
    snapshot: dict = {"mode": "api"}


class LinkDecisionBody(BaseModel):
    shot_type: str | None = None


class AttributeBody(BaseModel):
    code: str
    label: str
    data_type: str
    level: str
    group_code: str
    sort_order: int = 0
    option_list_code: str | None = None
    reference_type_code: str | None = None
    unit: str | None = None
    validation: dict = {}
    channel_scopable: bool = False
    allows_not_applicable: bool = False
    default_value: str | None = None
    default_families: list[str] = []
    owner_role: str | None = None
    owner_person: str | None = None
    status: str = "proposed"
    source_of_truth: str = "pim"
    help_text: str | None = None
    example_value: str | None = None
    erp_column: str | None = None
    not_required_means_na: bool = False
    cost_restricted: bool = False


class GroupBody(BaseModel):
    code: str
    label: str
    owning_role: str = "pim_admin"
    sort_order: int = 0
    read_only: bool = False
    survivorship: str = "fill_empty_only"
    exclude_from_quality: bool = False
    channel_code: str | None = None


class OptionListBody(BaseModel):
    code: str
    label: str
    kind: str = "option"
    size_group: str | None = None
    values: list[dict] = []


class ChannelBody(BaseModel):
    code: str
    label: str
    adapter: str
    kind: str = "dtc"
    enabled: bool = True
    protected_fields: list[str] = []
    attribute_mapping: dict = {}
    eligibility: dict = {}
    config: dict = {}
    requirement_set_code: str | None = None


class UserRoleBody(BaseModel):
    id: str | None = None
    email: str
    role_code: str | None = None
    role: str | None = None  # frontend alias
    brand_scopes: list[str] = []


class ReferenceBody(BaseModel):
    code: str | None = None
    label: str | None = None
    values: dict[str, Any] = {}
    certificate_refs: list[str] | None = None


# ---- Phase 3 (EXP-01, EXP-04, EXP-05, EXP-06, EXP-12, IMG-05, IMG-06, IMG-07) ----
class MappingBody(BaseModel):
    attribute_mapping: dict[str, str] = {}
    transforms: list[dict] = []
    image_profile: dict | None = None


class RunBody(BaseModel):
    selection: dict = {}
    mode: str = "full"  # delta | full
    preview: int = 5


class ScheduleBody(BaseModel):
    enabled: bool = False
    mode: str = "delta"
    every_hours: float | None = None
    at_hour: int | None = None
    at_minute: int = 0
    timezone: str = "America/New_York"
    view_id: str | None = None


class EligibilityOverrideBody(BaseModel):
    channel_code: str
    reason: str
    expires_at: str | None = None


class ImageOrderBody(BaseModel):
    link_ids: list[str]


class AssetPatchBody(BaseModel):
    ai_generated_image: bool


class RenditionRefreshBody(BaseModel):
    channel_code: str
    entity_ids: list[str] | None = None


# ---- Phase 4 (AI-02, AI-03, AI-04, AI-07, GOV-03) ----
class BrandVoiceBody(BaseModel):
    label: str | None = None
    tone: str = ""
    do_rules: list[str] = []
    dont_rules: list[str] = []
    blocked_terms: list[str] = []
    trademark_terms: dict[str, str] = {}
    punctuation_rules: list[str] = []
    examples: list[str] = []


class TemplateBody(BaseModel):
    code: str | None = None
    label: str
    task_type: str
    target_attribute: str | None = None
    output_attributes: list[str] = []
    channel_code: str | None = None
    family_code: str | None = None
    brand_code: str = "vitamin_a"
    body: str
    input_attributes: list[str] = []
    input_shot_types: list[str] = []
    accepts_text_input: bool = False
    accepts_document: bool = False
    max_length: int | None = None
    model_task: str = "copy"
    status: str | None = None
    note: str | None = None


class TemplatePreviewBody(BaseModel):
    entity_id: str
    channel_code: str | None = None
    text: str | None = None


class AskBody(BaseModel):
    entity_id: str
    template_code: str
    channel_code: str | None = None
    text: str | None = None
    document: dict | None = None
    image_asset_ids: list[str] | None = None


class AcceptBody(BaseModel):
    value: object | None = None


class RejectBody(BaseModel):
    reason: str


class RegenerateBody(BaseModel):
    note: str | None = None


class AiRunBody(BaseModel):
    template_code: str
    selection: dict = {}
    channel_code: str | None = None


class EvalBuildBody(BaseModel):
    attribute_code: str
    limit: int = 50


class EvalRunBody(BaseModel):
    template_code: str


class QualitySettingsBody(BaseModel):
    excluded_groups: list[str] = []
    enabled_checks: list[str] = []
    weights: dict[str, float] = {}
    grade_bands: dict[str, float] = {}


class RecomputeBody(BaseModel):
    entity_ids: list[str] | None = None
