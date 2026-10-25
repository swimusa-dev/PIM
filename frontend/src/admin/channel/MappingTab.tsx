// EXP-01: Channel mapping editor. Target fields (schema plus mapped targets not in the schema) with a
// metadata-driven attribute picker (attributes grouped by attribute group, core identifiers, or a dotted
// reference path typed by hand), a transforms list editor for the contract ops, the value-mappings summary
// per select attribute, and the gaps box. The save itself lives in ChannelEditor (PUT mapping, RBAC-03).
// Phase 5 (EXP-10): the picker groups and AttributePicker are exported for the Transport tab.

import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useAttributes, useChannels, useGroups } from "../../api/hooks";
import type { AttributeDefinition, ChannelMapping, ChannelMappingUpdate, ChannelTransform, ChannelTransformOp, Condition, ConditionOp, TargetSchema } from "../../api/types";
import { Badge, Empty, Spinner } from "../../components/Common";
import { buildFieldCatalog } from "../../grid/fields";
import { COND_OPS, FieldSelect } from "../Rules";

// The only hard-coded identifiers (DM-01).
const CORE_KEYS: { key: string; label: string }[] = [
  { key: "style_number", label: "Style number" },
  { key: "color_code", label: "Color code" },
  { key: "size", label: "Size" },
  { key: "sku", label: "SKU" },
  { key: "upc", label: "UPC" },
];
const CUSTOM = "__custom";

export const TRANSFORM_OPS: { op: ChannelTransformOp; label: string }[] = [
  { op: "concatenate", label: "Concatenate" },
  { op: "format", label: "Format template" },
  { op: "unit_convert", label: "Unit convert" },
  { op: "conditional", label: "Conditional" },
  { op: "case", label: "Change case" },
  { op: "truncate", label: "Truncate" },
];

function defaultArgs(op: ChannelTransformOp): Record<string, unknown> {
  switch (op) {
    case "concatenate":
      return { parts: [], separator: " " };
    case "format":
      return { template: "" };
    case "unit_convert":
      return { from: "", to: "" };
    case "conditional":
      return { when: { field: "", op: "eq", value: "" }, then: "", else: "" };
    case "case":
      return { mode: "upper" };
    case "truncate":
      return { max_length: 255 };
  }
}

export interface PickerGroup {
  label: string;
  options: { value: string; label: string; attr?: AttributeDefinition }[];
}

/** Attribute picker groups shared with the Phase 5 Transport tab (feed column sources, Walmart variant attributes). */
export function useAttributePickerGroups(): { groups: PickerGroup[]; loading: boolean; byCode: Map<string, AttributeDefinition> } {
  const attrs = useAttributes();
  const groups = useGroups();
  return useMemo(() => {
    const gByCode = new Map((groups.data ?? []).map((g) => [g.code, g]));
    const sorted = (attrs.data ?? [])
      .filter((a) => a.status !== "deprecated")
      .slice()
      .sort((a, b) => {
        const ga = gByCode.get(a.group_code)?.sort_order ?? 999;
        const gb = gByCode.get(b.group_code)?.sort_order ?? 999;
        return ga - gb || a.sort_order - b.sort_order || a.label.localeCompare(b.label);
      });
    const out: PickerGroup[] = [{ label: "Core identifiers", options: CORE_KEYS.map((k) => ({ value: k.key, label: k.label })) }];
    const m = new Map<string, PickerGroup>();
    for (const a of sorted) {
      const label = gByCode.get(a.group_code)?.label ?? a.group_code;
      const g = m.get(label) ?? { label, options: [] };
      g.options.push({ value: a.code, label: a.level.startsWith("ref:") ? `${a.label} (${a.level})` : a.label, attr: a });
      m.set(label, g);
    }
    out.push(...m.values());
    return { groups: out, loading: attrs.isLoading || groups.isLoading, byCode: new Map(sorted.map((a) => [a.code, a])) };
  }, [attrs.data, attrs.isLoading, groups.data, groups.isLoading]);
}

