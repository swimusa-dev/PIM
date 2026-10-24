// GOV-01 rules engine admin, GOV-06 suspicious constants. List with priority / trigger / level / status and
// enabled toggle; editor with condition builder and actions; preview on samples; activate (forced with a
// reason when the preview blocks it); run now; runs history.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { rowsOf, useAttributes, useChannels, useGroups, useOptionLists, useWorkflows } from "../api/hooks";
import type { AttributeDefinition, Condition, ConditionOp, Level, OptionList, Rule, RuleAction, RuleActionOp, RuleInput, RulePreview, RuleTrigger } from "../api/types";
import { Badge, Confirm, Dialog, Empty, ErrorBox, Spinner, Tabs, useToast } from "../components/Common";
import { ValueEditor } from "../components/ValueEditor";
import { buildFieldCatalog, type FieldDef } from "../grid/fields";
import { displayValue, formatDate, LEVEL_LABEL } from "../lib/format";

const TRIGGERS: { v: RuleTrigger; label: string }[] = [
  { v: "on_save", label: "On save" },
  { v: "on_import", label: "On import" },
  { v: "nightly", label: "Nightly" },
  { v: "all", label: "All of the above" },
];
const COND_OPS: { op: ConditionOp; label: string }[] = [
  { op: "eq", label: "is" },
  { op: "neq", label: "is not" },
  { op: "contains", label: "contains" },
  { op: "in", label: "is one of" },
  { op: "empty", label: "is empty" },
  { op: "not_empty", label: "is not empty" },
  { op: "gt", label: ">" },
  { op: "lt", label: "<" },
  { op: "regex", label: "matches regex" },
];
const ACTION_OPS: { op: RuleActionOp; label: string }[] = [
  { op: "set", label: "Set" },
  { op: "clear", label: "Clear" },
  { op: "copy", label: "Copy from" },
  { op: "concatenate", label: "Concatenate" },
  { op: "calculate", label: "Calculate" },
  { op: "set_approval_state", label: "Set approval state" },
  { op: "add_to_workflow", label: "Add to workflow" },
  { op: "trigger_ai", label: "Trigger AI" },
];

const EMPTY_RULE: RuleInput = {
  code: "",
  label: "",
  priority: 100,
  enabled: false,
  trigger: "on_save",
  level: "style_color",
  condition: { all: [] },
  actions: [],
  brand_scopes: [],
};

