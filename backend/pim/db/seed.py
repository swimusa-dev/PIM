"""Seed loader for the metadata layer (1.3). Upserts by code; never deletes."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.models import (
    AttributeDefinition,
    AttributeGroup,
    BrandScope,
    Channel,
    ChannelRequirement,
    ChannelRequirementBinding,
    ChannelRequirementSet,
    Family,
    FamilyGroup,
    FilenamePattern,
    OptionList,
    OptionValue,
    PlaceholderToken,
    ReferenceEntityType,
    Role,
    ShotType,
    UserRole,
    ValueMapping,
    WorkflowDefinition,
    WorkflowStep,
)
from pim.normalization import normalize_raw_option

log = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parents[3] / "seeds"

REFERENCE_TYPES = [
    {"code": "print", "label": "Print", "label_attribute": "print_name"},
    {"code": "fabric", "label": "Fabric", "label_attribute": "fabric_name"},
    {"code": "model", "label": "Model profile", "label_attribute": "model_name"},
]


def _load(name: str) -> dict:
    path = SEED_DIR / name
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _upsert(session: Session, model, pk: str, data: dict):  # noqa: ANN001
    obj = session.get(model, data[pk])
    if obj is None:
        obj = model(**data)
        session.add(obj)
    else:
        for k, v in data.items():
            setattr(obj, k, v)
    return obj


def seed_all(session: Session, seed_dir: Path | None = None) -> dict[str, int]:
    global SEED_DIR
    if seed_dir:
        SEED_DIR = seed_dir
    counts: dict[str, int] = {}

    # Groups
    for g in _load("groups.yml").get("groups", []):
        _upsert(session, AttributeGroup, "code", g)
        counts["groups"] = counts.get("groups", 0) + 1
    session.flush()

    # Option lists and size scales
    ol = _load("option_lists.yml")
    for kind, key in (("option", "option_lists"), ("size_scale", "size_scales")):
        for lst in ol.get(key, []):
            values = lst.pop("values", [])
            lst["kind"] = kind
            obj = _upsert(session, OptionList, "code", lst)
            session.flush()
            existing = {v.code: v for v in obj.values}
            for i, v in enumerate(values):
                data = {
                    "code": str(v["code"]),
                    "label": str(v.get("label", v["code"])),
                    "sort_order": int(v.get("sort_order", i * 10)),
                    "channel_mappings": v.get("channel_mappings", {}),
                }
                if data["code"] in existing:
                    for k, val in data.items():
                        setattr(existing[data["code"]], k, val)
                else:
                    obj.values.append(OptionValue(**data))
            counts["option_lists"] = counts.get("option_lists", 0) + 1
    session.flush()

    # Reference entity types
    for rt in REFERENCE_TYPES:
        _upsert(session, ReferenceEntityType, "code", rt)

    # Attributes
    for a in _load("attributes.yml").get("attributes", []):
        a.setdefault("validation", {})
        a.setdefault("status", "proposed")
        a.setdefault("source_of_truth", "pim")
        _upsert(session, AttributeDefinition, "code", a)
        counts["attributes"] = counts.get("attributes", 0) + 1
    session.flush()

    # Families
    for f in _load("families.yml").get("families", []):
        groups = f.pop("groups", [])
        fam = _upsert(session, Family, "code", f)
        session.flush()
        fam.groups.clear()
        for i, gc in enumerate(groups):
            fam.groups.append(FamilyGroup(family_code=fam.code, group_code=gc, sort_order=i * 10))
        counts["families"] = counts.get("families", 0) + 1
    session.flush()

    # Channels and requirement sets
    ch = _load("channels.yml")
    for rs in ch.get("requirement_sets", []):
        reqs = rs.pop("requirements", [])
        obj = _upsert(session, ChannelRequirementSet, "code", rs)
        session.flush()
        obj.requirements.clear()
        for r in reqs:
            obj.requirements.append(ChannelRequirement(**r))
    session.flush()
    for c in ch.get("channels", []):
        rs_code = c.pop("requirement_set", None)
        obj = _upsert(session, Channel, "code", c)
        session.flush()
        if rs_code:
            binding = session.get(ChannelRequirementBinding, {"channel_code": obj.code, "family_code": "*"})
            if binding is None:
                session.add(ChannelRequirementBinding(channel_code=obj.code, family_code="*", set_code=rs_code))
            else:
                binding.set_code = rs_code
        counts["channels"] = counts.get("channels", 0) + 1
    session.flush()

    # Roles, brand scopes, user roles
    roles = _load("roles.yml")
    for r in roles.get("roles", []):
        rights = dict(r.get("data_rights", {}))
        # P1 and D-05 enforced regardless of YAML: ERP is view-only, cost is none unless view_cost permission.
        rights["erp"] = "view" if rights.get("erp", "view") != "none" else "none"
        if "view_cost" not in r.get("permissions", []):
            rights["cost"] = "none"
        r["data_rights"] = rights
        _upsert(session, Role, "code", r)
        counts["roles"] = counts.get("roles", 0) + 1
    for b in roles.get("brand_scopes", []):
        _upsert(session, BrandScope, "code", b)
    session.flush()
    for ur in roles.get("user_roles", []):
        existing = session.execute(
            select(UserRole).where(UserRole.email == ur["email"], UserRole.role_code == ur["role_code"])
        ).scalar_one_or_none()
        if existing is None:
            session.add(UserRole(**ur))
        else:
            existing.brand_scopes = ur.get("brand_scopes", [])

    # Placeholders
    for p in _load("placeholders.yml").get("placeholders", []):
        p["token"] = p["token"].strip().lower()
        _upsert(session, PlaceholderToken, "token", p)

    # Images
    img = _load("images.yml")
    for st in img.get("shot_types", []):
        _upsert(session, ShotType, "code", st)
    existing_patterns = {p.regex for p in session.execute(select(FilenamePattern)).scalars()}
    for fp in img.get("filename_patterns", []):
        if fp["regex"] not in existing_patterns:
            session.add(FilenamePattern(**fp))

    # Workflows
    for wf in _load("workflows.yml").get("workflows", []):
        steps = wf.pop("steps", [])
        obj = session.execute(select(WorkflowDefinition).where(WorkflowDefinition.code == wf["code"])).scalar_one_or_none()
        if obj is None:
            obj = WorkflowDefinition(**wf)
            session.add(obj)
        else:
            for k, v in wf.items():
                setattr(obj, k, v)
        session.flush()
        obj.steps.clear()
        for s in steps:
            obj.steps.append(WorkflowStep(**s))

    # Value mappings
    lists = {o.code: {v.code for v in o.values} for o in session.execute(select(OptionList)).scalars()}
    for vm in _load("value_mappings.yml").get("value_mappings", []):
        if vm["list"] not in lists:
            log.warning("value mapping references unknown list %s", vm["list"])
            continue
        key = normalize_raw_option(vm["raw"])
        existing = session.execute(
            select(ValueMapping).where(
                ValueMapping.source_code == vm["source"],
                ValueMapping.list_code == vm["list"],
                ValueMapping.raw_normalized == key,
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                ValueMapping(
                    source_code=vm["source"],
                    list_code=vm["list"],
                    raw_value=str(vm["raw"]),
                    raw_normalized=key,
                    option_code=vm.get("option"),
                )
            )
        else:
            existing.option_code = vm.get("option")
        counts["value_mappings"] = counts.get("value_mappings", 0) + 1

    session.commit()
    log.info("Seed complete: %s", counts)
    return counts
