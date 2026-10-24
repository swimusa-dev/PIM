// DM-07: My Work. Tabs Mine / My role / All with an overdue filter, Manager view (by step, age buckets),
// and an Admin tab (admin only) to edit workflow definitions with up to 20 ordered steps.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { isAdmin, useChannels, useGroups, useMe, useWorkflows } from "../api/hooks";
import type { AgeBucket, WorkflowDefinition, WorkflowScope, WorkflowStepDef, WorkflowStepKind } from "../api/types";
import { Badge, Dialog, Empty, ErrorBox, Spinner, Tabs, useToast } from "../components/Common";
import { DueTag, ItemActionButtons, StepProgress } from "../workflows/ItemActions";
import { formatDate } from "../lib/format";

type Tab = WorkflowScope | "manager" | "admin";
const MAX_STEPS = 20;

export function WorkflowsPage() {
  const me = useMe();
  const admin = isAdmin(me.data);
  const [tab, setTab] = useState<Tab>("mine");
  const tabs: { key: Tab; label: string }[] = [
    { key: "mine", label: "Mine" },
    { key: "role", label: "My role" },
    { key: "all", label: "All" },
    { key: "manager", label: "Manager" },
  ];
  if (admin) tabs.push({ key: "admin", label: "Admin" });
  return (
    <div>
      <div className="page-header">
        <h1>My Work</h1>
        <span className="muted small">Workflow steps waiting on you, your role, or anyone.</span>
      </div>
      <Tabs<Tab> tabs={tabs} value={tab} onChange={setTab} />
      {(tab === "mine" || tab === "role" || tab === "all") && <InboxTab scope={tab} />}
      {tab === "manager" && <ManagerTab />}
      {tab === "admin" && admin && <AdminTab />}
    </div>
  );
}

