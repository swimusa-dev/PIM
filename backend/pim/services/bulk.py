"""DM-04 bulk actions: preview the first 20 changes and the total, run as a job, report changed, skipped, and
failed records with reasons, and keep the whole action as one reversible change set (GOV-02)."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.auth.identity import CurrentUser
from pim.models import (
    BulkAction,
    Family,
    ProductEntity,
    ProductValue,
    SavedView,
    ValueDraft,
    WorkflowDefinition,
)
from pim.models._common import utcnow
from pim.services.metadata import Metadata
from pim.services.readiness import refresh_snapshots
from pim.services.values import NA_SENTINEL, clear_value, new_change_set, set_value, typed_from_row

KINDS = ("set_value", "clear_value", "add_option", "remove_option", "find_replace", "copy_attribute", "change_family",
         "assign_workflow", "run_ai", "send_for_approval")


def resolve_entities(session: Session, meta: Metadata, user: CurrentUser, selection: dict) -> list[ProductEntity]:
    level = selection.get("level", "style_color")
    ids = selection.get("entity_ids") or []
    if ids:
        ents = session.execute(select(ProductEntity).where(ProductEntity.id.in_(ids))).scalars().all()
    elif selection.get("view_id"):
        from pim.services.grid import GridQuery, run_grid_query

        view = session.get(SavedView, selection["view_id"])
        if view is None:
            return []
        d = view.definition or {}
        res = run_grid_query(session, meta, user, GridQuery(level=view.level, page=1, page_size=5000, filters=d.get("filters", []),
                                                            search=d.get("search"), columns=["__none__"]))
        ents = session.execute(select(ProductEntity).where(ProductEntity.id.in_([r["entity_id"] for r in res["rows"]]))).scalars().all()
        level = view.level
    else:
        ents = []
    return [e for e in ents if e.level == level and user.in_brand_scope(e.brand_scopes or [])]


def _current(session: Session, ent: ProductEntity, code: str, channel: str = "") -> ProductValue | None:
    return session.execute(select(ProductValue).where(ProductValue.entity_id == ent.id, ProductValue.attribute_code == code,
                                                      ProductValue.channel_code == channel)).scalar_one_or_none()


def _owner(session: Session, ent: ProductEntity, level: str) -> ProductEntity | None:
    cur = ent
    from pim.services.metadata import LEVEL_ORDER

    while cur is not None and LEVEL_ORDER.get(cur.level, 0) > LEVEL_ORDER.get(level, 0):
        cur = session.get(ProductEntity, cur.parent_id) if cur.parent_id else None
    return cur if cur is not None and cur.level == level else None


def compute_changes(session: Session, meta: Metadata, user: CurrentUser, kind: str, entities: list[ProductEntity], params: dict,
                    limit: int | None = None) -> list[dict]:
    """Each change: {entity_id, label, attribute_code?, before, after, op}. Rights and ERP rules are applied at run time
    through set_value; the preview shows intent."""
    out: list[dict] = []
    channel = params.get("channel_code") or ""
    for ent in entities:
        if limit is not None and len(out) >= limit:
            break
        if kind in ("set_value", "clear_value", "add_option", "remove_option", "find_replace"):
            code = params.get("attribute_code")
            attr = meta.attributes.get(code or "")
            if attr is None:
                continue
            owner = _owner(session, ent, attr.level) or ent
            pv = _current(session, owner, code, channel)
            before = typed_from_row(pv).as_python() if pv else None
            if kind == "set_value":
                after = params.get("value")
            elif kind == "clear_value":
                if pv is None:
                    continue
                after = None
            elif kind in ("add_option", "remove_option"):
                cur = list(before) if isinstance(before, list) else ([before] if before else [])
                opts = params.get("option_codes") or []
                after = sorted(set(cur) | set(opts)) if kind == "add_option" else [c for c in cur if c not in opts]
                if attr.data_type == "single_select":
                    after = opts[0] if kind == "add_option" and opts else None
                if after == cur or (attr.data_type == "single_select" and after == before):
                    continue
            else:
                if not isinstance(before, str) or not before:
                    continue
                find, repl = str(params.get("find", "")), str(params.get("replace", ""))
                flags = 0 if params.get("case_sensitive") else re.IGNORECASE
                pattern = find if params.get("regex") else re.escape(find)
                after = re.sub(pattern, repl, before, flags=flags)
                if after == before:
                    continue
            out.append({"entity_id": owner.id, "label": owner.label, "attribute_code": code, "before": before, "after": after, "op": kind})
        elif kind == "copy_attribute":
            src, dst = meta.attributes.get(params.get("from_attribute", "")), meta.attributes.get(params.get("to_attribute", ""))
            if src is None or dst is None:
                continue
            s_owner, d_owner = _owner(session, ent, src.level), _owner(session, ent, dst.level)
            if s_owner is None or d_owner is None:
                continue
            spv, dpv = _current(session, s_owner, src.code), _current(session, d_owner, dst.code)
            after = typed_from_row(spv).as_python() if spv else None
            before = typed_from_row(dpv).as_python() if dpv else None
            if after in (None, "") or after == before:
                continue
            out.append({"entity_id": d_owner.id, "label": d_owner.label, "attribute_code": dst.code, "before": before, "after": after, "op": kind})
        elif kind == "change_family":
            fam = params.get("family_code")
            if fam and ent.family_code != fam:
                out.append({"entity_id": ent.id, "label": ent.label, "attribute_code": None, "before": ent.family_code, "after": fam, "op": kind})
        elif kind == "assign_workflow":
            out.append({"entity_id": ent.id, "label": ent.label, "attribute_code": None, "before": None, "after": params.get("workflow_code"), "op": kind})
        elif kind == "send_for_approval":
            n = session.execute(select(ValueDraft).where(ValueDraft.entity_id == ent.id, ValueDraft.state == "draft")).scalars().all()
            if n:
                out.append({"entity_id": ent.id, "label": ent.label, "attribute_code": None, "before": f"{len(n)} draft(s)", "after": "proposed", "op": kind})
        elif kind == "run_ai":
            out.append({"entity_id": ent.id, "label": ent.label, "attribute_code": params.get("target_attribute"), "before": None,
                        "after": f"AI suggestion ({params.get('task_type', 'generate')})", "op": kind})
    return out


def preview(session: Session, meta: Metadata, user: CurrentUser, kind: str, selection: dict, params: dict) -> BulkAction:
    if kind not in KINDS:
        raise ValueError(f"Unknown bulk action {kind}")
    ents = resolve_entities(session, meta, user, selection)
    changes = compute_changes(session, meta, user, kind, ents, params)
    action = BulkAction(kind=kind, selection=selection, params=params, status="preview", created_by=user.email,
                        preview={"total": len(changes), "entities": len(ents), "sample": changes[:20]})
    session.add(action)
    session.flush()
    return action


def run(session: Session, meta: Metadata, user: CurrentUser, action: BulkAction) -> dict:
    action.status = "running"
    ents = resolve_entities(session, meta, user, action.selection or {})
    changes = compute_changes(session, meta, user, action.kind, ents, action.params or {})
    cs = new_change_set(session, "bulk", user.email, f"bulk {action.kind}", source_ref=action.id)
    action.change_set_id = cs.id
    items, counts = [], {"changed": 0, "skipped": 0, "failed": 0}
    touched: dict[str, ProductEntity] = {}
    channel = (action.params or {}).get("channel_code") or None
    for ch in changes:
        ent = session.get(ProductEntity, ch["entity_id"])
        if ent is None:
            continue
        outcome, reason = "skipped", None
        try:
            if ch["op"] in ("set_value", "add_option", "remove_option", "find_replace", "copy_attribute"):
                attr = meta.attributes[ch["attribute_code"]]
                res = set_value(session, meta, user, ent, attr, ch["after"] if ch["after"] is not None else NA_SENTINEL if attr.allows_not_applicable else None,
                                channel_code=channel, change_set=cs) if ch["after"] is not None else clear_value(session, meta, user, ent, attr, channel, cs)
                outcome, reason = ("changed" if res.outcome in ("approved", "draft") else "skipped" if res.outcome == "unchanged" else "failed"), res.message
                if res.outcome == "draft":
                    reason = "saved as draft (no approve rights)"
            elif ch["op"] == "clear_value":
                res = clear_value(session, meta, user, ent, meta.attributes[ch["attribute_code"]], channel, cs)
                outcome, reason = ("changed" if res.outcome == "approved" else "failed" if res.outcome == "rejected" else "skipped"), res.message
            elif ch["op"] == "change_family":
                if not user.can("bulk_edit") and not user.can("admin_metadata"):
                    outcome, reason = "failed", "No bulk_edit permission"
                elif session.get(Family, ch["after"]) is None:
                    outcome, reason = "failed", "Unknown family"
                else:
                    ent.family_code = ch["after"]
                    outcome = "changed"
            elif ch["op"] == "assign_workflow":
                from pim.services.workflow import start_workflow

                wf = session.execute(select(WorkflowDefinition).where(WorkflowDefinition.code == ch["after"])).scalar_one_or_none()
                if wf is None:
                    outcome, reason = "failed", "Unknown workflow"
                else:
                    item = start_workflow(session, meta, wf, ent)
                    outcome, reason = ("changed", None) if item else ("skipped", "already in this workflow")
            elif ch["op"] == "send_for_approval":
                for d in session.execute(select(ValueDraft).where(ValueDraft.entity_id == ent.id, ValueDraft.state == "draft")).scalars():
                    d.state = "proposed"
                outcome = "changed"
            elif ch["op"] == "run_ai":
                outcome, reason = _run_ai_for(session, meta, user, ent, action.params or {})
        except Exception as exc:  # noqa: BLE001
            outcome, reason = "failed", str(exc)[:300]
        counts[outcome] += 1
        if outcome == "changed":
            touched[ent.id] = ent
        items.append({"entity_id": ent.id, "label": ent.label, "attribute_code": ch.get("attribute_code"), "outcome": outcome, "reason": reason})
    session.flush()
    refresh_snapshots(session, meta, list(touched.values()))
    action.report = {**counts, "items": items[:1000]}
    action.status = "succeeded" if counts["failed"] == 0 or counts["changed"] > 0 else "failed"
    action.updated_at = utcnow()
    return action.report


def _run_ai_for(session: Session, meta: Metadata, user: CurrentUser, ent: ProductEntity, params: dict) -> tuple[str, str | None]:
    """AI-04 bulk AI through a managed template (AI-02); output lands as a proposed draft (AI-03), never a write.
    The Exports-era `target_attribute` parameter picks the first active template for that attribute."""
    from pim.adapters.base import NotConfigured
    from pim.ai import tasks
    from pim.models import PromptTemplate

    if not user.can("run_ai"):
        return "failed", "No run_ai permission"
    tpl = session.get(PromptTemplate, params.get("template_code", "")) if params.get("template_code") else None
    if tpl is None and params.get("target_attribute"):
        tpl = next(iter(tasks.templates_for(session, meta, ent, params["target_attribute"])), None)
    if tpl is None:
        return "failed", "No active template for this attribute; create one under Admin > AI"
    try:
        outs = tasks.run_task(session, meta, user, ent, tpl, channel_code=params.get("channel_code") or "")
    except NotConfigured as exc:
        return "skipped", str(exc)
    except tasks.AiTaskError as exc:
        return "failed", str(exc)
    if any(o.status == "proposed" for o in outs):
        return "changed", "AI suggestion queued for approval"
    first = outs[0] if outs else None
    if first is None:
        return "failed", "no output"
    if first.status == "info":
        findings = first.check_findings or []
        return "skipped", (f"{len(findings)} finding(s): " + "; ".join(f.get("message", "") for f in findings[:3])) if findings else "; ".join(first.grounding_errors or ["nothing to apply"])
    parts = list(first.grounding_errors or [])
    if first.needs_input:
        parts.append(f"needs input: {', '.join(first.needs_input)}")
    return "failed", "; ".join(parts) or first.status


def rollback(session: Session, meta: Metadata, user: CurrentUser, action: BulkAction) -> dict:
    from pim.services.changesets import rollback_change_set

    if not action.change_set_id:
        raise ValueError("Nothing to roll back")
    result = rollback_change_set(session, meta, user, action.change_set_id)
    action.status = "rolled_back"
    action.report = {**(action.report or {}), "rollback": result}
    return result
