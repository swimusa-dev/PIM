// 1.3: Attribute definitions. Table with inline edit of label, group, level, data type, status, owner,
// source of truth, allows N/A, default, validation JSON; add attribute.

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAttributes, useGroups, useOptionLists, useReferenceTypes } from "../api/hooks";
import type { AttributeDefinition, DataType } from "../api/types";
import { Badge, Dialog, Empty, ErrorBox, Spinner, useToast } from "../components/Common";

const DATA_TYPES: DataType[] = [
  "text",
  "rich_text",
  "number",
  "boolean",
  "date",
  "single_select",
  "multi_select",
  "asset_ref",
  "product_ref",
  "reference_entity",
];
const STATUSES = ["proposed", "confirmed", "deprecated"] as const;
const SOURCES = ["erp", "plm", "pim", "channel"] as const;

export function AttributesTab() {
  const attrs = useAttributes();
  const groups = useGroups();
  const optionLists = useOptionLists();
  const refTypes = useReferenceTypes();
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [editing, setEditing] = useState<AttributeDefinition | null>(null);
  const [adding, setAdding] = useState(false);

  const levels = useMemo(() => {
    const base = ["style", "style_color", "sku"];
    const refs = (refTypes.data ?? []).map((t) => `ref:${t.code}`);
    return [...base, ...refs];
  }, [refTypes.data]);

  const rows = useMemo(() => {
    let r = attrs.data ?? [];
    if (groupFilter) r = r.filter((a) => a.group_code === groupFilter);
    if (q) {
      const s = q.toLowerCase();
      r = r.filter((a) => a.code.toLowerCase().includes(s) || a.label.toLowerCase().includes(s));
    }
    const order = new Map((groups.data ?? []).map((g) => [g.code, g.sort_order]));
    return r.slice().sort((a, b) => (order.get(a.group_code) ?? 999) - (order.get(b.group_code) ?? 999) || a.sort_order - b.sort_order);
  }, [attrs.data, groups.data, groupFilter, q]);

  const save = useMutation({
    mutationFn: (a: AttributeDefinition & { isNew?: boolean }) => {
      const { isNew, ...body } = a;
      return isNew ? api.metadata.createAttribute(body) : api.metadata.updateAttribute(body.code, body);
    },
    onSuccess: () => {
      toast("Attribute saved", "ok");
      qc.invalidateQueries({ queryKey: ["metadata"] });
      setEditing(null);
      setAdding(false);
    },
    onError: (e) => toast(`Save failed: ${(e as Error).message}`, "error"),
  });

  if (attrs.isLoading || groups.isLoading) return <Spinner label="Loading attributes" />;
  if (attrs.isError) return <ErrorBox error={attrs.error} title="Could not load attributes" />;

  return (
    <div>
      <div className="row mb8" style={{ justifyContent: "space-between" }}>
        <div className="row">
          <input placeholder="Find by code or label" value={q} onChange={(e) => setQ(e.target.value)} />
          <select value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}>
            <option value="">All groups</option>
            {(groups.data ?? []).map((g) => (
              <option key={g.code} value={g.code}>
                {g.label}
              </option>
            ))}
          </select>
          <span className="muted small">{rows.length} attributes</span>
        </div>
        <button className="primary" onClick={() => setAdding(true)}>
          Add attribute
        </button>
      </div>
      {rows.length === 0 ? (
        <Empty title="No attributes">Add an attribute or load the seed file to define the product model.</Empty>
      ) : (
        <div className="panel" style={{ overflow: "auto" }}>
          <table className="data compact">
            <thead>
              <tr>
                <th>Code</th>
                <th>Label</th>
                <th>Group</th>
                <th>Level</th>
                <th>Type</th>
                <th>Status</th>
                <th>Owner</th>
                <th>Source of truth</th>
                <th>Channel</th>
                <th>N/A</th>
                <th>Default</th>
                <th>Validation</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.code}>
                  <td className="mono">{a.code}</td>
                  <td>{a.label}</td>
                  <td>{groups.data?.find((g) => g.code === a.group_code)?.label ?? a.group_code}</td>
                  <td className="mono">{a.level}</td>
                  <td>
                    {a.data_type}
                    {a.option_list_code && <div className="faint mono small">{a.option_list_code}</div>}
                    {a.reference_type_code && <div className="faint mono small">{a.reference_type_code}</div>}
                    {a.unit && <div className="faint small">unit {a.unit}</div>}
                  </td>
                  <td>
                    <Badge color={a.status === "confirmed" ? "green" : a.status === "deprecated" ? "red" : "amber"}>{a.status}</Badge>
                  </td>
                  <td>
                    {a.owner_role ?? ""}
                    {a.owner_person && <div className="faint small">{a.owner_person}</div>}
                  </td>
                  <td>{a.source_of_truth}</td>
                  <td>{a.channel_scopable ? "yes" : ""}</td>
                  <td>{a.allows_not_applicable ? "yes" : ""}</td>
                  <td className="mono small">{a.default_value ?? ""}</td>
                  <td className="mono small">{Object.keys(a.validation ?? {}).length ? JSON.stringify(a.validation) : ""}</td>
                  <td>
                    <button className="small" onClick={() => setEditing(a)}>
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(editing || adding) && (
        <AttributeDialog
          initial={
            editing ?? {
              code: "",
              label: "",
              data_type: "text",
              level: "style",
              group_code: groups.data?.[0]?.code ?? "",
              sort_order: (attrs.data?.length ?? 0) + 1,
              validation: {},
              channel_scopable: false,
              allows_not_applicable: false,
              status: "proposed",
              source_of_truth: "pim",
            }
          }
          isNew={adding}
          levels={levels}
          groups={(groups.data ?? []).map((g) => ({ code: g.code, label: g.label }))}
          optionLists={(optionLists.data ?? []).map((l) => ({ code: l.code, label: l.label }))}
          refTypes={(refTypes.data ?? []).map((t) => ({ code: t.code, label: t.label }))}
          busy={save.isPending}
          error={save.error}
          onClose={() => {
            setEditing(null);
            setAdding(false);
          }}
          onSave={(a) => save.mutate({ ...a, isNew: adding })}
        />
      )}
    </div>
  );
}

