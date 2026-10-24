"""Metadata endpoints (1.3). Writes require admin_metadata (RBAC-02 PIM Admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.api.schemas import AttributeBody, ChannelBody, GroupBody, OptionListBody
from pim.api.serializers import attribute_out, channel_out, family_out, group_out, option_list_out
from pim.auth.identity import require_permission
from pim.models import (
    AttributeDefinition,
    AttributeGroup,
    Channel,
    ChannelRequirementBinding,
    OptionList,
    OptionValue,
)
from pim.services.metadata import invalidate

router = APIRouter(prefix="/api/metadata", tags=["metadata"])


@router.get("/attributes")
def list_attributes(level: str | None = None, group: str | None = None, include_deprecated: bool = True,
                    meta: Metadata = Depends(get_meta), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    out = []
    for a in sorted(meta.attributes.values(), key=lambda a: (meta.groups.get(a.group_code).sort_order if a.group_code in meta.groups else 999, a.sort_order, a.code)):
        if level and a.level != level:
            continue
        if group and a.group_code != group:
            continue
        if not include_deprecated and a.status == "deprecated":
            continue
        if not user.can_view_group(a.group_code):
            continue
        out.append(attribute_out(a))
    return out


@router.post("/attributes")
@router.put("/attributes/{code}")
def upsert_attribute(body: AttributeBody, code: str | None = None, session: Session = Depends(get_session),
                     user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    data = body.model_dump()
    if code and code != body.code:
        raise HTTPException(400, "code in path and body differ")
    obj = session.get(AttributeDefinition, body.code)
    if obj is None:
        obj = AttributeDefinition(**data)
        session.add(obj)
    else:
        for k, v in data.items():
            setattr(obj, k, v)
    session.commit()
    invalidate()
    return attribute_out(obj)


@router.get("/groups")
def list_groups(meta: Metadata = Depends(get_meta)) -> list[dict]:
    return [group_out(g) for g in sorted(meta.groups.values(), key=lambda g: g.sort_order)]


@router.put("/groups")
def save_groups(body: list[GroupBody], session: Session = Depends(get_session),
                user: CurrentUser = Depends(require_permission("admin_metadata"))) -> list[dict]:
    out = []
    for g in body:
        obj = session.get(AttributeGroup, g.code)
        data = g.model_dump()
        if obj is None:
            obj = AttributeGroup(**data)
            session.add(obj)
        else:
            for k, v in data.items():
                setattr(obj, k, v)
        out.append(obj)
    session.commit()
    invalidate()
    return [group_out(g) for g in out]


@router.put("/groups/{code}")
def upsert_group(code: str, body: GroupBody, session: Session = Depends(get_session),
                 user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    obj = session.get(AttributeGroup, code)
    data = body.model_dump()
    if obj is None:
        obj = AttributeGroup(**data)
        session.add(obj)
    else:
        for k, v in data.items():
            setattr(obj, k, v)
    session.commit()
    invalidate()
    return group_out(obj)


@router.get("/option-lists")
def list_option_lists(meta: Metadata = Depends(get_meta)) -> list[dict]:
    return [option_list_out(o) for o in sorted(meta.option_lists.values(), key=lambda o: o.code)]


@router.put("/option-lists/{code}")
def upsert_option_list(code: str, body: OptionListBody, session: Session = Depends(get_session),
                       user: CurrentUser = Depends(require_permission("admin_metadata"))) -> dict:
    obj = session.get(OptionList, code)
    if obj is None:
        obj = OptionList(code=code, label=body.label, kind=body.kind, size_group=body.size_group)
        session.add(obj)
        session.flush()
    else:
        obj.label, obj.kind, obj.size_group = body.label, body.kind, body.size_group
    existing = {v.code: v for v in obj.values}
    seen = set()
    for i, v in enumerate(body.values):
        seen.add(v["code"])
        if v["code"] in existing:
            existing[v["code"]].label = v.get("label", v["code"])
            existing[v["code"]].sort_order = int(v.get("sort_order", i * 10))
            existing[v["code"]].channel_mappings = v.get("channel_mappings", {})
        else:
            obj.values.append(OptionValue(code=v["code"], label=v.get("label", v["code"]),
                                          sort_order=int(v.get("sort_order", i * 10)), channel_mappings=v.get("channel_mappings", {})))
    # values not sent are kept (never delete silently); admins deprecate by removing usage first
    session.commit()
    invalidate()
    return option_list_out(obj)


@router.get("/families")
def list_families(meta: Metadata = Depends(get_meta)) -> list[dict]:
    return [family_out(f) for f in meta.families.values()]


@router.get("/channels")
def list_channels(meta: Metadata = Depends(get_meta)) -> list[dict]:
    return [channel_out(c, meta) for c in meta.channels.values()]


@router.put("/channels/{code}")
def upsert_channel(code: str, body: ChannelBody, session: Session = Depends(get_session),
                   user: CurrentUser = Depends(get_current_user), meta: Metadata = Depends(get_meta)) -> dict:
    if not (user.can("admin_metadata") or (user.can("manage_channels") and user.channel_right(code, "edit_profile"))):
        raise HTTPException(403, "No right to edit this channel profile (RBAC-03)")
    obj = session.get(Channel, code)
    data = body.model_dump()
    rs = data.pop("requirement_set_code", None)
    if obj is None:
        obj = Channel(**data)
        session.add(obj)
    else:
        for k, v in data.items():
            setattr(obj, k, v)
        obj.version += 1
    session.flush()
    if rs:
        b = session.get(ChannelRequirementBinding, {"channel_code": code, "family_code": "*"})
        if b is None:
            session.add(ChannelRequirementBinding(channel_code=code, family_code="*", set_code=rs))
        else:
            b.set_code = rs
    session.commit()
    invalidate()
    from pim.services.metadata import load_metadata

    return channel_out(obj, load_metadata(session, force=True))


@router.get("/reference-types")
def list_reference_types(meta: Metadata = Depends(get_meta)) -> list[dict]:
    return [{"code": r.code, "label": r.label, "label_attribute": r.label_attribute,
             "attribute_codes": [a.code for a in meta.attributes_for_level(f"ref:{r.code}")]}
            for r in meta.reference_types.values()]


@router.get("/shot-types")
def list_shot_types(meta: Metadata = Depends(get_meta)) -> list[dict]:
    return [{"code": s.code, "label": s.label, "sort_order": s.sort_order}
            for s in sorted(meta.shot_types.values(), key=lambda s: s.sort_order)]
