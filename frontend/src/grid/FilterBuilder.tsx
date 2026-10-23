// DM-02: Faceted filter builder (field, op, value) over core fields, attributes, completeness and readiness.

import type { FilterOp, OptionList, QueryFilter } from "../api/types";
import type { FieldDef } from "./fields";
import { FILTER_ONLY_FIELDS } from "./fields";

const OPS: { op: FilterOp; label: string }[] = [
  { op: "eq", label: "is" },
  { op: "neq", label: "is not" },
  { op: "contains", label: "contains" },
  { op: "in", label: "is one of" },
  { op: "empty", label: "is empty" },
  { op: "not_empty", label: "is not empty" },
  { op: "gt", label: ">" },
  { op: "gte", label: ">=" },
  { op: "lt", label: "<" },
  { op: "lte", label: "<=" },
];

function opsFor(field: FieldDef | undefined): FilterOp[] {
  if (!field) return ["eq", "neq", "contains", "in", "empty", "not_empty"];
  if (field.kind === "completeness") return ["eq", "gt", "gte", "lt", "lte"];
  if (field.kind === "readiness") return ["eq", "neq"];
  const dt = field.attr?.data_type;
  if (dt === "number" || dt === "date") return ["eq", "neq", "gt", "gte", "lt", "lte", "empty", "not_empty"];
  if (dt === "boolean") return ["eq", "empty", "not_empty"];
  if (dt === "single_select" || dt === "multi_select") return ["eq", "neq", "in", "empty", "not_empty"];
  return ["eq", "neq", "contains", "in", "empty", "not_empty"];
}

export function FilterBuilder({
  filters,
  onChange,
  fields,
  optionLists,
}: {
  filters: QueryFilter[];
  onChange: (f: QueryFilter[]) => void;
  fields: FieldDef[];
  optionLists: Record<string, OptionList>;
}) {
  const byKey = new Map(fields.map((f) => [f.key, f]));
  const groups = new Map<string, FieldDef[]>();
  for (const f of fields) {
    const arr = groups.get(f.groupLabel) ?? [];
    arr.push(f);
    groups.set(f.groupLabel, arr);
  }

  const update = (i: number, patch: Partial<QueryFilter>) => {
    const next = filters.slice();
    next[i] = { ...next[i], ...patch };
    onChange(next);
  };
  const remove = (i: number) => onChange(filters.filter((_, j) => j !== i));
  const add = () => onChange([...filters, { field: fields[0]?.key ?? "style_number", op: "contains", value: "" }]);

  return (
    <div className="stack" style={{ gap: 4 }}>
      {filters.map((f, i) => {
        const fd = byKey.get(f.field);
        const ops = opsFor(fd);
        const needsValue = f.op !== "empty" && f.op !== "not_empty";
        return (
          <div className="filter-row" key={i}>
            <select
              value={f.field}
              onChange={(e) => {
                const nf = byKey.get(e.target.value);
                const nops = opsFor(nf);
                update(i, { field: e.target.value, op: nops.includes(f.op) ? f.op : nops[0], value: "" });
              }}
            >
              {Array.from(groups.entries()).map(([g, fs]) => (
                <optgroup key={g} label={g}>
                  {fs.map((x) => (
                    <option key={x.key} value={x.key}>
                      {x.label}
                    </option>
                  ))}
                </optgroup>
              ))}
              <optgroup label="Other">
                {FILTER_ONLY_FIELDS.map((x) => (
                  <option key={x.key} value={x.key}>
                    {x.label}
                  </option>
                ))}
              </optgroup>
            </select>
            <select value={f.op} onChange={(e) => update(i, { op: e.target.value as FilterOp })}>
              {OPS.filter((o) => ops.includes(o.op)).map((o) => (
                <option key={o.op} value={o.op}>
                  {o.label}
                </option>
              ))}
            </select>
            {needsValue && <ValueInput field={fd} filter={f} optionLists={optionLists} onChange={(v) => update(i, { value: v })} />}
            <button className="icon small" onClick={() => remove(i)} title="Remove filter" aria-label="Remove filter">
              &times;
            </button>
          </div>
        );
      })}
      <div>
        <button className="small" onClick={add}>
          + Add filter
        </button>
        {filters.length > 0 && (
          <button className="small link" style={{ marginLeft: 8 }} onClick={() => onChange([])}>
            Clear all
          </button>
        )}
      </div>
    </div>
  );
}

function ValueInput({
  field,
  filter,
  optionLists,
  onChange,
}: {
  field: FieldDef | undefined;
  filter: QueryFilter;
  optionLists: Record<string, OptionList>;
  onChange: (v: unknown) => void;
}) {
  const v = filter.value;
  if (field?.kind === "readiness") {
    return (
      <select value={v === true ? "true" : v === false ? "false" : ""} onChange={(e) => onChange(e.target.value === "true")}>
        <option value="">choose</option>
        <option value="true">Ready</option>
        <option value="false">Not ready</option>
      </select>
    );
  }
  if (field?.kind === "completeness") {
    return (
      <input
        type="number"
        min={0}
        max={100}
        style={{ width: 80 }}
        value={typeof v === "number" ? v : ""}
        onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
        placeholder="%"
      />
    );
  }
  if (field?.key === "lifecycle_status") {
    return (
      <select value={String(v ?? "")} onChange={(e) => onChange(e.target.value)}>
        <option value="">choose</option>
        <option value="active">active</option>
        <option value="new">new</option>
        <option value="discontinued">discontinued</option>
      </select>
    );
  }
  if (filter.field === "ai_generated" || filter.field === "missing_images" || field?.attr?.data_type === "boolean") {
    return (
      <select value={v === true ? "true" : v === false ? "false" : ""} onChange={(e) => onChange(e.target.value === "true")}>
        <option value="">choose</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  }
  if (filter.field === "approval_state") {
    return (
      <select value={String(v ?? "")} onChange={(e) => onChange(e.target.value)}>
        <option value="">choose</option>
        {["draft", "proposed", "approved", "rejected"].map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    );
  }
  const list = field?.attr?.option_list_code ? optionLists[field.attr.option_list_code] : undefined;
  if (list && filter.op !== "in") {
    return (
      <select value={String(v ?? "")} onChange={(e) => onChange(e.target.value)}>
        <option value="">choose</option>
        {list.values
          .slice()
          .sort((a, b) => a.sort_order - b.sort_order)
          .map((o) => (
            <option key={o.code} value={o.code}>
              {o.label}
            </option>
          ))}
      </select>
    );
  }
  if (filter.op === "in") {
    const text = Array.isArray(v) ? v.join(", ") : String(v ?? "");
    return (
      <input
        value={text}
        placeholder="comma separated"
        onChange={(e) => onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
      />
    );
  }
  const type = field?.attr?.data_type === "number" ? "number" : field?.attr?.data_type === "date" ? "date" : "text";
  return (
    <input
      type={type}
      value={v === null || v === undefined ? "" : String(v)}
      onChange={(e) => onChange(type === "number" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value)}
      placeholder="value"
    />
  );
}

export function describeFilter(f: QueryFilter, fields: FieldDef[]): string {
  const fd = fields.find((x) => x.key === f.field);
  const label = fd?.label ?? FILTER_ONLY_FIELDS.find((x) => x.key === f.field)?.label ?? f.field;
  const op = OPS.find((o) => o.op === f.op)?.label ?? f.op;
  const val = f.op === "empty" || f.op === "not_empty" ? "" : Array.isArray(f.value) ? f.value.join(", ") : String(f.value ?? "");
  return `${label} ${op} ${val}`.trim();
}