/** Attribute picker: attributes by group, core identifiers, or a dotted reference path (e.g. fabric.fabric_story). */
export function AttributePicker({ value, onChange, groups, disabled }: { value: string; onChange: (v: string) => void; groups: PickerGroup[]; disabled?: boolean }) {
  const known = useMemo(() => new Set(groups.flatMap((g) => g.options.map((o) => o.value))), [groups]);
  const isCustom = value !== "" && !known.has(value);
  const selectValue = isCustom ? CUSTOM : value;
  return (
    <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>
      <select
        value={selectValue}
        disabled={disabled}
        onChange={(e) => {
          const v = e.target.value;
          if (v === CUSTOM) onChange(value && isCustom ? value : "custom.path");
          else onChange(v);
        }}
      >
        <option value="">Not mapped</option>
        {groups.map((g) => (
          <optgroup key={g.label} label={g.label}>
            {g.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </optgroup>
        ))}
        <option value={CUSTOM}>Reference path (typed)</option>
      </select>
      {isCustom && (
        <input
          className="mono"
          value={value}
          disabled={disabled}
          placeholder="fabric.fabric_story"
          title="Dotted path through a reference entity attribute, e.g. fabric.fabric_story"
          style={{ width: 170 }}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </span>
  );
}

export function computeGaps(schema: TargetSchema | undefined, attributeMapping: Record<string, string>, server: ChannelMapping | undefined) {
  if (!schema || schema.fields.length === 0) return server?.gaps ?? { required_fields_unmapped: [], mapped_fields_missing_in_schema: [] };
  const names = new Set(schema.fields.map((f) => f.name));
  return {
    required_fields_unmapped: schema.fields.filter((f) => f.required && !attributeMapping[f.name]).map((f) => f.name),
    mapped_fields_missing_in_schema: Object.keys(attributeMapping).filter((t) => attributeMapping[t] && !names.has(t)),
  };
}

export function MappingTab({
  schema,
  server,
  draft,
  setDraft,
  canEdit,
}: {
  schema: TargetSchema | undefined;
  server: ChannelMapping;
  draft: ChannelMappingUpdate;
  setDraft: (d: ChannelMappingUpdate) => void;
  canEdit: boolean;
}) {
  const picker = useAttributePickerGroups();
  const channels = useChannels();
  const attrs = useAttributes();
  const groups = useGroups();
  // Condition fields for the conditional transform: same catalog as the rules engine (core keys plus attr:<code>).
  const condFields = useMemo(
    () => buildFieldCatalog("sku", attrs.data ?? [], groups.data ?? [], channels.data ?? []).filter((f) => f.kind === "core" || f.kind === "attr"),
    [attrs.data, groups.data, channels.data],
  );

  const rows = useMemo(() => {
    const fields = schema?.fields ?? [];
    const names = new Set(fields.map((f) => f.name));
    const extra = Object.keys(draft.attribute_mapping).filter((t) => !names.has(t));
    return [...fields.map((f) => ({ name: f.name, field: f })), ...extra.map((name) => ({ name, field: null }))];
  }, [schema, draft.attribute_mapping]);

  const gaps = computeGaps(schema, draft.attribute_mapping, server);
  const setMapping = (target: string, attr: string) => {
    const next = { ...draft.attribute_mapping };
    if (attr) next[target] = attr;
    else delete next[target];
    setDraft({ ...draft, attribute_mapping: next });
  };
  const setTransforms = (t: ChannelTransform[]) => setDraft({ ...draft, transforms: t });
  const updateTransform = (i: number, patch: Partial<ChannelTransform>) => setTransforms(draft.transforms.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  const updateArgs = (i: number, patch: Record<string, unknown>) => updateTransform(i, { args: { ...draft.transforms[i].args, ...patch } });
  const targetNames = Array.from(new Set([...rows.map((r) => r.name), ...draft.transforms.map((t) => t.target)])).filter(Boolean);

  if (picker.loading) return <Spinner label="Loading attributes" />;

  return (
    <div className="map-layout">
      <div className="stack gap16">
        <div className="panel">
          <div className="panel-header">
            <h3>
              Target fields <span className="muted small">({rows.length})</span>
            </h3>
            <span className="muted small">Pick the PIM attribute that feeds each target field.</span>
          </div>
          <div className="panel-body flush" style={{ maxHeight: 520, overflow: "auto" }}>
            {rows.length === 0 ? (
              <Empty title="No target fields">Load a target schema on the Target schema tab, or add a transform below to map a field by name.</Empty>
            ) : (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Target field</th>
                    <th>Type</th>
                    <th>PIM attribute</th>
                    <th>Transforms</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const mapped = draft.attribute_mapping[r.name] ?? "";
                    const tCount = draft.transforms.filter((t) => t.target === r.name).length;
                    const attr = picker.byCode.get(mapped);
                    return (
                      <tr key={r.name}>
                        <td>
                          <span className="mono">{r.name}</span>{" "}
                          {r.field?.required && <Badge color="red">required</Badge>}
                          {!r.field && (
                            <Badge color="amber" title="This target is mapped but the loaded schema has no such field">
                              not in schema
                            </Badge>
                          )}
                          {r.field?.group && <div className="faint small">{r.field.group}</div>}
                        </td>
                        <td className="small">
                          {r.field?.type ?? <span className="faint">unknown</span>}
                          {r.field?.max_length ? <div className="faint">max {r.field.max_length}</div> : null}
                          {r.field?.enum && r.field.enum.length > 0 ? <div className="faint">{r.field.enum.length} enum values</div> : null}
                        </td>
                        <td>
                          <AttributePicker value={mapped} groups={picker.groups} disabled={!canEdit} onChange={(v) => setMapping(r.name, v)} />
                          {attr?.option_list_code && (
                            <div className="faint small">
                              Select attribute, list <span className="mono">{attr.option_list_code}</span>
                            </div>
                          )}
                        </td>
                        <td>
                          {tCount > 0 ? <Badge color="teal">{tCount}</Badge> : <span className="faint">none</span>}{" "}
                          {canEdit && (
                            <button className="small link" onClick={() => setTransforms([...draft.transforms, { target: r.name, op: "format", args: defaultArgs("format") }])}>
                              Add
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>
              Transforms <span className="muted small">({draft.transforms.length})</span>
            </h3>
            {canEdit && (
              <button className="small" onClick={() => setTransforms([...draft.transforms, { target: targetNames[0] ?? "", op: "format", args: defaultArgs("format") }])}>
                Add transform
              </button>
            )}
          </div>
          <fieldset className="panel-body transforms" disabled={!canEdit} style={{ border: "none", margin: 0 }}>
            {draft.transforms.length === 0 && <span className="muted">No transforms. Mapped values are sent as they are (option codes go through the option list channel mappings).</span>}
            {draft.transforms.map((t, i) => (
              <div className="transform-row" key={i}>
                <input className="mono" list="channel-transform-targets" value={t.target} disabled={!canEdit} placeholder="target field" style={{ width: 150 }} onChange={(e) => updateTransform(i, { target: e.target.value })} />
                <select value={t.op} disabled={!canEdit} onChange={(e) => updateTransform(i, { op: e.target.value as ChannelTransformOp, args: defaultArgs(e.target.value as ChannelTransformOp) })}>
                  {TRANSFORM_OPS.map((o) => (
                    <option key={o.op} value={o.op}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <TransformArgs t={t} disabled={!canEdit} onChange={(patch) => updateArgs(i, patch)} picker={picker.groups} condFields={condFields} />
                {canEdit && (
                  <button className="icon small" aria-label="Remove transform" onClick={() => setTransforms(draft.transforms.filter((_, j) => j !== i))}>
                    x
                  </button>
                )}
              </div>
            ))}
            <datalist id="channel-transform-targets">
              {targetNames.map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
          </fieldset>
        </div>
      </div>

      <div className="stack gap16">
        <div className={`panel${gaps.required_fields_unmapped.length + gaps.mapped_fields_missing_in_schema.length > 0 ? " gaps-warn" : ""}`}>
          <div className="panel-header">
            <h3>Gaps</h3>
          </div>
          <div className="panel-body stack">
            {gaps.required_fields_unmapped.length === 0 && gaps.mapped_fields_missing_in_schema.length === 0 && <span className="muted">No gaps: every required field is mapped and every mapped field exists in the schema.</span>}
            {gaps.required_fields_unmapped.length > 0 && (
              <div>
                <div className="small muted mb8">Required fields without a mapping ({gaps.required_fields_unmapped.length})</div>
                <div className="chips">
                  {gaps.required_fields_unmapped.map((f) => (
                    <Badge key={f} color="red">
                      {f}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {gaps.mapped_fields_missing_in_schema.length > 0 && (
              <div>
                <div className="small muted mb8">Mapped fields missing in the schema ({gaps.mapped_fields_missing_in_schema.length})</div>
                <div className="chips">
                  {gaps.mapped_fields_missing_in_schema.map((f) => (
                    <Badge key={f} color="amber">
                      {f}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Value mappings</h3>
            <Link to="/admin/option-lists" className="small">
              Edit in Option lists
            </Link>
          </div>
          <div className="panel-body flush">
            {server.value_mappings.length === 0 ? (
              <div className="empty">No select attributes are mapped to this channel yet.</div>
            ) : (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Attribute</th>
                    <th className="right">Mapped</th>
                    <th>Unmapped values</th>
                  </tr>
                </thead>
                <tbody>
                  {server.value_mappings.map((v) => (
                    <tr key={`${v.attribute_code}:${v.list_code}`}>
                      <td>
                        {picker.byCode.get(v.attribute_code)?.label ?? v.attribute_code}
                        <div className="faint small mono">{v.list_code}</div>
                      </td>
                      <td className="num">{v.mapped}</td>
                      <td>
                        {v.unmapped.length === 0 ? (
                          <Badge color="green">all mapped</Badge>
                        ) : (
                          <div className="chips">
                            {v.unmapped.slice(0, 8).map((u) => (
                              <Badge key={u} color="amber">
                                {u}
                              </Badge>
                            ))}
                            {v.unmapped.length > 8 && <span className="faint small">+{v.unmapped.length - 8} more</span>}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function TransformArgs({
  t,
  disabled,
  onChange,
  picker,
  condFields,
}: {
  t: ChannelTransform;
  disabled: boolean;
  onChange: (patch: Record<string, unknown>) => void;
  picker: PickerGroup[];
  condFields: ReturnType<typeof buildFieldCatalog>;
}) {
  const a = t.args ?? {};
  switch (t.op) {
    case "concatenate": {
      const parts = Array.isArray(a.parts) ? (a.parts as string[]) : [];
      return (
        <>
          <span className="faint">parts</span>
          {parts.map((p, i) => (
            <span key={i} className="chip">
              {p}
              {!disabled && (
                <button aria-label="Remove part" onClick={() => onChange({ parts: parts.filter((_, j) => j !== i) })}>
                  x
                </button>
              )}
            </span>
          ))}
          {!disabled && <AttributePicker value="" groups={picker} onChange={(v) => v && onChange({ parts: [...parts, v] })} />}
          <span className="faint">separator</span>
          <input value={String(a.separator ?? "")} disabled={disabled} style={{ width: 60 }} onChange={(e) => onChange({ separator: e.target.value })} />
        </>
      );
    }
    case "format":
      return (
        <>
          <span className="faint">template</span>
          <input className="mono grow" value={String(a.template ?? "")} disabled={disabled} placeholder="{{attr.style_name}} in {{attr.color_name}}" onChange={(e) => onChange({ template: e.target.value })} />
        </>
      );
    case "unit_convert":
      return (
        <>
          <span className="faint">from</span>
          <input value={String(a.from ?? "")} disabled={disabled} style={{ width: 60 }} placeholder="in" onChange={(e) => onChange({ from: e.target.value })} />
          <span className="faint">to</span>
          <input value={String(a.to ?? "")} disabled={disabled} style={{ width: 60 }} placeholder="cm" onChange={(e) => onChange({ to: e.target.value })} />
        </>
      );
    case "conditional": {
      const when = (a.when ?? { field: "", op: "eq", value: "" }) as Condition;
      const needsValue = when.op !== "empty" && when.op !== "not_empty";
      const setWhen = (patch: Partial<Condition>) => onChange({ when: { ...when, ...patch } });
      return (
        <>
          <span className="faint">when</span>
          <FieldSelect fields={condFields} value={when.field} onChange={(v) => setWhen({ field: v })} />
          <select value={when.op} disabled={disabled} onChange={(e) => setWhen({ op: e.target.value as ConditionOp })}>
            {COND_OPS.map((o) => (
              <option key={o.op} value={o.op}>
                {o.label}
              </option>
            ))}
          </select>
          {needsValue && (
            <input
              value={Array.isArray(when.value) ? when.value.join(", ") : String(when.value ?? "")}
              disabled={disabled}
              placeholder={when.op === "in" ? "comma separated" : "value"}
              style={{ width: 110 }}
              onChange={(e) => setWhen({ value: when.op === "in" ? e.target.value.split(",").map((s) => s.trim()).filter(Boolean) : e.target.value })}
            />
          )}
          <span className="faint">then</span>
          <input value={String(a.then ?? "")} disabled={disabled} style={{ width: 100 }} onChange={(e) => onChange({ then: e.target.value })} />
          <span className="faint">else</span>
          <input value={String(a.else ?? "")} disabled={disabled} style={{ width: 100 }} placeholder="(unchanged)" onChange={(e) => onChange({ else: e.target.value })} />
        </>
      );
    }
    case "case":
      return (
        <>
          <span className="faint">mode</span>
          <select value={String(a.mode ?? "upper")} disabled={disabled} onChange={(e) => onChange({ mode: e.target.value })}>
            <option value="upper">UPPER CASE</option>
            <option value="lower">lower case</option>
            <option value="title">Title Case</option>
            <option value="sentence">Sentence case</option>
          </select>
        </>
      );
    case "truncate":
      return (
        <>
          <span className="faint">max length</span>
          <input type="number" min={1} value={Number(a.max_length ?? 0) || ""} disabled={disabled} style={{ width: 80 }} onChange={(e) => onChange({ max_length: Number(e.target.value) })} />
        </>
      );
  }
}
