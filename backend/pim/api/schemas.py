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
