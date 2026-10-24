"""GOV-01 rules engine with GOV-06 safety: condition/action rules ordered by priority, run on save, on import commit,
and nightly. Calculated or constant-setting rules must pass a preview on 20 sample products from at least 3 brand
scopes and a suspicious-constant check before they can be activated."""

from __future__ import annotations

import ast
import operator
import re
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pim.models import ProductEntity, ProductValue, Rule, RuleRun, ValueDraft, WorkflowDefinition
from pim.models._common import utcnow
from pim.services.metadata import Metadata
from pim.services.readiness import refresh_snapshots
from pim.services.values import NA_SENTINEL, new_change_set, set_value, typed_from_row

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.USub: operator.neg}


def _values_for(session: Session, ent: ProductEntity) -> dict[str, Any]:
    """Global values for the entity and its ancestors (inheritance), keyed by attribute code."""
    chain = [ent]
    cur = ent
    while cur.parent_id:
        cur = session.get(ProductEntity, cur.parent_id)
        if cur is None:
            break
        chain.append(cur)
    out: dict[str, Any] = {}
    for e in reversed(chain):  # ancestors first, children override nothing (strict ownership) but fill their own
        for pv in session.execute(select(ProductValue).where(ProductValue.entity_id == e.id, ProductValue.channel_code == "")).scalars():
            out[pv.attribute_code] = None if pv.not_applicable else typed_from_row(pv).as_python()
    return out


def _field(field: str, ent: ProductEntity, values: dict[str, Any]) -> Any:
    if field.startswith("attr:"):
        return values.get(field[5:])
    return getattr(ent, field, (ent.erp_fields or {}).get(field))


def eval_condition(cond: dict, ent: ProductEntity, values: dict[str, Any]) -> bool:
    if not cond:
        return True
    if "all" in cond or "any" in cond:
        alls = [eval_condition(c, ent, values) for c in cond.get("all", [])]
        anys = [eval_condition(c, ent, values) for c in cond.get("any", [])]
        return (all(alls) if alls else True) and (any(anys) if anys else True)
    val = _field(cond.get("field", ""), ent, values)
    op, target = cond.get("op", "eq"), cond.get("value")
    sval = "" if val is None else str(val)
    if op == "eq":
        return sval.lower() == str(target).lower()
    if op == "neq":
        return sval.lower() != str(target).lower()
    if op == "contains":
        return str(target).lower() in sval.lower()
    if op == "in":
        return sval.lower() in {str(t).lower() for t in (target or [])}
    if op == "empty":
        return val in (None, "", [])
    if op == "not_empty":
        return val not in (None, "", [])
    if op in ("gt", "lt"):
        try:
            return (float(val) > float(target)) if op == "gt" else (float(val) < float(target))
        except (TypeError, ValueError):
            return False
    if op == "regex":
        return bool(re.search(str(target), sval))
    return False


def _calc(expression: str, values: dict[str, Any]) -> Any:
    """Safe arithmetic over {{attr.code}} references."""
    expr = re.sub(r"\{\{attr\.([a-z0-9_]+)\}\}", lambda m: repr(float(values.get(m.group(1)) or 0)), expression)

    def ev(node):  # noqa: ANN001
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError("unsupported expression")

    return round(ev(ast.parse(expr, mode="eval")), 4)


def _render(template: str, values: dict[str, Any], ent: ProductEntity) -> str:
    return re.sub(r"\{\{(attr\.)?([a-z0-9_]+)\}\}", lambda m: str(values.get(m.group(2)) if m.group(1) else getattr(ent, m.group(2), "") or ""), template)


def planned_changes(session: Session, meta: Metadata, rule: Rule, ent: ProductEntity) -> list[dict]:
    values = _values_for(session, ent)
    if rule.brand_scopes and not set(rule.brand_scopes) & set(ent.brand_scopes or []):
        return []
    if not eval_condition(rule.condition or {}, ent, values):
        return []
    out = []
    for a in rule.actions or []:
        op, target = a.get("op"), a.get("target")
        if op == "set":
            after = _render(str(a.get("value", "")), values, ent) if isinstance(a.get("value"), str) else a.get("value")
            out.append({"attribute_code": target, "before": values.get(target), "after": after, "op": op})
        elif op == "clear":
            if values.get(target) is not None:
                out.append({"attribute_code": target, "before": values.get(target), "after": None, "op": op})
        elif op == "copy":
            src = a.get("source", "")
            after = values.get(src[5:] if src.startswith("attr:") else src)
            if after not in (None, ""):
                out.append({"attribute_code": target, "before": values.get(target), "after": after, "op": op})
        elif op == "concatenate":
            parts = [str(values.get(p[5:] if p.startswith("attr:") else p) or "") for p in a.get("parts", [])]
            after = str(a.get("separator", " ")).join(p for p in parts if p)
            if after:
                out.append({"attribute_code": target, "before": values.get(target), "after": after, "op": op})
        elif op == "calculate":
            try:
                after = _calc(str(a.get("expression", "0")), values)
            except Exception:  # noqa: BLE001
                continue
            out.append({"attribute_code": target, "before": values.get(target), "after": after, "op": op})
        elif op in ("set_approval_state", "add_to_workflow", "trigger_ai"):
            out.append({"attribute_code": target, "before": None, "after": a.get("value") or a.get("workflow_code") or a.get("task_type"), "op": op})
    # skip no-ops
    return [c for c in out if c["op"] not in ("set", "copy", "concatenate", "calculate") or c["before"] != c["after"]]