function AttributeDialog({
  initial,
  isNew,
  levels,
  groups,
  optionLists,
  refTypes,
  busy,
  error,
  onClose,
  onSave,
}: {
  initial: AttributeDefinition;
  isNew: boolean;
  levels: string[];
  groups: { code: string; label: string }[];
  optionLists: { code: string; label: string }[];
  refTypes: { code: string; label: string }[];
  busy: boolean;
  error: unknown;
  onClose: () => void;
  onSave: (a: AttributeDefinition) => void;
}) {
  const [a, setA] = useState<AttributeDefinition>(initial);
  const [validationText, setValidationText] = useState(JSON.stringify(initial.validation ?? {}, null, 0));
  const [validationError, setValidationError] = useState<string | null>(null);
  const set = <K extends keyof AttributeDefinition>(k: K, v: AttributeDefinition[K]) => setA((x) => ({ ...x, [k]: v }));
  const needsList = a.data_type === "single_select" || a.data_type === "multi_select";
  const needsRef = a.data_type === "reference_entity";
  const codeOk = /^[a-z][a-z0-9_]*$/.test(a.code);

  const submit = () => {
    let validation = {};
    try {
      validation = validationText.trim() ? JSON.parse(validationText) : {};
      setValidationError(null);
    } catch {
      setValidationError("Validation must be valid JSON, for example {\"max_length\": 120}");
      return;
    }
    onSave({ ...a, validation });
  };

  return (
    <Dialog
      title={isNew ? "Add attribute" : `Edit attribute ${a.code}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="primary" onClick={submit} disabled={busy || !codeOk || !a.label.trim() || !a.group_code}>
            {busy ? "Saving" : "Save"}
          </button>
        </>
      }
    >
      <div className="form-grid">
        <label className="field">
          Code (snake_case, cannot change later)
          <input value={a.code} disabled={!isNew} onChange={(e) => set("code", e.target.value)} className={a.code && !codeOk ? "invalid" : ""} />
        </label>
        <label className="field">
          Label
          <input value={a.label} onChange={(e) => set("label", e.target.value)} />
        </label>
        <label className="field">
          Group
          <select value={a.group_code} onChange={(e) => set("group_code", e.target.value)}>
            {groups.map((g) => (
              <option key={g.code} value={g.code}>
                {g.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Level
          <select value={a.level} onChange={(e) => set("level", e.target.value)}>
            {levels.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Data type
          <select value={a.data_type} onChange={(e) => set("data_type", e.target.value as DataType)}>
            {DATA_TYPES.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        {needsList && (
          <label className="field">
            Option list
            <select value={a.option_list_code ?? ""} onChange={(e) => set("option_list_code", e.target.value || null)}>
              <option value="">choose</option>
              {optionLists.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>
        )}
        {needsRef && (
          <label className="field">
            Reference type
            <select value={a.reference_type_code ?? ""} onChange={(e) => set("reference_type_code", e.target.value || null)}>
              <option value="">choose</option>
              {refTypes.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
        )}
        {a.data_type === "number" && (
          <label className="field">
            Unit (required for measurements and weights)
            <input value={a.unit ?? ""} onChange={(e) => set("unit", e.target.value || null)} placeholder="in, cm, oz, g" />
          </label>
        )}
        <label className="field">
          Status
          <select value={a.status} onChange={(e) => set("status", e.target.value as AttributeDefinition["status"])}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Source of truth
          <select value={a.source_of_truth} onChange={(e) => set("source_of_truth", e.target.value as AttributeDefinition["source_of_truth"])}>
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Owner role
          <input value={a.owner_role ?? ""} onChange={(e) => set("owner_role", e.target.value || null)} />
        </label>
        <label className="field">
          Owner person
          <input value={a.owner_person ?? ""} onChange={(e) => set("owner_person", e.target.value || null)} placeholder="email" />
        </label>
        <label className="field">
          Sort order
          <input type="number" value={a.sort_order} onChange={(e) => set("sort_order", Number(e.target.value))} />
        </label>
        <label className="field">
          Default value (applied as source_type default, GOV-06)
          <input value={a.default_value ?? ""} onChange={(e) => set("default_value", e.target.value || null)} />
        </label>
        <label className="field">
          Example value
          <input value={a.example_value ?? ""} onChange={(e) => set("example_value", e.target.value || null)} />
        </label>
        <label className="field" style={{ gridColumn: "1 / -1" }}>
          Help text
          <input value={a.help_text ?? ""} onChange={(e) => set("help_text", e.target.value || null)} />
        </label>
        <label className="field" style={{ gridColumn: "1 / -1" }}>
          Validation JSON (min_length, max_length, regex, min, max)
          <input value={validationText} onChange={(e) => setValidationText(e.target.value)} className={validationError ? "invalid mono" : "mono"} />
          {validationError && <span className="field-error">{validationError}</span>}
        </label>
        <label className="inline">
          <input type="checkbox" checked={a.channel_scopable} onChange={(e) => set("channel_scopable", e.target.checked)} /> Channel scopable
        </label>
        <label className="inline">
          <input type="checkbox" checked={a.allows_not_applicable} onChange={(e) => set("allows_not_applicable", e.target.checked)} /> Allows Not applicable
        </label>
      </div>
      {error ? <ErrorBox error={error} title="Save failed" /> : null}
    </Dialog>
  );
}
