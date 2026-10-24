"""RBAC-01 to RBAC-04 and saved views (DM-02)."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pim.db.session import Base
from pim.models._common import IdMixin, TimestampMixin

RIGHT_LEVELS = ("none", "view", "edit", "approve")
FEATURE_PERMISSIONS = (
    "import",
    "bulk_edit",
    "run_ai",
    "approve",
    "manage_channels",
    "export",
    "publish",
    "admin_metadata",
    "manage_users",
    "view_cost",
)


class Role(Base):
    __tablename__ = "role"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    # group_code -> none|view|edit|approve ; "*" applies to any group not listed
    data_rights: Mapped[dict] = mapped_column(JSON, default=dict)
    # channel_code -> {"run": bool, "edit_profile": bool} ; "*" wildcard (RBAC-03)
    channel_rights: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class BrandScope(Base):
    """RBAC-04: a brand is a rule over ERP fields, not a single field."""

    __tablename__ = "brand_scope"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    # list of {"field": "division", "op": "eq"|"in"|"contains", "value": ...}; all conditions in a rule must match;
    # a scope matches when any rule matches.
    rules: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class UserRole(Base, IdMixin):
    __tablename__ = "user_role"
    __table_args__ = (UniqueConstraint("email", "role_code"),)
    email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    role_code: Mapped[str] = mapped_column(ForeignKey("role.code"), nullable=False)
    brand_scopes: Mapped[list] = mapped_column(JSON, default=list)  # [] = all brands


class SavedView(Base, IdMixin, TimestampMixin):
    __tablename__ = "saved_view"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    shared_with: Mapped[str] = mapped_column(String(100), default="private")  # private | role:<code> | everyone
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    definition: Mapped[dict] = mapped_column(JSON, default=dict)  # filters, columns, sort, search
