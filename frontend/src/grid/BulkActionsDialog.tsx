// DM-04: Bulk actions dialog. Chooses the kind and params (metadata-driven pickers), previews the first
// 20 changes and the total, runs, polls until done and shows the report.

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { canEdit, useAttributes, useChannels, useFamilies, useGroups, useMe, useOptionLists, useWorkflows } from "../api/hooks";
import type { AttributeDefinition, BulkAction, BulkKind, BulkSelection, Level, OptionList, SavedView } from "../api/types";
import { Badge, Dialog, ErrorBox, Spinner, StatusBadge } from "../components/Common";
import { ValueEditor } from "../components/ValueEditor";
import { attributeAppliesAtLevel } from "./fields";
import { displayValue } from "../lib/format";

export const BULK_KINDS: { kind: BulkKind; label: string; help: string }[] = [
  { kind: "set_value", label: "Set value", help: "Write one value to an attribute on every selected product." },
  { kind: "clear_value", label: "Clear value", help: "Empty an attribute on every selected product." },
  { kind: "add_option", label: "Add options", help: "Add options to a multi-select attribute, keeping the existing ones." },
  { kind: "remove_option", label: "Remove options", help: "Remove options from a multi-select attribute." },
  { kind: "find_replace", label: "Find and replace", help: "Replace text inside a text attribute." },
  { kind: "copy_attribute", label: "Copy attribute", help: "Copy the value of one attribute into another." },
  { kind: "change_family", label: "Change family", help: "Move the selected products to another family." },
  { kind: "assign_workflow", label: "Assign workflow", help: "Start a workflow for the selected products." },
  { kind: "run_ai", label: "Run AI", help: "Generate a value with an AI task; results land as drafts." },
  { kind: "send_for_approval", label: "Send for approval", help: "Submit the pending drafts on the selected products." },
];

export function bulkStatusColor(status: string): string | undefined {
  return status === "succeeded" ? "green" : status === "failed" ? "red" : status === "rolled_back" ? "purple" : status === "preview" ? undefined : "amber";
}

