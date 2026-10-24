"""Identity and RBAC (RBAC-01 to RBAC-04, P7).

Databricks Apps forward the signed-in user's identity in request headers [D7]:
  X-Forwarded-Email, X-Forwarded-User, X-Forwarded-Preferred-Username, and, with OBO enabled,
  x-forwarded-access-token. The app proxy sets these; a browser cannot spoof them because the app is only
  reachable through the proxy [D8]. Locally, PIM_DEV_USER_EMAIL and PIM_DEV_USER_ROLES stand in.

Role resolution has two implementations behind one seam (PLT-00 step 3 decides which one we use):
  - GroupRoleMapper: call /api/2.0/preview/scim/v2/Me with the OBO token, read `groups`, map by PIM_GROUP_ROLE_MAP.
  - TableRoleMapper: read user_role rows keyed by email.
Both return role codes; effective rights are the most permissive across roles (RBAC-01).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.config import Settings, get_settings
from pim.db.session import get_session
from pim.models import BrandScope, Role, UserRole

log = logging.getLogger(__name__)

RIGHT_ORDER = {"none": 0, "view": 1, "edit": 2, "approve": 3}


@dataclass
class CurrentUser:
    email: str
    user_id: str | None
    roles: list[str]
    permissions: set[str] = field(default_factory=set)
    data_rights: dict[str, str] = field(default_factory=dict)  # group_code -> level ("*" default)
    channel_rights: dict[str, dict] = field(default_factory=dict)
    brand_scopes: list[str] = field(default_factory=list)  # [] = all brands
    access_token: str | None = None
    request_id: str | None = None

    def right_for_group(self, group_code: str) -> str:
        return self.data_rights.get(group_code, self.data_rights.get("*", "none"))

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def can_edit_group(self, group_code: str) -> bool:
        return RIGHT_ORDER[self.right_for_group(group_code)] >= RIGHT_ORDER["edit"]

    def can_approve_group(self, group_code: str) -> bool:
        return RIGHT_ORDER[self.right_for_group(group_code)] >= RIGHT_ORDER["approve"]

    def can_view_group(self, group_code: str) -> bool:
        return RIGHT_ORDER[self.right_for_group(group_code)] >= RIGHT_ORDER["view"]

    def channel_right(self, channel_code: str, kind: str) -> bool:
        r = self.channel_rights.get(channel_code) or self.channel_rights.get("*") or {}
        return bool(r.get(kind, False))

    def in_brand_scope(self, scopes: list[str]) -> bool:
        if not self.brand_scopes:
            return True
        return bool(set(scopes) & set(self.brand_scopes))

    def as_dict(self) -> dict:
        return {
            "email": self.email,
            "user_id": self.user_id,
            "roles": self.roles,
            "permissions": sorted(self.permissions),
            "data_rights": self.data_rights,
            "channel_rights": self.channel_rights,
            "brand_scopes": self.brand_scopes,
        }


# ---------------------------------------------------------------------------------------------------
# Role mappers (seam decided by PLT-00 step 3)
# ---------------------------------------------------------------------------------------------------
class RoleMapper:
    def roles_for(self, email: str, token: str | None, session: Session) -> tuple[list[str], list[str]]:
        """Returns (role_codes, brand_scope_codes)."""
        raise NotImplementedError


class TableRoleMapper(RoleMapper):
    def roles_for(self, email: str, token: str | None, session: Session) -> tuple[list[str], list[str]]:
        rows = session.execute(select(UserRole).where(UserRole.email == email.lower())).scalars().all()
        roles = [r.role_code for r in rows]
        scopes: set[str] = set()
        unrestricted = False
        for r in rows:
            if not r.brand_scopes:
                unrestricted = True
            scopes.update(r.brand_scopes or [])
        return roles, ([] if unrestricted or not rows else sorted(scopes))


class GroupRoleMapper(RoleMapper):
    """Maps Entra-synced Databricks groups to roles. Group membership is cached per email for 5 minutes."""

    def __init__(self, settings: Settings) -> None:
        self.map: dict[str, str] = {}
        for pair in settings.group_role_map.split(";"):
            if "=" in pair:
                g, r = pair.split("=", 1)
                self.map[g.strip().lower()] = r.strip()
        self._cache: dict[str, tuple[float, list[str]]] = {}
        self._fallback = TableRoleMapper()

    def _groups(self, email: str, token: str | None) -> list[str]:
        now = time.monotonic()
        hit = self._cache.get(email)
        if hit and now - hit[0] < 300:
            return hit[1]
        groups: list[str] = []
        if token:
            try:
                from databricks.sdk import WorkspaceClient

                w = WorkspaceClient(token=token, auth_type="pat")
                me = w.current_user.me()
                groups = [g.display.lower() for g in (me.groups or []) if g.display]
            except Exception as exc:  # noqa: BLE001
                log.warning("SCIM /Me failed for %s: %s", email, exc)
        self._cache[email] = (now, groups)
        return groups

    def roles_for(self, email: str, token: str | None, session: Session) -> tuple[list[str], list[str]]:
        roles = sorted({self.map[g] for g in self._groups(email, token) if g in self.map})
        table_roles, scopes = self._fallback.roles_for(email, token, session)
        return sorted(set(roles) | set(table_roles)), scopes


_mapper: RoleMapper | None = None


def get_role_mapper(settings: Settings) -> RoleMapper:
    global _mapper
    if _mapper is None:
        _mapper = GroupRoleMapper(settings) if settings.role_source == "groups" else TableRoleMapper()
    return _mapper


def reset_role_mapper() -> None:
    global _mapper
    _mapper = None


# ---------------------------------------------------------------------------------------------------
def build_user(email: str, user_id: str | None, role_codes: list[str], scopes: list[str], session: Session) -> CurrentUser:
    roles = session.execute(select(Role).where(Role.code.in_(role_codes))).scalars().all() if role_codes else []
    user = CurrentUser(email=email, user_id=user_id, roles=[r.code for r in roles], brand_scopes=scopes)
    merged_rights: dict[str, str] = {}
    for r in roles:
        user.permissions.update(r.permissions or [])
        for g, lvl in (r.data_rights or {}).items():
            if RIGHT_ORDER.get(lvl, 0) > RIGHT_ORDER.get(merged_rights.get(g, "none"), 0):
                merged_rights[g] = lvl
        for c, rights in (r.channel_rights or {}).items():
            cur = user.channel_rights.setdefault(c, {"run": False, "edit_profile": False})
            cur["run"] = cur["run"] or bool(rights.get("run"))
            cur["edit_profile"] = cur["edit_profile"] or bool(rights.get("edit_profile"))
    # Any explicit group right lower than "*" still applies to that group; the wildcard is the floor for the rest.
    user.data_rights = merged_rights or {"*": "none"}
    user.data_rights.setdefault("*", "none")
    # Hard rules that no role can lift: ERP is view-only (P1); cost is none unless view_cost (D-05).
    if RIGHT_ORDER[user.data_rights.get("erp", "view")] > 1:
        user.data_rights["erp"] = "view"
    if "view_cost" not in user.permissions:
        user.data_rights["cost"] = "none"
    elif user.data_rights.get("cost", "none") == "none":
        user.data_rights["cost"] = "view"
    return user


def get_current_user(request: Request, session: Session = Depends(get_session)) -> CurrentUser:
    settings = get_settings()
    email = request.headers.get("x-forwarded-email")
    user_id = request.headers.get("x-forwarded-user")
    token = request.headers.get("x-forwarded-access-token")
    dev_fallback = False
    if not email:
        if settings.is_databricks:
            raise HTTPException(status_code=401, detail="No identity header; the app must be reached through Databricks")
        email = settings.dev_user_email
        dev_fallback = True
        if not email:
            raise HTTPException(status_code=401, detail="Set PIM_DEV_USER_EMAIL for local development")
    email = email.lower()
    roles, scopes = get_role_mapper(settings).roles_for(email, token, session)
    # PIM_DEV_USER_ROLES only applies to the header-less local developer, never to a user identified by headers.
    if dev_fallback and not settings.is_databricks and settings.dev_user_roles:
        roles = sorted(set(roles) | {r.strip() for r in settings.dev_user_roles.split(",") if r.strip()})
    user = build_user(email, user_id, roles, scopes, session)
    user.access_token = token
    user.request_id = request.headers.get("x-request-id")
    request.state.user = user
    return user


def require_permission(permission: str):
    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.can(permission):
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
        return user

    return _dep


def evaluate_brand_scopes(erp_fields: dict, scopes: list[BrandScope]) -> list[str]:
    """RBAC-04: a scope matches when any of its rules matches; all conditions in a rule must match."""
    matched: list[str] = []
    for scope in scopes:
        if not scope.enabled:
            continue
        for rule in scope.rules or []:
            ok = True
            for cond in rule:
                field_val = str(erp_fields.get(cond.get("field"), "") or "").upper()
                target = cond.get("value")
                op = cond.get("op", "eq")
                if op == "eq":
                    ok = field_val == str(target).upper()
                elif op == "in":
                    ok = field_val in {str(t).upper() for t in (target or [])}
                elif op == "contains":
                    ok = str(target).upper() in field_val
                elif op == "neq":
                    ok = field_val != str(target).upper()
                else:
                    ok = False
                if not ok:
                    break
            if ok:
                matched.append(scope.code)
                break
    return matched