export function RulesTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules.list });
  const [editing, setEditing] = useState<{ rule: Rule | null } | null>(null);
  const [previewing, setPreviewing] = useState<Rule | null>(null);
  const [deleting, setDeleting] = useState<Rule | null>(null);
  const [runsFor, setRunsFor] = useState<Rule | null>(null);

  const toggle = useMutation({
    mutationFn: (r: Rule) => api.rules.update(r.id, { enabled: !r.enabled }),
    onSuccess: (r) => {
      toast(r.enabled ? "Rule enabled." : "Rule disabled.", "ok");
      qc.invalidateQueries({ queryKey: ["rules"] });
    },
    onError: (e) => toast(`Could not update: ${(e as Error).message}`, "error"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.rules.remove(id),
    onSuccess: () => {
      toast("Rule deleted.", "ok");
      setDeleting(null);
      qc.invalidateQueries({ queryKey: ["rules"] });
    },
    onError: (e) => toast(`Could not delete: ${(e as Error).message}`, "error"),
  });
  const run = useMutation({
    mutationFn: (id: string) => api.rules.run(id),
    onSuccess: (r) => {
      toast(`Rule ran: ${r.affected} product${r.affected === 1 ? "" : "s"} affected.`, "ok");
      qc.invalidateQueries({ queryKey: ["rules"] });
      qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
    },
    onError: (e) => toast(`Run failed: ${(e as Error).message}`, "error"),
  });

  const sorted = useMemo(() => (rules.data ?? []).slice().sort((a, b) => a.priority - b.priority || a.code.localeCompare(b.code)), [rules.data]);

  return (
    <div>
      <div className="row mb8" style={{ justifyContent: "space-between" }}>
        <span className="muted small">
          Rules run in priority order (lowest first). A rule must be previewed on sample products from at least three brand scopes before it can be activated.
        </span>
        <button className="primary" onClick={() => setEditing({ rule: null })}>
          New rule
        </button>
      </div>
      {rules.isLoading && <Spinner label="Loading rules" />}
      {rules.isError && <ErrorBox error={rules.error} title="Could not load rules" />}
      {rules.data && sorted.length === 0 && <Empty title="No rules yet">Create a rule to derive, copy or validate attribute values automatically.</Empty>}
      {sorted.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th className="right">Priority</th>
                <th>Rule</th>
                <th>Trigger</th>
                <th>Level</th>
                <th>Status</th>
                <th>Enabled</th>
                <th>Last preview</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.id}>
                  <td className="num">{r.priority}</td>
                  <td>
                    <b>{r.label}</b>
                    <div className="faint small mono">{r.code}</div>
                    {r.brand_scopes.length > 0 && <div className="chips">{r.brand_scopes.map((b) => <Badge key={b}>{b}</Badge>)}</div>}
                  </td>
                  <td>{TRIGGERS.find((t) => t.v === r.trigger)?.label ?? r.trigger}</td>
                  <td>{LEVEL_LABEL[r.level] ?? r.level}</td>
                  <td>
                    <Badge color={r.status === "active" ? "green" : "amber"}>{r.status}</Badge>
                    {r.activated_at && (
                      <div className="faint small">
                        {formatDate(r.activated_at, false)}
                        {r.activated_by ? ` by ${r.activated_by}` : ""}
                      </div>
                    )}
                  </td>
                  <td>
                    <label className="switch" title={r.enabled ? "Enabled" : "Disabled"}>
                      <input type="checkbox" checked={r.enabled} disabled={toggle.isPending} onChange={() => toggle.mutate(r)} />
                      <span className="track" />
                    </label>
                  </td>
                  <td className="small">
                    {r.last_preview ? (
                      <span className="row" style={{ gap: 4 }}>
                        {r.last_preview.ok_to_activate ? <Badge color="green">ok</Badge> : <Badge color="red">blocked</Badge>}
                        <span className="faint">{r.last_preview.matched_total} matched</span>
                      </span>
                    ) : (
                      <span className="faint">none</span>
                    )}
                  </td>
                  <td className="nowrap">
                    <button className="small" onClick={() => setEditing({ rule: r })}>
                      Edit
                    </button>{" "}
                    <button className="small" onClick={() => setPreviewing(r)}>
                      Preview
                    </button>{" "}
                    <button className="small" disabled={run.isPending || r.status !== "active"} title={r.status !== "active" ? "Activate the rule first" : ""} onClick={() => run.mutate(r.id)}>
                      Run now
                    </button>{" "}
                    <button className="small" onClick={() => setRunsFor(r)}>
                      Runs
                    </button>{" "}
                    <button className="small danger" onClick={() => setDeleting(r)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <RuleEditor rule={editing.rule} onClose={() => setEditing(null)} />}
      {previewing && <PreviewDialog rule={rules.data?.find((r) => r.id === previewing.id) ?? previewing} onClose={() => setPreviewing(null)} />}
      {runsFor && <RunsDialog rule={runsFor} onClose={() => setRunsFor(null)} />}
      {deleting && (
        <Confirm
          title={`Delete rule ${deleting.label}?`}
          message="The rule stops running. Values it already set are kept."
          confirmLabel="Delete"
          busy={remove.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.id)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Editor
// ---------------------------------------------------------------------------------------------

function useRuleFields(level: Level) {
  const attrs = useAttributes();
  const groups = useGroups();
  const channels = useChannels();
  // Same catalog as the grid filter builder: core keys plus attr:<code>, grouped by attribute group.
  const fields = useMemo(
    () => buildFieldCatalog(level, attrs.data ?? [], groups.data ?? [], channels.data ?? []).filter((f) => f.kind === "core" || f.kind === "attr"),
    [level, attrs.data, groups.data, channels.data],
  );
  const targets = useMemo(
    () => fields.filter((f) => f.kind === "attr" && f.attr && f.attr.level === level && f.attr.source_of_truth !== "erp" && f.attr.status !== "deprecated"),
    [fields, level],
  );
  return { fields, targets, loading: attrs.isLoading || groups.isLoading, error: attrs.error ?? groups.error };
}

function FieldSelect({ fields, value, onChange, placeholder = "Choose a field" }: { fields: FieldDef[]; value: string; onChange: (v: string) => void; placeholder?: string }) {
  const grouped = useMemo(() => {
    const m = new Map<string, FieldDef[]>();
    for (const f of fields) m.set(f.groupLabel, [...(m.get(f.groupLabel) ?? []), f]);
    return Array.from(m.entries());
  }, [fields]);
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {grouped.map(([g, fs]) => (
        <optgroup key={g} label={g}>
          {fs.map((f) => (
            <option key={f.key} value={f.key}>
              {f.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

function RuleEditor({ rule, onClose }: { rule: Rule | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [r, setR] = useState<RuleInput>(() =>
    rule
      ? { code: rule.code, label: rule.label, priority: rule.priority, enabled: rule.enabled, status: rule.status, trigger: rule.trigger, level: rule.level, condition: { ...rule.condition }, actions: rule.actions.map((a) => ({ ...a })), brand_scopes: [...rule.brand_scopes] }
      : { ...EMPTY_RULE },
  );
  const [mode, setMode] = useState<"all" | "any">(rule?.condition.any && !rule.condition.all ? "any" : "all");
  const { fields, targets, loading, error } = useRuleFields(r.level);
  const optionLists = useOptionLists();
  const workflows = useWorkflows();
  const listByCode = useMemo(() => {
    const m: Record<string, OptionList> = {};
    for (const l of optionLists.data ?? []) m[l.code] = l;
    return m;
  }, [optionLists.data]);
  const conditions = (mode === "all" ? r.condition.all : r.condition.any) ?? [];
  const setConditions = (c: Condition[]) => setR({ ...r, condition: mode === "all" ? { all: c } : { any: c } });
  const switchMode = (m: "all" | "any") => {
    setMode(m);
    setR({ ...r, condition: m === "all" ? { all: conditions } : { any: conditions } });
  };

  const save = useMutation({
    mutationFn: () => {
      const body: RuleInput = { ...r, condition: mode === "all" ? { all: conditions } : { any: conditions } };
      return rule ? api.rules.update(rule.id, body) : api.rules.create(body);
    },
    onSuccess: () => {
      toast(rule ? "Rule saved." : "Rule created as a draft. Preview it before activating.", "ok");
      qc.invalidateQueries({ queryKey: ["rules"] });
      onClose();
    },
  });

  const updateCond = (i: number, patch: Partial<Condition>) => setConditions(conditions.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const updateAction = (i: number, patch: Partial<RuleAction>) => setR({ ...r, actions: r.actions.map((a, j) => (j === i ? { ...a, ...patch } : a)) });
  const moveAction = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= r.actions.length) return;
    const a = r.actions.slice();
    [a[i], a[j]] = [a[j], a[i]];
    setR({ ...r, actions: a });
  };
  const attrOf = (target?: string): AttributeDefinition | undefined => targets.find((t) => t.key === `attr:${target}` || t.attr?.code === target)?.attr;
  const valid = /^[a-z0-9_]+$/.test(r.code) && r.label.trim().length > 0 && r.actions.length > 0 && r.actions.every((a) => actionValid(a));

  return (
    <Dialog
      title={rule ? `Edit rule ${rule.code}` : "New rule"}
      onClose={onClose}
      wide
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={!valid || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving" : "Save rule"}
          </button>
        </>
      }
    >
      <div className="stack gap16">
        <div className="form-grid">
          <label className="field">
            Code
            <input value={r.code} disabled={!!rule} placeholder="lowercase_with_underscores" onChange={(e) => setR({ ...r, code: e.target.value })} />
          </label>
          <label className="field">
            Label
            <input value={r.label} onChange={(e) => setR({ ...r, label: e.target.value })} />
          </label>
          <label className="field">
            Priority (lowest runs first)
            <input type="number" value={r.priority} onChange={(e) => setR({ ...r, priority: Number(e.target.value) })} />
          </label>
          <label className="field">
            Trigger
            <select value={r.trigger} onChange={(e) => setR({ ...r, trigger: e.target.value as RuleTrigger })}>
              {TRIGGERS.map((t) => (
                <option key={t.v} value={t.v}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Level
            <select value={r.level} onChange={(e) => setR({ ...r, level: e.target.value as Level, actions: [], condition: { all: [] } })}>
              {(["style", "style_color", "sku"] as Level[]).map((l) => (
                <option key={l} value={l}>
                  {LEVEL_LABEL[l]}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Brand scopes (comma separated, empty for all)
            <input value={r.brand_scopes.join(", ")} placeholder="e.g. vitamin_a" onChange={(e) => setR({ ...r, brand_scopes: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
          </label>
        </div>

        {loading && <Spinner label="Loading metadata" />}
        {!!error && <ErrorBox error={error} title="Could not load metadata" />}

        <div className="cond-group">
          <div className="row mb8">
            <b>When</b>
            <select value={mode} onChange={(e) => switchMode(e.target.value as "all" | "any")}>
              <option value="all">all of these are true</option>
              <option value="any">any of these is true</option>
            </select>
            {conditions.length === 0 && <span className="faint small">(no conditions: the rule applies to every product at this level)</span>}
          </div>
          <div className="stack" style={{ gap: 4 }}>
            {conditions.map((c, i) => {
              const fd = fields.find((f) => f.key === c.field);
              const needsValue = c.op !== "empty" && c.op !== "not_empty";
              const list = fd?.attr?.option_list_code ? listByCode[fd.attr.option_list_code] : undefined;
              return (
                <div className="filter-row" key={i}>
                  <FieldSelect fields={fields} value={c.field} onChange={(v) => updateCond(i, { field: v, value: "" })} />
                  <select value={c.op} onChange={(e) => updateCond(i, { op: e.target.value as ConditionOp })}>
                    {COND_OPS.map((o) => (
                      <option key={o.op} value={o.op}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  {needsValue && c.op === "in" && (
                    <input value={Array.isArray(c.value) ? c.value.join(", ") : String(c.value ?? "")} placeholder="comma separated" onChange={(e) => updateCond(i, { value: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
                  )}
                  {needsValue && c.op !== "in" && list && c.op !== "regex" && c.op !== "contains" && (
                    <select value={String(c.value ?? "")} onChange={(e) => updateCond(i, { value: e.target.value })}>
                      <option value="">choose</option>
                      {list.values.map((o) => (
                        <option key={o.code} value={o.code}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  )}
                  {needsValue && c.op !== "in" && (!list || c.op === "regex" || c.op === "contains") && fd?.attr?.data_type === "boolean" && c.op !== "regex" ? (
                    <select value={c.value === true ? "true" : c.value === false ? "false" : ""} onChange={(e) => updateCond(i, { value: e.target.value === "true" })}>
                      <option value="">choose</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </select>
                  ) : (
                    needsValue &&
                    c.op !== "in" &&
                    (!list || c.op === "regex" || c.op === "contains") && (
                      <input
                        type={fd?.attr?.data_type === "number" && c.op !== "regex" ? "number" : "text"}
                        value={c.value === null || c.value === undefined ? "" : String(c.value)}
                        placeholder={c.op === "regex" ? "pattern" : "value"}
                        onChange={(e) => updateCond(i, { value: fd?.attr?.data_type === "number" && c.op !== "regex" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value })}
                      />
                    )
                  )}
                  <button className="icon small" onClick={() => setConditions(conditions.filter((_, j) => j !== i))} aria-label="Remove condition">
                    &times;
                  </button>
                </div>
              );
            })}
            <div>
              <button className="small" onClick={() => setConditions([...conditions, { field: fields[0]?.key ?? "style_number", op: "eq", value: "" }])}>
                + Add condition
              </button>
            </div>
          </div>
        </div>

        <div>
          <div className="row mb8" style={{ justifyContent: "space-between" }}>
            <b>Then</b>
            <select value="" onChange={(e) => e.target.value && setR({ ...r, actions: [...r.actions, { op: e.target.value as RuleActionOp }] })}>
              <option value="">+ Add action</option>
              {ACTION_OPS.map((a) => (
                <option key={a.op} value={a.op}>
                  {a.label}
                </option>
              ))}
            </select>
          </div>
          {r.actions.length === 0 && <div className="empty">Add at least one action.</div>}
          <div className="stack" style={{ gap: 4 }}>
            {r.actions.map((a, i) => {
              const targetAttr = attrOf(a.target);
              return (
                <div className="action-row" key={i}>
                  <span className="faint small">{i + 1}.</span>
                  <select value={a.op} onChange={(e) => updateAction(i, { op: e.target.value as RuleActionOp, value: undefined, source: undefined, parts: undefined, expression: undefined, workflow_code: undefined, task_type: undefined })}>
                    {ACTION_OPS.map((o) => (
                      <option key={o.op} value={o.op}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  {a.op !== "add_to_workflow" && (
                    <>
                      <span className="muted small">target</span>
                      <select value={a.target ?? ""} onChange={(e) => updateAction(i, { target: e.target.value, value: undefined })}>
                        <option value="">attribute</option>
                        {targets.map((t) => (
                          <option key={t.key} value={t.attr!.code}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                    </>
                  )}
                  {a.op === "set" && targetAttr && (
                    <span style={{ minWidth: 160 }}>
                      <ValueEditor key={targetAttr.code} attr={targetAttr} optionList={targetAttr.option_list_code ? listByCode[targetAttr.option_list_code] : undefined} value={a.value ?? null} onCommit={(v) => updateAction(i, { value: v })} compact />
                      <span className="faint small"> {a.value !== undefined ? displayValue(a.value, targetAttr, listByCode) : "(commit a value)"}</span>
                    </span>
                  )}
                  {a.op === "copy" && (
                    <>
                      <span className="muted small">from</span>
                      <FieldSelect fields={fields} value={a.source ?? ""} onChange={(v) => updateAction(i, { source: v })} placeholder="source field" />
                    </>
                  )}
                  {a.op === "concatenate" && (
                    <>
                      <span className="muted small">parts</span>
                      <PartsPicker fields={fields} parts={a.parts ?? []} onChange={(p) => updateAction(i, { parts: p })} />
                      <span className="muted small">separator</span>
                      <input style={{ width: 50 }} value={a.separator ?? " "} onChange={(e) => updateAction(i, { separator: e.target.value })} />
                    </>
                  )}
                  {a.op === "calculate" && (
                    <>
                      <span className="muted small">expression</span>
                      <input style={{ width: 240 }} value={a.expression ?? ""} placeholder="e.g. attr:weight_g / 1000" onChange={(e) => updateAction(i, { expression: e.target.value })} />
                    </>
                  )}
                  {a.op === "set_approval_state" && (
                    <>
                      <span className="muted small">to</span>
                      <select value={typeof a.value === "string" ? a.value : ""} onChange={(e) => updateAction(i, { value: e.target.value })}>
                        <option value="">state</option>
                        {["draft", "proposed", "approved", "rejected"].map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </select>
                    </>
                  )}
                  {a.op === "add_to_workflow" && (
                    <>
                      <span className="muted small">workflow</span>
                      <select value={a.workflow_code ?? ""} onChange={(e) => updateAction(i, { workflow_code: e.target.value })}>
                        <option value="">choose</option>
                        {(workflows.data ?? []).map((w) => (
                          <option key={w.code} value={w.code}>
                            {w.label}
                          </option>
                        ))}
                      </select>
                    </>
                  )}
                  {a.op === "trigger_ai" && (
                    <>
                      <span className="muted small">task</span>
                      <input style={{ width: 140 }} value={a.task_type ?? ""} placeholder="task type" onChange={(e) => updateAction(i, { task_type: e.target.value })} />
                    </>
                  )}
                  <span className="grow" />
                  <button className="icon small" disabled={i === 0} onClick={() => moveAction(i, -1)} aria-label="Move up">
                    &uarr;
                  </button>
                  <button className="icon small" disabled={i === r.actions.length - 1} onClick={() => moveAction(i, 1)} aria-label="Move down">
                    &darr;
                  </button>
                  <button className="icon small" onClick={() => setR({ ...r, actions: r.actions.filter((_, j) => j !== i) })} aria-label="Remove action">
                    &times;
                  </button>
                </div>
              );
            })}
          </div>
        </div>
        {save.isError && <ErrorBox error={save.error} title="Could not save the rule" />}
      </div>
    </Dialog>
  );
}

function actionValid(a: RuleAction): boolean {
  switch (a.op) {
    case "set":
      return !!a.target && a.value !== undefined;
    case "clear":
      return !!a.target;
    case "copy":
      return !!a.target && !!a.source;
    case "concatenate":
      return !!a.target && !!a.parts && a.parts.length > 0;
    case "calculate":
      return !!a.target && !!a.expression;
    case "set_approval_state":
      return !!a.target && !!a.value;
    case "add_to_workflow":
      return !!a.workflow_code;
    case "trigger_ai":
      return !!a.target && !!a.task_type;
  }
}

function PartsPicker({ fields, parts, onChange }: { fields: FieldDef[]; parts: string[]; onChange: (p: string[]) => void }) {
  return (
    <span className="chips">
      {parts.map((p, i) => (
        <span key={`${p}-${i}`} className="chip">
          {fields.find((f) => f.key === p)?.label ?? p}
          <button onClick={() => onChange(parts.filter((_, j) => j !== i))} aria-label="Remove part">
            &times;
          </button>
        </span>
      ))}
      <FieldSelect fields={fields} value="" onChange={(v) => v && onChange([...parts, v])} placeholder="+ part" />
    </span>
  );
}

// ---------------------------------------------------------------------------------------------
// Preview and activate
// ---------------------------------------------------------------------------------------------

function PreviewDialog({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const attrs = useAttributes();
  const optionLists = useOptionLists();
  const listByCode = useMemo(() => {
    const m: Record<string, OptionList> = {};
    for (const l of optionLists.data ?? []) m[l.code] = l;
    return m;
  }, [optionLists.data]);
  const attrOf = (code: string) => attrs.data?.find((a) => a.code === code);
  const [preview, setPreview] = useState<RulePreview | null>(rule.last_preview ?? null);
  const [force, setForce] = useState(false);
  const [reason, setReason] = useState("");
  const [tab, setTab] = useState<"sample" | "constants">("sample");

  const run = useMutation({
    mutationFn: () => api.rules.preview(rule.id),
    onSuccess: (p) => {
      setPreview(p);
      qc.invalidateQueries({ queryKey: ["rules"] });
    },
  });
  const activate = useMutation({
    mutationFn: () => api.rules.activate(rule.id, force ? { force: true, reason: reason.trim() } : undefined),
    onSuccess: () => {
      toast("Rule activated.", "ok");
      qc.invalidateQueries({ queryKey: ["rules"] });
      onClose();
    },
  });

  const canActivate = !!preview?.ok_to_activate || (force && reason.trim().length > 0);

  return (
    <Dialog
      title={`Preview: ${rule.label}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button onClick={onClose}>Close</button>
          <button disabled={run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? "Running" : preview ? "Preview again" : "Preview on samples"}
          </button>
          {rule.status !== "active" && (
            <button className="primary" disabled={!canActivate || activate.isPending} title={canActivate ? "" : "Preview must be ok, or force with a reason"} onClick={() => activate.mutate()}>
              {activate.isPending ? "Activating" : force ? "Force activate" : "Activate"}
            </button>
          )}
        </>
      }
    >
      <div className="stack gap16">
        <div className="muted small">Runs the rule on 20 sample products from at least 3 brand scopes without saving anything.</div>
        {run.isError && <ErrorBox error={run.error} title="Preview failed" />}
        {!preview && !run.isPending && <Empty title="No preview yet">Click Preview on samples.</Empty>}
        {run.isPending && <Spinner label="Running on samples" />}
        {preview && (
          <>
            <div className="row gap16">
              <span>
                Matched <b>{preview.matched_total}</b>
              </span>
              <span className="row" style={{ gap: 4 }}>
                Brands covered {preview.brands_covered.length === 0 ? <span className="faint">none</span> : preview.brands_covered.map((b) => <Badge key={b}>{b}</Badge>)}
              </span>
              {preview.ok_to_activate ? <Badge color="green">OK to activate</Badge> : <Badge color="red">Blocked</Badge>}
            </div>
            {preview.blockers.length > 0 && (
              <div className="error-box">
                <div className="title">Blockers</div>
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {preview.blockers.map((b, i) => (
                    <li key={i}>{b}</li>
                  ))}
                </ul>
              </div>
            )}
            {preview.suspicious_constants.length > 0 && (
              <div className="banner warn boxed">
                <b>Suspicious constants (GOV-06):</b> the rule writes the same value across brands or families, which may be a default masquerading as data.
                <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  {preview.suspicious_constants.map((s, i) => (
                    <li key={i}>
                      {attrOf(s.attribute_code)?.label ?? s.attribute_code} = <b>{displayValue(s.value, attrOf(s.attribute_code), listByCode)}</b> across brands {s.brands.join(", ") || "n/a"}
                      {s.families.length ? ` and families ${s.families.join(", ")}` : ""}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <Tabs<"sample" | "constants">
              value={tab}
              onChange={setTab}
              tabs={[
                { key: "sample", label: "Sample products", count: preview.sample.length },
                { key: "constants", label: "Suspicious constants", count: preview.suspicious_constants.length },
              ]}
            />
            {tab === "sample" && (
              <div className="panel" style={{ maxHeight: 360, overflow: "auto" }}>
                {preview.sample.length === 0 ? (
                  <div className="empty">No sample products matched the condition.</div>
                ) : (
                  <table className="data compact">
                    <thead>
                      <tr>
                        <th>Product</th>
                        <th>Brands</th>
                        <th>Attribute</th>
                        <th>Before</th>
                        <th>After</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.sample.map((s) =>
                        (s.changes.length ? s.changes : [null]).map((c, i) => (
                          <tr key={`${s.entity_id}-${i}`}>
                            {i === 0 && (
                              <>
                                <td rowSpan={Math.max(s.changes.length, 1)}>
                                  <Link to={`/products/${encodeURIComponent(s.entity_id)}`}>{s.label}</Link>
                                </td>
                                <td rowSpan={Math.max(s.changes.length, 1)} className="small">
                                  {s.brand_scopes.join(", ")}
                                </td>
                              </>
                            )}
                            {c ? (
                              <>
                                <td>{attrOf(c.attribute_code)?.label ?? c.attribute_code}</td>
                                <td className="diff-old">{displayValue(c.before, attrOf(c.attribute_code), listByCode) || <span className="faint">empty</span>}</td>
                                <td className="diff-new">{displayValue(c.after, attrOf(c.attribute_code), listByCode) || <span className="faint">empty</span>}</td>
                              </>
                            ) : (
                              <td colSpan={3} className="faint">
                                no change
                              </td>
                            )}
                          </tr>
                        )),
                      )}
                    </tbody>
                  </table>
                )}
              </div>
            )}
            {tab === "constants" && preview.suspicious_constants.length === 0 && <Empty title="No suspicious constants" />}
            {tab === "constants" && preview.suspicious_constants.length > 0 && (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Attribute</th>
                    <th>Value</th>
                    <th>Brands</th>
                    <th>Families</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.suspicious_constants.map((s, i) => (
                    <tr key={i}>
                      <td>{attrOf(s.attribute_code)?.label ?? s.attribute_code}</td>
                      <td>{displayValue(s.value, attrOf(s.attribute_code), listByCode)}</td>
                      <td>{s.brands.join(", ")}</td>
                      <td>{s.families.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {!preview.ok_to_activate && rule.status !== "active" && (
              <div className="stack">
                <label className="inline">
                  <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> Activate anyway (logged with a reason)
                </label>
                {force && (
                  <label className="field">
                    Reason (required)
                    <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why the blockers do not apply" />
                  </label>
                )}
              </div>
            )}
          </>
        )}
        {activate.isError && <ErrorBox error={activate.error} title="Could not activate" />}
      </div>
    </Dialog>
  );
}

function RunsDialog({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const q = useQuery({ queryKey: ["rules", "runs", rule.id], queryFn: () => api.rules.runs(rule.id) });
  const rows = rowsOf(q.data);
  return (
    <Dialog
      title={`Runs: ${rule.label}`}
      onClose={onClose}
      footer={
        <button className="primary" onClick={onClose}>
          Close
        </button>
      }
    >
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} title="Could not load runs" />}
      {q.data && rows.length === 0 && <Empty title="No runs yet" />}
      {rows.length > 0 && (
        <table className="data compact">
          <thead>
            <tr>
              <th>Started</th>
              <th>Finished</th>
              <th>Trigger</th>
              <th>Status</th>
              <th className="right">Affected</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="nowrap">{formatDate(r.started_at)}</td>
                <td className="nowrap">{r.finished_at ? formatDate(r.finished_at) : <span className="faint">running</span>}</td>
                <td>{r.trigger ?? ""}</td>
                <td>{r.status ? <Badge color={r.status === "succeeded" ? "green" : r.status === "failed" ? "red" : "amber"}>{r.status}</Badge> : ""}</td>
                <td className="num">{r.affected ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Dialog>
  );
}