def preview_rule(session: Session, meta: Metadata, rule: Rule) -> dict:
    """GOV-06: 20 samples from at least 3 brands, plus a suspicious-constant check."""
    ents = session.execute(select(ProductEntity).where(ProductEntity.level == rule.level)).scalars().all()
    by_brand: dict[str, list[ProductEntity]] = {}
    for e in ents:
        for b in e.brand_scopes or ["(none)"]:
            by_brand.setdefault(b, []).append(e)
    sample: list[ProductEntity] = []
    brands = sorted(by_brand)
    i = 0
    while len(sample) < 20 and any(by_brand.values()):
        b = brands[i % len(brands)]
        if by_brand[b]:
            cand = by_brand[b].pop(0)
            if cand not in sample:
                sample.append(cand)
        i += 1
        if i > 10000:
            break
    rows, matched_total = [], 0
    after_by_attr: dict[str, list[tuple[Any, str, str]]] = {}
    for e in ents:
        ch = planned_changes(session, meta, rule, e)
        if ch:
            matched_total += 1
    for e in sample:
        ch = planned_changes(session, meta, rule, e)
        rows.append({"entity_id": e.id, "label": e.label, "brand_scopes": e.brand_scopes or [], "changes": ch})
        for c in ch:
            if c["op"] in ("set", "concatenate", "calculate", "copy") and c["after"] not in (None, ""):
                for b in e.brand_scopes or ["(none)"]:
                    after_by_attr.setdefault(c["attribute_code"], []).append((c["after"], b, e.family_code or "?"))
    suspicious = []
    for code, triples in after_by_attr.items():
        vals = Counter(str(v) for v, _, _ in triples)
        for v, n in vals.items():
            brands_v = {b for x, b, _ in triples if str(x) == v}
            fams_v = {f for x, _, f in triples if str(x) == v}
            if n >= 2 and (len(brands_v) >= 2 or len(fams_v) >= 3):
                suspicious.append({"attribute_code": code, "value": v, "brands": sorted(brands_v), "families": sorted(fams_v)})
    brands_covered = sorted({b for r in rows for b in r["brand_scopes"]})
    blockers = []
    if len(brands_covered) < 3:
        blockers.append(f"Only {len(brands_covered)} brand scope(s) have products to sample; GOV-06 asks for 3 (owner may waive)")
    if suspicious:
        blockers.append("Suspicious constant: the same computed value appears across unrelated brands or families")
    if not any(r["changes"] for r in rows):
        blockers.append("The rule changes nothing in the sample")
    preview = {"sample": rows, "brands_covered": brands_covered, "matched_total": matched_total, "suspicious_constants": suspicious,
               "ok_to_activate": not blockers, "blockers": blockers, "at": utcnow().isoformat()}
    rule.last_preview = preview
    return preview


def run_rules(session: Session, meta: Metadata, trigger: str, entities: list[ProductEntity] | None = None,
              only_rule: Rule | None = None, user_email: str = "system") -> list[dict]:
    rules = [only_rule] if only_rule else session.execute(
        select(Rule).where(Rule.enabled.is_(True), Rule.status == "active", Rule.trigger.in_([trigger, "all"])).order_by(Rule.priority)).scalars().all()
    results = []
    for rule in rules:
        ents = entities if entities is not None else session.execute(select(ProductEntity).where(ProductEntity.level == rule.level)).scalars().all()
        ents = [e for e in ents if e.level == rule.level]
        cs = new_change_set(session, "rule", user_email, f"rule {rule.code} ({trigger})", source_ref=rule.id)
        affected, report = 0, Counter()
        touched: dict[str, ProductEntity] = {}
        for e in ents:
            for ch in planned_changes(session, meta, rule, e):
                affected += 1
                op = ch["op"]
                if op in ("set", "copy", "concatenate", "calculate", "clear"):
                    attr = meta.attributes.get(ch["attribute_code"] or "")
                    if attr is None or attr.level != e.level:
                        report["skipped_level"] += 1
                        continue
                    raw = NA_SENTINEL if ch["after"] is None and attr.allows_not_applicable else ch["after"]
                    res = set_value(session, meta, None, e, attr, raw, source_type="rule", source_ref=rule.code, change_set=cs, force=True)
                    report[res.outcome] += 1
                    touched[e.id] = e
                elif op == "set_approval_state":
                    pv = session.execute(select(ProductValue).where(ProductValue.entity_id == e.id, ProductValue.attribute_code == ch["attribute_code"],
                                                                    ProductValue.channel_code == "")).scalar_one_or_none()
                    if pv:
                        pv.approval_state = str(ch["after"])
                        report["approval_state"] += 1
                elif op == "add_to_workflow":
                    from pim.services.workflow import start_workflow

                    wf = session.execute(select(WorkflowDefinition).where(WorkflowDefinition.code == ch["after"])).scalar_one_or_none()
                    if wf and start_workflow(session, meta, wf, e):
                        report["workflow"] += 1
                elif op == "trigger_ai":
                    # P4: the AI task still produces a suggestion; here we queue a placeholder draft request for the AI job
                    session.add(ValueDraft(entity_level=e.level, entity_id=e.id, attribute_code=ch["attribute_code"] or "", channel_code="",
                                           proposed={"value": None, "not_applicable": False, "ai_task": ch["after"]}, source_type="ai",
                                           ai_generated=True, submitted_by=f"rule:{rule.code}", state="draft"))
                    report["ai_requested"] += 1
        session.flush()
        refresh_snapshots(session, meta, list(touched.values()))
        session.add(RuleRun(rule_id=rule.id, trigger=trigger, affected=affected, report=dict(report), change_set_id=cs.id))
        results.append({"rule": rule.code, "affected": affected, "report": dict(report)})
    return results