function InboxTab({ scope }: { scope: WorkflowScope }) {
  const [overdue, setOverdue] = useState(false);
  const q = useQuery({ queryKey: ["workflows", "inbox", scope, overdue], queryFn: () => api.workflows.inbox(scope, overdue), refetchInterval: 60_000 });
  const rows = q.data?.rows ?? [];
  return (
    <div>
      <div className="row mb8" style={{ justifyContent: "space-between" }}>
        <label className="inline">
          <input type="checkbox" checked={overdue} onChange={(e) => setOverdue(e.target.checked)} />
          Overdue only
        </label>
        <span className="faint small">{q.data?.total ?? 0} items</span>
      </div>
      {q.isLoading && <Spinner label="Loading work items" />}
      {q.isError && <ErrorBox error={q.error} title="Could not load work items" />}
      {q.data && rows.length === 0 && (
        <Empty title={overdue ? "Nothing overdue" : "Nothing waiting"}>
          {scope === "mine" ? "Items assigned to you appear here." : scope === "role" ? "Items for your roles appear here." : "No open workflow items."}
        </Empty>
      )}
      {rows.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Product</th>
                <th>Workflow</th>
                <th>Step</th>
                <th>Due</th>
                <th>Assignee</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((it) => (
                <tr key={it.id}>
                  <td>
                    <Link to={`/products/${encodeURIComponent(it.entity_id)}`}>{it.entity_label}</Link>
                  </td>
                  <td>{it.workflow_label}</td>
                  <td>
                    <div className="row" style={{ gap: 6 }}>
                      <StepProgress item={it} />
                      <span>
                        {it.step ? `${it.step.position}. ${it.step.label}` : "complete"}
                      </span>
                      {it.step && <Badge>{it.step.kind}</Badge>}
                    </div>
                    {it.step && <div className="faint small">role {it.step.role_code}</div>}
                  </td>
                  <td>
                    <DueTag item={it} />
                  </td>
                  <td>{it.assigned_email ?? <span className="faint">{it.assigned_role ?? "unassigned"}</span>}</td>
                  <td>
                    <ItemActionButtons item={it} compact />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const BUCKETS: AgeBucket[] = ["0-2", "3-7", "8-14", "15+"];

function ManagerTab() {
  const q = useQuery({ queryKey: ["workflows", "manager"], queryFn: api.workflows.manager });
  const workflows = useWorkflows();
  const wfLabel = (code: string) => workflows.data?.find((w) => w.code === code)?.label ?? code;
  const ageTotal = (q.data?.by_age ?? []).reduce((n, b) => n + b.count, 0);
  return (
    <div className="stack gap16">
      {q.isLoading && <Spinner label="Loading manager view" />}
      {q.isError && <ErrorBox error={q.error} title="Could not load the manager view" />}
      {q.data && (
        <>
          <div className="panel">
            <div className="panel-header">
              <h3>Open items by age (days)</h3>
              <span className="muted small">{ageTotal} open</span>
            </div>
            <div className="panel-body">
              {ageTotal === 0 ? (
                <div className="muted">No open items.</div>
              ) : (
                <>
                  <div className="age-bar">
                    {BUCKETS.map((b, i) => {
                      const n = q.data.by_age.find((x) => x.bucket === b)?.count ?? 0;
                      if (!n) return null;
                      return (
                        <div key={b} className={`seg b${i}`} style={{ width: `${(n / ageTotal) * 100}%` }} title={`${b} days: ${n}`}>
                          {n}
                        </div>
                      );
                    })}
                  </div>
                  <div className="legend mt8">
                    {BUCKETS.map((b, i) => (
                      <span key={b}>
                        <i className={`b${i}`} style={{ background: ["var(--green)", "var(--teal)", "var(--amber)", "var(--red)"][i] }} />
                        {b} days: {q.data.by_age.find((x) => x.bucket === b)?.count ?? 0}
                      </span>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
          <div className="panel">
            <div className="panel-header">
              <h3>By step</h3>
            </div>
            {q.data.by_step.length === 0 ? (
              <div className="empty">No open items.</div>
            ) : (
              <table className="data">
                <thead>
                  <tr>
                    <th>Workflow</th>
                    <th>Step</th>
                    <th className="right">Open</th>
                    <th className="right">Overdue</th>
                    <th className="right">Oldest (days)</th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.by_step.map((s, i) => (
                    <tr key={`${s.workflow_code}-${s.step_label}-${i}`}>
                      <td>{wfLabel(s.workflow_code)}</td>
                      <td>{s.step_label}</td>
                      <td className="num">{s.open}</td>
                      <td className="num" style={{ color: s.overdue ? "var(--red)" : undefined }}>
                        {s.overdue}
                      </td>
                      <td className="num">{s.oldest_days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Admin: workflow definitions
// ---------------------------------------------------------------------------------------------

function AdminTab() {
  const workflows = useWorkflows();
  const [editing, setEditing] = useState<{ def: WorkflowDefinition; isNew: boolean } | null>(null);
  const blank: WorkflowDefinition = { code: "", label: "", enabled: true, entry_rule: "", steps: [] };
  return (
    <div>
      <div className="row mb8" style={{ justifyContent: "space-between" }}>
        <span className="muted small">A workflow is an ordered list of up to {MAX_STEPS} enrich or review steps, each owned by a role.</span>
        <button className="primary" onClick={() => setEditing({ def: blank, isNew: true })}>
          New workflow
        </button>
      </div>
      {workflows.isLoading && <Spinner />}
      {workflows.isError && <ErrorBox error={workflows.error} title="Could not load workflows" />}
      {workflows.data && workflows.data.length === 0 && <Empty title="No workflows defined" />}
      {workflows.data && workflows.data.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Code</th>
                <th>Label</th>
                <th>Enabled</th>
                <th>Entry rule</th>
                <th>Steps</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {workflows.data.map((w) => (
                <tr key={w.code}>
                  <td className="mono">{w.code}</td>
                  <td>{w.label}</td>
                  <td>{w.enabled ? <Badge color="green">enabled</Badge> : <Badge>disabled</Badge>}</td>
                  <td className="small muted">{w.entry_rule || ""}</td>
                  <td className="small">
                    {w.steps
                      .slice()
                      .sort((a, b) => a.position - b.position)
                      .map((s) => `${s.position}. ${s.label} (${s.kind}, ${s.role_code}, ${s.due_in_days}d)`)
                      .join("; ")}
                  </td>
                  <td>
                    <button className="small" onClick={() => setEditing({ def: { ...w, steps: w.steps.map((s) => ({ ...s })) }, isNew: false })}>
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <WorkflowDialog def={editing.def} isNew={editing.isNew} onClose={() => setEditing(null)} />}
    </div>
  );
}

function WorkflowDialog({ def, isNew, onClose }: { def: WorkflowDefinition; isNew: boolean; onClose: () => void }) {
  const [d, setD] = useState<WorkflowDefinition>(def);
  const groups = useGroups();
  const channels = useChannels();
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const roleSuggestions = useMemo(() => {
    const s = new Set<string>();
    for (const g of groups.data ?? []) if (g.owning_role) s.add(g.owning_role);
    for (const r of me.data?.roles ?? []) s.add(r);
    return Array.from(s).sort();
  }, [groups.data, me.data]);

  const save = useMutation({
    mutationFn: () => {
      const steps = d.steps.map((s, i) => ({ ...s, position: i + 1 }));
      return api.workflows.save(d.code, { label: d.label, enabled: d.enabled, entry_rule: d.entry_rule || null, steps });
    },
    onSuccess: () => {
      toast("Workflow saved.", "ok");
      qc.invalidateQueries({ queryKey: ["workflows"] });
      onClose();
    },
  });

  const updateStep = (i: number, patch: Partial<WorkflowStepDef>) => setD((x) => ({ ...x, steps: x.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)) }));
  const moveStep = (i: number, dir: -1 | 1) =>
    setD((x) => {
      const j = i + dir;
      if (j < 0 || j >= x.steps.length) return x;
      const steps = x.steps.slice();
      [steps[i], steps[j]] = [steps[j], steps[i]];
      return { ...x, steps };
    });
  const addStep = () =>
    setD((x) => ({
      ...x,
      steps: [...x.steps, { position: x.steps.length + 1, label: "", kind: "enrich", role_code: "", group_codes: [], channel_codes: [], due_in_days: 3 }],
    }));
  const toggleIn = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  const valid = /^[a-z0-9_]+$/.test(d.code) && d.label.trim().length > 0 && d.steps.length > 0 && d.steps.every((s) => s.label.trim() && s.role_code.trim());

  return (
    <Dialog
      title={isNew ? "New workflow" : `Edit workflow ${d.code}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={!valid || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving" : "Save workflow"}
          </button>
        </>
      }
    >
      <div className="stack gap16">
        <div className="form-grid">
          <label className="field">
            Code
            <input value={d.code} disabled={!isNew} placeholder="lowercase_with_underscores" onChange={(e) => setD({ ...d, code: e.target.value })} />
          </label>
          <label className="field">
            Label
            <input value={d.label} onChange={(e) => setD({ ...d, label: e.target.value })} />
          </label>
          <label className="field">
            Entry rule (optional)
            <input value={d.entry_rule ?? ""} placeholder="e.g. lifecycle_status = new" onChange={(e) => setD({ ...d, entry_rule: e.target.value })} />
          </label>
          <label className="inline" style={{ alignSelf: "end", paddingBottom: 6 }}>
            <input type="checkbox" checked={d.enabled} onChange={(e) => setD({ ...d, enabled: e.target.checked })} /> Enabled
          </label>
        </div>
        <div>
          <div className="row mb8" style={{ justifyContent: "space-between" }}>
            <b>
              Steps ({d.steps.length} of {MAX_STEPS})
            </b>
            <button className="small" disabled={d.steps.length >= MAX_STEPS} onClick={addStep}>
              + Add step
            </button>
          </div>
          {d.steps.length === 0 && <div className="empty">Add at least one step.</div>}
          <div className="step-list">
            {d.steps.map((s, i) => (
              <div className="step-card" key={i}>
                <div className="row nowrap" style={{ alignItems: "flex-start" }}>
                  <span className="faint" style={{ width: 20, paddingTop: 6 }}>
                    {i + 1}.
                  </span>
                  <div className="grow stack" style={{ gap: 6 }}>
                    <div className="row">
                      <input className="grow" value={s.label} placeholder="Step label" onChange={(e) => updateStep(i, { label: e.target.value })} />
                      <select value={s.kind} onChange={(e) => updateStep(i, { kind: e.target.value as WorkflowStepKind })}>
                        <option value="enrich">enrich</option>
                        <option value="review">review</option>
                      </select>
                      <input list="pim-roles" value={s.role_code} placeholder="role code" style={{ width: 150 }} onChange={(e) => updateStep(i, { role_code: e.target.value })} />
                      <label className="inline">
                        Due in
                        <input type="number" min={0} style={{ width: 60 }} value={s.due_in_days} onChange={(e) => updateStep(i, { due_in_days: Number(e.target.value) })} />
                        days
                      </label>
                    </div>
                    <div className="row">
                      <span className="muted small">Groups:</span>
                      {(groups.data ?? []).map((g) => (
                        <label key={g.code} className="inline small">
                          <input type="checkbox" checked={s.group_codes.includes(g.code)} onChange={() => updateStep(i, { group_codes: toggleIn(s.group_codes, g.code) })} />
                          {g.label}
                        </label>
                      ))}
                    </div>
                    <div className="row">
                      <span className="muted small">Channels:</span>
                      {(channels.data ?? []).map((c) => (
                        <label key={c.code} className="inline small">
                          <input type="checkbox" checked={s.channel_codes.includes(c.code)} onChange={() => updateStep(i, { channel_codes: toggleIn(s.channel_codes, c.code) })} />
                          {c.label}
                        </label>
                      ))}
                      {(channels.data ?? []).length === 0 && <span className="faint small">none configured</span>}
                    </div>
                  </div>
                  <span className="row nowrap" style={{ gap: 2 }}>
                    <button className="icon small" disabled={i === 0} onClick={() => moveStep(i, -1)} aria-label="Move up">
                      &uarr;
                    </button>
                    <button className="icon small" disabled={i === d.steps.length - 1} onClick={() => moveStep(i, 1)} aria-label="Move down">
                      &darr;
                    </button>
                    <button className="icon small" onClick={() => setD((x) => ({ ...x, steps: x.steps.filter((_, j) => j !== i) }))} aria-label="Remove step">
                      &times;
                    </button>
                  </span>
                </div>
              </div>
            ))}
          </div>
          <datalist id="pim-roles">
            {roleSuggestions.map((r) => (
              <option key={r} value={r} />
            ))}
          </datalist>
        </div>
        {save.isError && <ErrorBox error={save.error} title="Could not save the workflow" />}
        {!isNew && <div className="faint small">Last edited definitions apply to new items; open items keep their current step.</div>}
        {!isNew && d.steps.length > 0 && <div className="faint small">Saved {formatDate(new Date().toISOString(), false)} on save.</div>}
      </div>
    </Dialog>
  );
}