export function BulkReport({ action }: { action: BulkAction }) {
  const r = action.report;
  return (
    <div className="stack">
      <div className="row gap16">
        <span>
          Changed <b>{r?.changed ?? 0}</b>
        </span>
        <span>
          Skipped <b>{r?.skipped ?? 0}</b>
        </span>
        <span style={{ color: r?.failed ? "var(--red)" : undefined }}>
          Failed <b>{r?.failed ?? 0}</b>
        </span>
        {action.change_set_id && <span className="faint small mono">change set {action.change_set_id}</span>}
      </div>
      {r?.items && r.items.length > 0 && (
        <div className="panel" style={{ maxHeight: 300, overflow: "auto" }}>
          <table className="data compact">
            <thead>
              <tr>
                <th>Product</th>
                <th>Outcome</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {r.items.map((it, i) => (
                <tr key={`${it.entity_id}-${i}`}>
                  <td>
                    <Link to={`/products/${encodeURIComponent(it.entity_id)}`}>{it.label}</Link>
                  </td>
                  <td>
                    <StatusBadge status={it.outcome} />
                  </td>
                  <td className="small">{it.reason ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function BulkActionsDialog({
  level,
  entityIds,
  view,
  onClose,
  onDone,
}: {
  level: Level;
  entityIds: string[];
  view: SavedView | null;
  onClose: () => void;
  onDone?: () => void;
}) {
  const me = useMe();
  const attrs = useAttributes();
  const groups = useGroups();
  const optionLists = useOptionLists();
  const families = useFamilies();
  const channels = useChannels();
  const workflows = useWorkflows();

  const [scope, setScope] = useState<"rows" | "view">(entityIds.length > 0 ? "rows" : "view");
  const [kind, setKind] = useState<BulkKind>("set_value");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [preview, setPreview] = useState<BulkAction | null>(null);
  const [runId, setRunId] = useState<string | null>(null);

  const listByCode = useMemo(() => {
    const m: Record<string, OptionList> = {};
    for (const l of optionLists.data ?? []) m[l.code] = l;
    return m;
  }, [optionLists.data]);
  const groupReadOnly = useMemo(() => new Set((groups.data ?? []).filter((g) => g.read_only).map((g) => g.code)), [groups.data]);
  const editable = useMemo(
    () =>
      (attrs.data ?? [])
        .filter((a) => attributeAppliesAtLevel(a, level) && a.level === level && a.status !== "deprecated" && a.source_of_truth !== "erp" && !groupReadOnly.has(a.group_code) && canEdit(me.data, a))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [attrs.data, level, groupReadOnly, me.data],
  );
  const groupLabel = (code: string) => groups.data?.find((g) => g.code === code)?.label ?? code;
  const grouped = useMemo(() => {
    const m = new Map<string, AttributeDefinition[]>();
    for (const a of editable) m.set(a.group_code, [...(m.get(a.group_code) ?? []), a]);
    return Array.from(m.entries());
  }, [editable]);

  const selection: BulkSelection = scope === "view" && view ? { view_id: view.id, level } : { entity_ids: entityIds, level };

  const previewM = useMutation({
    mutationFn: () => api.bulk.preview({ kind, selection, params }),
    onSuccess: (a) => setPreview(a),
  });
  const runM = useMutation({
    mutationFn: () => api.bulk.run(preview!.id),
    onSuccess: (a) => setRunId(a.id),
  });
  const poll = useQuery({
    queryKey: ["bulk", "detail", runId],
    queryFn: () => api.bulk.detail(runId!),
    enabled: !!runId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "queued" || s === "running" || s === "preview" ? 1500 : false;
    },
  });
  const done = poll.data && (poll.data.status === "succeeded" || poll.data.status === "failed");

  const setParam = (k: string, v: unknown) => {
    setParams((p) => ({ ...p, [k]: v }));
    setPreview(null);
  };
  const changeKind = (k: BulkKind) => {
    setKind(k);
    setParams({});
    setPreview(null);
  };

  const attr = typeof params.attribute_code === "string" ? editable.find((a) => a.code === params.attribute_code) : undefined;
  const valid = (() => {
    switch (kind) {
      case "set_value":
        return !!attr && params.value !== undefined;
      case "clear_value":
        return !!attr;
      case "add_option":
      case "remove_option":
        return !!attr && Array.isArray(params.option_codes) && params.option_codes.length > 0;
      case "find_replace":
        return !!attr && typeof params.find === "string" && params.find.length > 0 && params.replace !== undefined;
      case "copy_attribute":
        return !!params.from_attribute && !!params.to_attribute && params.from_attribute !== params.to_attribute;
      case "change_family":
        return !!params.family_code;
      case "assign_workflow":
        return !!params.workflow_code;
      case "run_ai":
        return !!params.task_type && !!params.target_attribute;
      case "send_for_approval":
        return true;
    }
  })();
  const hasSelection = scope === "view" ? !!view : entityIds.length > 0;

  const attrPicker = (param: string, filter?: (a: AttributeDefinition) => boolean, placeholder = "Choose an attribute") => (
    <select value={typeof params[param] === "string" ? (params[param] as string) : ""} onChange={(e) => setParam(param, e.target.value)}>
      <option value="">{placeholder}</option>
      {grouped.map(([g, list]) => {
        const items = filter ? list.filter(filter) : list;
        if (items.length === 0) return null;
        return (
          <optgroup key={g} label={groupLabel(g)}>
            {items.map((a) => (
              <option key={a.code} value={a.code}>
                {a.label}
              </option>
            ))}
          </optgroup>
        );
      })}
    </select>
  );
  const channelPicker = () =>
    attr?.channel_scopable ? (
      <label className="field">
        Channel (optional)
        <select value={typeof params.channel_code === "string" ? (params.channel_code as string) : ""} onChange={(e) => setParam("channel_code", e.target.value || undefined)}>
          <option value="">Global value</option>
          {(channels.data ?? []).map((c) => (
            <option key={c.code} value={c.code}>
              {c.label} override
            </option>
          ))}
        </select>
      </label>
    ) : null;

  const kindInfo = BULK_KINDS.find((k) => k.kind === kind)!;
  const metaLoading = attrs.isLoading || groups.isLoading || optionLists.isLoading;

  return (
    <Dialog
      title="Bulk actions"
      onClose={onClose}
      wide
      footer={
        <>
          {done ? (
            <button
              className="primary"
              onClick={() => {
                onDone?.();
                onClose();
              }}
            >
              Close
            </button>
          ) : (
            <>
              <button onClick={onClose} disabled={runM.isPending || (!!runId && !done)}>
                Cancel
              </button>
              {!preview && (
                <button className="primary" disabled={!valid || !hasSelection || previewM.isPending} onClick={() => previewM.mutate()}>
                  {previewM.isPending ? "Previewing" : "Preview"}
                </button>
              )}
              {preview && !runId && (
                <button className="primary" disabled={runM.isPending || preview.preview.total === 0} onClick={() => runM.mutate()}>
                  {runM.isPending ? "Starting" : `Run on ${preview.preview.total} product${preview.preview.total === 1 ? "" : "s"}`}
                </button>
              )}
            </>
          )}
        </>
      }
    >
      <div className="stack gap16">
        <div>
          <div className="muted small mb8">Apply to</div>
          <div className="row">
            <label className="inline">
              <input type="radio" checked={scope === "rows"} disabled={entityIds.length === 0} onChange={() => { setScope("rows"); setPreview(null); }} />
              Selected rows ({entityIds.length})
            </label>
            <label className="inline">
              <input type="radio" checked={scope === "view"} disabled={!view} onChange={() => { setScope("view"); setPreview(null); }} />
              The whole view{view ? ` "${view.name}"` : ""}
            </label>
          </div>
        </div>

        {!runId && (
          <>
            <div className="form-grid">
              <label className="field">
                Action
                <select value={kind} onChange={(e) => changeKind(e.target.value as BulkKind)}>
                  {BULK_KINDS.map((k) => (
                    <option key={k.kind} value={k.kind}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="help" style={{ alignSelf: "end", paddingBottom: 6 }}>
                {kindInfo.help}
              </div>
            </div>
            {metaLoading && <Spinner label="Loading metadata" />}
            {editable.length === 0 && !metaLoading && kind !== "change_family" && kind !== "assign_workflow" && kind !== "send_for_approval" && (
              <div className="banner warn boxed">You have no editable attributes at the {level} level.</div>
            )}

            <div className="stack">
              {(kind === "set_value" || kind === "clear_value") && (
                <>
                  <label className="field">
                    Attribute
                    {attrPicker("attribute_code")}
                  </label>
                  {kind === "set_value" && attr && (
                    <label className="field">
                      Value
                      <ValueEditor
                        key={attr.code}
                        attr={attr}
                        optionList={attr.option_list_code ? listByCode[attr.option_list_code] : undefined}
                        value={params.value ?? null}
                        onCommit={(v) => setParam("value", v)}
                      />
                      <span className="help">{params.value !== undefined ? `Will set: ${displayValue(params.value, attr, listByCode) || "empty"}` : "Commit the value (Enter or leave the field) before previewing."}</span>
                    </label>
                  )}
                  {channelPicker()}
                </>
              )}
              {(kind === "add_option" || kind === "remove_option") && (
                <>
                  <label className="field">
                    Multi-select attribute
                    {attrPicker("attribute_code", (a) => a.data_type === "multi_select")}
                  </label>
                  {attr && attr.option_list_code && (
                    <div>
                      <div className="muted small mb8">Options</div>
                      <div className="row">
                        {(listByCode[attr.option_list_code]?.values ?? [])
                          .slice()
                          .sort((a, b) => a.sort_order - b.sort_order)
                          .map((o) => {
                            const cur = Array.isArray(params.option_codes) ? (params.option_codes as string[]) : [];
                            return (
                              <label key={o.code} className="inline">
                                <input
                                  type="checkbox"
                                  checked={cur.includes(o.code)}
                                  onChange={() => setParam("option_codes", cur.includes(o.code) ? cur.filter((c) => c !== o.code) : [...cur, o.code])}
                                />
                                {o.label}
                              </label>
                            );
                          })}
                      </div>
                    </div>
                  )}
                </>
              )}
              {kind === "find_replace" && (
                <>
                  <label className="field">
                    Text attribute
                    {attrPicker("attribute_code", (a) => a.data_type === "text" || a.data_type === "rich_text")}
                  </label>
                  <div className="form-grid">
                    <label className="field">
                      Find
                      <input value={typeof params.find === "string" ? (params.find as string) : ""} onChange={(e) => setParam("find", e.target.value)} />
                    </label>
                    <label className="field">
                      Replace with
                      <input value={typeof params.replace === "string" ? (params.replace as string) : ""} onChange={(e) => setParam("replace", e.target.value)} />
                    </label>
                  </div>
                  <div className="row">
                    <label className="inline">
                      <input type="checkbox" checked={!!params.regex} onChange={(e) => setParam("regex", e.target.checked)} /> Regular expression
                    </label>
                    <label className="inline">
                      <input type="checkbox" checked={!!params.case_sensitive} onChange={(e) => setParam("case_sensitive", e.target.checked)} /> Case sensitive
                    </label>
                  </div>
                </>
              )}
              {kind === "copy_attribute" && (
                <div className="form-grid">
                  <label className="field">
                    From attribute
                    <select value={typeof params.from_attribute === "string" ? (params.from_attribute as string) : ""} onChange={(e) => setParam("from_attribute", e.target.value)}>
                      <option value="">Choose</option>
                      {(attrs.data ?? [])
                        .filter((a) => attributeAppliesAtLevel(a, level))
                        .map((a) => (
                          <option key={a.code} value={a.code}>
                            {a.label}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label className="field">
                    To attribute
                    {attrPicker("to_attribute")}
                  </label>
                </div>
              )}
              {kind === "change_family" && (
                <label className="field">
                  Family
                  <select value={typeof params.family_code === "string" ? (params.family_code as string) : ""} onChange={(e) => setParam("family_code", e.target.value)}>
                    <option value="">Choose a family</option>
                    {(families.data ?? []).map((f) => (
                      <option key={f.code} value={f.code}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {kind === "assign_workflow" && (
                <label className="field">
                  Workflow
                  {workflows.isError && <ErrorBox error={workflows.error} title="Could not load workflows" />}
                  <select value={typeof params.workflow_code === "string" ? (params.workflow_code as string) : ""} onChange={(e) => setParam("workflow_code", e.target.value)}>
                    <option value="">Choose a workflow</option>
                    {(workflows.data ?? []).map((w) => (
                      <option key={w.code} value={w.code} disabled={!w.enabled}>
                        {w.label}
                        {w.enabled ? "" : " (disabled)"}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {kind === "run_ai" && (
                <div className="form-grid">
                  <label className="field">
                    Task type
                    <input value={typeof params.task_type === "string" ? (params.task_type as string) : ""} placeholder="e.g. describe, translate" onChange={(e) => setParam("task_type", e.target.value)} />
                  </label>
                  <label className="field">
                    Target attribute
                    {attrPicker("target_attribute")}
                  </label>
                  <label className="field">
                    Prompt template (optional)
                    <input value={typeof params.template_code === "string" ? (params.template_code as string) : ""} onChange={(e) => setParam("template_code", e.target.value || undefined)} />
                  </label>
                </div>
              )}
              {kind === "send_for_approval" && <div className="muted small">Pending drafts on the selected products are submitted to their approvers.</div>}
            </div>
            {previewM.isError && <ErrorBox error={previewM.error} title="Preview failed" />}
          </>
        )}

        {preview && !runId && (
          <div className="panel">
            <div className="panel-header">
              <h3>Preview</h3>
              <span className="muted small">
                {preview.preview.total} product{preview.preview.total === 1 ? "" : "s"} affected, first {preview.preview.sample.length} shown
              </span>
            </div>
            {preview.preview.sample.length === 0 ? (
              <div className="empty">Nothing would change.</div>
            ) : (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>Attribute</th>
                    <th>Before</th>
                    <th>After</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.preview.sample.map((s, i) => {
                    const a = s.attribute_code ? attrs.data?.find((x) => x.code === s.attribute_code) : undefined;
                    return (
                      <tr key={`${s.entity_id}-${i}`}>
                        <td>{s.label}</td>
                        <td>{a?.label ?? s.attribute_code ?? ""}</td>
                        <td className="diff-old">{displayValue(s.before, a, listByCode) || <span className="faint">empty</span>}</td>
                        <td className="diff-new">{displayValue(s.after, a, listByCode) || <span className="faint">empty</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            {runM.isError && <ErrorBox error={runM.error} title="Could not start the action" />}
          </div>
        )}

        {runId && (
          <div className="stack">
            <div className="row">
              <span>Status</span>
              {poll.data ? <Badge color={bulkStatusColor(poll.data.status)}>{poll.data.status.replace(/_/g, " ")}</Badge> : <Spinner />}
              {poll.data && !done && <Spinner label="Running" />}
            </div>
            {poll.isError && <ErrorBox error={poll.error} title="Could not read the action status" />}
            {done && poll.data && <BulkReport action={poll.data} />}
            {done && (
              <div className="muted small">
                Actions can be rolled back from <Link to="/bulk">Bulk actions history</Link>.
              </div>
            )}
          </div>
        )}
      </div>
    </Dialog>
  );
}
