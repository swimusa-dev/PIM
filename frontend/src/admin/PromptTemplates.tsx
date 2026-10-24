// AI-02, AI-05, AI-07: Prompt templates manager (Admin > AI). Table (code, label, task type, target, channel,
// family, status, version, eval gate), create and edit dialog with every contract field (body with a placeholder
// helper for the chosen input attributes, input attributes grouped by attribute group, shot types from
// /api/metadata/shot-types, output attributes for extract / restructure, model task, max length), "Preview on a
// product" (entity id or style number search through POST /api/products/query), Activate with the 409 eval-gate
// message surfaced, and a version history expander.

import { Fragment, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { aiApi, api, ApiError, errorMessage } from "../api/client";
import { isAdmin, useAttributes, useBrandVoices, useChannels, useFamilies, useGroups, useMe, useShotTypes } from "../api/hooks";
import type { AttributeDefinition, Level, ModelTask, PromptTemplate, PromptTemplateInput, TaskType, TemplatePreview } from "../api/types";
import { Badge, Dialog, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { EvalGatePill, TASK_TYPES, TaskBadge, TemplateStatusPill } from "../ai/shared";
import { formatDate } from "../lib/format";

const EMPTY: PromptTemplateInput = {
  code: "",
  label: "",
  task_type: "generate",
  target_attribute: null,
  output_attributes: [],
  channel_code: null,
  family_code: null,
  brand_code: "",
  body: "",
  input_attributes: [],
  input_shot_types: [],
  accepts_text_input: false,
  accepts_document: false,
  max_length: null,
  model_task: "copy",
};

const MULTI_TARGET: TaskType[] = ["extract", "restructure"];

export function PromptTemplatesTab() {
  const me = useMe();
  const admin = isAdmin(me.data);
  const qc = useQueryClient();
  const toast = useToast();
  const templates = useQuery({ queryKey: ["ai", "templates", {}], queryFn: () => aiApi.templates() });
  const attrs = useAttributes();
  const [editing, setEditing] = useState<{ t: PromptTemplate | null } | null>(null);
  const [previewing, setPreviewing] = useState<PromptTemplate | null>(null);
  const [history, setHistory] = useState<string | null>(null);
  const [activateError, setActivateError] = useState<Record<string, string>>({});

  const attrByCode = useMemo(() => new Map((attrs.data ?? []).map((a) => [a.code, a])), [attrs.data]);
  const activate = useMutation({
    mutationFn: (code: string) => aiApi.activateTemplate(code),
    onSuccess: (t) => {
      toast(`Template ${t.label} is active.`, "ok");
      setActivateError((e) => ({ ...e, [t.code]: "" }));
      qc.invalidateQueries({ queryKey: ["ai", "templates"] });
    },
    onError: (e, code) => {
      const msg = e instanceof ApiError && e.status === 409 ? `Blocked by the evaluation gate: ${e.message}` : errorMessage(e);
      setActivateError((x) => ({ ...x, [code]: msg }));
    },
  });
  const retire = useMutation({
    mutationFn: (code: string) => aiApi.updateTemplate(code, { status: "retired" }),
    onSuccess: () => {
      toast("Template retired.", "ok");
      qc.invalidateQueries({ queryKey: ["ai", "templates"] });
    },
    onError: (e) => toast(`Could not retire: ${errorMessage(e)}`, "error"),
  });

  const targetText = (t: PromptTemplate) => {
    const codes = t.output_attributes.length ? t.output_attributes : t.target_attribute ? [t.target_attribute] : [];
    return codes.map((c) => attrByCode.get(c)?.label ?? c).join(", ");
  };
  const sorted = useMemo(() => (templates.data ?? []).slice().sort((a, b) => a.task_type.localeCompare(b.task_type) || a.label.localeCompare(b.label)), [templates.data]);

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="muted small">
          A template renders a prompt from the product's attributes, the brand voice and optional inputs. New templates start as drafts; a
          draft can be previewed and evaluated, and activation is blocked when the evaluation gate fails.
        </span>
        {admin && (
          <button className="primary" onClick={() => setEditing({ t: null })}>
            New template
          </button>
        )}
      </div>
      {templates.isLoading && <Spinner label="Loading templates" />}
      {templates.isError && <ErrorBox error={templates.error} title="Could not load templates" />}
      {templates.data && sorted.length === 0 && <Empty title="No prompt templates yet">Create one to make a task available in Ask AI and bulk runs.</Empty>}
      {sorted.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Code</th>
                <th>Label</th>
                <th>Task</th>
                <th>Target</th>
                <th>Channel</th>
                <th>Family</th>
                <th>Status</th>
                <th className="right">Version</th>
                <th>Eval gate</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((t) => (
                <Fragment key={t.code}>
                  <tr className={history === t.code ? "expanded" : ""}>
                    <td className="mono small">{t.code}</td>
                    <td>
                      <b>{t.label}</b>
                      <div className="faint small">
                        {t.brand_code} / {t.model_task} endpoint
                      </div>
                    </td>
                    <td>
                      <TaskBadge task={t.task_type} />
                    </td>
                    <td className="small">{targetText(t) || <span className="faint">none</span>}</td>
                    <td>{t.channel_code || <span className="faint">any</span>}</td>
                    <td>{t.family_code || <span className="faint">any</span>}</td>
                    <td>
                      <TemplateStatusPill status={t.status} />
                      {activateError[t.code] && <div className="field-error small">{activateError[t.code]}</div>}
                    </td>
                    <td className="num">{t.version}</td>
                    <td>
                      <EvalGatePill gate={t.eval_gate} />
                    </td>
                    <td className="nowrap">
                      <button className="small" onClick={() => setEditing({ t })}>
                        {admin ? "Edit" : "View"}
                      </button>{" "}
                      <button className="small" onClick={() => setPreviewing(t)}>
                        Preview
                      </button>{" "}
                      {admin && t.status !== "active" && (
                        <>
                          <button className="small primary" disabled={activate.isPending} onClick={() => activate.mutate(t.code)}>
                            Activate
                          </button>{" "}
                        </>
                      )}
                      {admin && t.status === "active" && (
                        <>
                          <button className="small" disabled={retire.isPending} onClick={() => retire.mutate(t.code)}>
                            Retire
                          </button>{" "}
                        </>
                      )}
                      <button className="small" onClick={() => setHistory(history === t.code ? null : t.code)}>
                        {history === t.code ? "Hide history" : "History"}
                      </button>
                    </td>
                  </tr>
                  {history === t.code && (
                    <tr className="expanded-row">
                      <td colSpan={10}>
                        <VersionHistory code={t.code} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <TemplateEditor template={editing.t} editable={admin} onClose={() => setEditing(null)} />}
      {previewing && <PreviewDialog template={previewing} onClose={() => setPreviewing(null)} />}
    </div>
  );
}

function VersionHistory({ code }: { code: string }) {
  const q = useQuery({ queryKey: ["ai", "template", code], queryFn: () => aiApi.template(code) });
  if (q.isLoading) return <Spinner label="Loading versions" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load the version history" />;
  const versions = (q.data?.versions ?? []).slice().sort((a, b) => b.version - a.version);
  if (versions.length === 0) return <span className="faint small">No version history.</span>;
  return (
    <div className="stack">
      {versions.map((v) => (
        <details key={v.version} open={v.version === q.data?.version}>
          <summary>
            <b>v{v.version}</b> <span className="muted small">{formatDate(v.updated_at)}{v.updated_by ? ` by ${v.updated_by}` : ""}</span>
            {v.note && <span className="small"> : {v.note}</span>}
          </summary>
          <pre className="ai-prompt">{v.body}</pre>
        </details>
      ))}
    </div>
  );
}

function TemplateEditor({ template, editable, onClose }: { template: PromptTemplate | null; editable: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const attrs = useAttributes();
  const groups = useGroups();
  const channels = useChannels();
  const families = useFamilies();
  const shotTypes = useShotTypes();
  const voices = useBrandVoices();
  const me = useMe();
  const [d, setD] = useState<PromptTemplateInput>(
    template
      ? {
          code: template.code,
          label: template.label,
          task_type: template.task_type,
          target_attribute: template.target_attribute ?? null,
          output_attributes: template.output_attributes,
          channel_code: template.channel_code ?? null,
          family_code: template.family_code ?? null,
          brand_code: template.brand_code,
          body: template.body,
          input_attributes: template.input_attributes,
          input_shot_types: template.input_shot_types,
          accepts_text_input: template.accepts_text_input,
          accepts_document: template.accepts_document,
          max_length: template.max_length ?? null,
          model_task: template.model_task,
        }
      : { ...EMPTY, brand_code: me.data?.brand_scopes[0] ?? "" },
  );
  const [note, setNote] = useState("");
  const set = <K extends keyof PromptTemplateInput>(k: K, v: PromptTemplateInput[K]) => setD((x) => ({ ...x, [k]: v }));

  const groupLabel = (code: string) => groups.data?.find((g) => g.code === code)?.label ?? code;
  const grouped = useMemo(() => {
    const m = new Map<string, AttributeDefinition[]>();
    for (const a of (attrs.data ?? []).filter((a) => a.status !== "deprecated" && a.level in { style: 1, style_color: 1, sku: 1 })) {
      m.set(a.group_code, [...(m.get(a.group_code) ?? []), a]);
    }
    const order = new Map((groups.data ?? []).map((g) => [g.code, g.sort_order]));
    return Array.from(m.entries()).sort((a, b) => (order.get(a[0]) ?? 999) - (order.get(b[0]) ?? 999));
  }, [attrs.data, groups.data]);
  const multi = MULTI_TARGET.includes(d.task_type);
  const targetFilter = (a: AttributeDefinition) => {
    if (a.source_of_truth === "erp") return false;
    if (d.task_type === "classify") return a.data_type === "single_select" || a.data_type === "multi_select";
    if (d.task_type === "check" || d.task_type === "adapt" || d.task_type === "expand") return a.data_type === "text" || a.data_type === "rich_text";
    return true;
  };
  const brandCodes = useMemo(() => {
    const s = new Set<string>([...(voices.data ?? []).map((v) => v.brand_code), ...(me.data?.brand_scopes ?? [])]);
    if (d.brand_code) s.add(d.brand_code);
    return Array.from(s);
  }, [voices.data, me.data, d.brand_code]);

  const placeholders = useMemo(() => {
    const out = d.input_attributes.map((c) => `{{attr.${c}}}`);
    out.push("{{core.style_number}}", "{{core.color_code}}", "{{core.family_code}}", "{{channel.max_length}}");
    if (d.accepts_text_input || d.task_type === "extract") out.push("{{input.text}}");
    return out;
  }, [d.input_attributes, d.accepts_text_input, d.task_type]);
  const unusedInputs = d.input_attributes.filter((c) => !d.body.includes(`{{attr.${c}}}`));

  const save = useMutation({
    mutationFn: () => {
      const body: PromptTemplateInput = {
        ...d,
        target_attribute: multi ? (d.output_attributes[0] ?? d.target_attribute ?? null) : d.target_attribute || null,
        output_attributes: multi ? d.output_attributes : d.target_attribute ? [d.target_attribute] : [],
        model_task: d.task_type === "classify" ? "classify" : d.model_task,
        max_length: d.max_length || null,
        channel_code: d.channel_code || null,
        family_code: d.family_code || null,
      };
      if (template) {
        const { code: _code, ...rest } = body;
        void _code;
        return aiApi.updateTemplate(template.code, { ...rest, note: note.trim() || null });
      }
      return aiApi.createTemplate(body);
    },
    onSuccess: (t) => {
      toast(template ? `Template saved (version ${t.version}).` : `Template ${t.code} created as a draft.`, "ok");
      qc.invalidateQueries({ queryKey: ["ai", "templates"] });
      qc.invalidateQueries({ queryKey: ["ai", "template", t.code] });
      onClose();
    },
  });

  const toggleIn = (list: string[], code: string) => (list.includes(code) ? list.filter((c) => c !== code) : [...list, code]);
  const valid =
    !!d.code.trim() && !!d.label.trim() && !!d.brand_code && !!d.body.trim() && (multi ? d.output_attributes.length > 0 : d.task_type === "check" ? true : !!d.target_attribute);
  const metaLoading = attrs.isLoading || groups.isLoading;

  return (
    <Dialog
      title={template ? `${editable ? "Edit" : "View"} template ${template.code}` : "New prompt template"}
      onClose={onClose}
      wide
      footer={
        <>
          <button onClick={onClose} disabled={save.isPending}>
            {editable ? "Cancel" : "Close"}
          </button>
          {editable && (
            <button className="primary" disabled={!valid || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? "Saving" : template ? "Save" : "Create draft"}
            </button>
          )}
        </>
      }
    >
      <fieldset disabled={!editable} style={{ border: 0, padding: 0, margin: 0 }}>
        <div className="stack gap16">
          {metaLoading && <Spinner label="Loading metadata" />}
          <div className="form-grid">
            <label className="field">
              Code
              <input value={d.code} disabled={!!template} placeholder="e.g. pdp_description_generate" onChange={(e) => set("code", e.target.value.replace(/[^a-zA-Z0-9_\-.]/g, "_"))} />
            </label>
            <label className="field">
              Label
              <input value={d.label} onChange={(e) => set("label", e.target.value)} />
            </label>
            <label className="field">
              Task type
              <select value={d.task_type} onChange={(e) => set("task_type", e.target.value as TaskType)}>
                {TASK_TYPES.map((t) => (
                  <option key={t.v} value={t.v}>
                    {t.label}
                  </option>
                ))}
              </select>
              <span className="help">{TASK_TYPES.find((t) => t.v === d.task_type)?.help}</span>
            </label>
            <label className="field">
              Brand
              <select value={d.brand_code} onChange={(e) => set("brand_code", e.target.value)}>
                <option value="">Choose a brand</option>
                {brandCodes.map((b) => (
                  <option key={b} value={b}>
                    {voices.data?.find((v) => v.brand_code === b)?.label ?? b}
                  </option>
                ))}
              </select>
              {voices.data && voices.data.length === 0 && <span className="help">No brand voice yet; add one on the Brand voice tab.</span>}
            </label>
            {!multi && (
              <label className="field">
                Target attribute {d.task_type === "check" ? "(optional for check)" : ""}
                <select value={d.target_attribute ?? ""} onChange={(e) => set("target_attribute", e.target.value || null)}>
                  <option value="">Choose an attribute</option>
                  {grouped.map(([g, list]) => {
                    const items = list.filter(targetFilter);
                    if (!items.length) return null;
                    return (
                      <optgroup key={g} label={groupLabel(g)}>
                        {items.map((a) => (
                          <option key={a.code} value={a.code}>
                            {a.label} ({a.data_type}, {a.level})
                          </option>
                        ))}
                      </optgroup>
                    );
                  })}
                </select>
              </label>
            )}
            <label className="field">
              Channel (optional)
              <select value={d.channel_code ?? ""} onChange={(e) => set("channel_code", e.target.value || null)}>
                <option value="">Any channel</option>
                {(channels.data ?? []).map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Family (optional)
              <select value={d.family_code ?? ""} onChange={(e) => set("family_code", e.target.value || null)}>
                <option value="">Any family</option>
                {(families.data ?? []).map((f) => (
                  <option key={f.code} value={f.code}>
                    {f.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Max length (characters)
              <input type="number" min={1} value={d.max_length ?? ""} onChange={(e) => set("max_length", e.target.value === "" ? null : Number(e.target.value))} />
              <span className="help">Empty: from the attribute definition and the channel requirement.</span>
            </label>
            <div className="field">
              Model task (endpoint)
              <div className="row">
                {(["copy", "classify"] as ModelTask[]).map((m) => (
                  <label key={m} className="inline">
                    <input type="radio" name="model_task" checked={(d.task_type === "classify" ? "classify" : d.model_task) === m} disabled={d.task_type === "classify"} onChange={() => set("model_task", m)} /> {m}
                  </label>
                ))}
              </div>
            </div>
          </div>

          {multi && (
            <div>
              <div className="muted small mb8">Output attributes (the task writes one suggestion per attribute)</div>
              <CheckGrid grouped={grouped} groupLabel={groupLabel} selected={d.output_attributes} filter={(a) => a.source_of_truth !== "erp"} onToggle={(c) => set("output_attributes", toggleIn(d.output_attributes, c))} />
            </div>
          )}

          <div>
            <div className="muted small mb8">Input attributes (read into the prompt as {"{{attr.<code>}}"})</div>
            <CheckGrid grouped={grouped} groupLabel={groupLabel} selected={d.input_attributes} onToggle={(c) => set("input_attributes", toggleIn(d.input_attributes, c))} />
          </div>

          <div className="form-grid">
            <div className="field">
              Input shot types (images sent to the model)
              {shotTypes.isError && <ErrorBox error={shotTypes.error} title="Could not load shot types" />}
              <div className="row" style={{ flexWrap: "wrap" }}>
                {(shotTypes.data ?? [])
                  .slice()
                  .sort((a, b) => a.sort_order - b.sort_order)
                  .map((s) => (
                    <label key={s.code} className="inline">
                      <input type="checkbox" checked={d.input_shot_types.includes(s.code)} onChange={() => set("input_shot_types", toggleIn(d.input_shot_types, s.code))} /> {s.label}
                    </label>
                  ))}
                {shotTypes.data && shotTypes.data.length === 0 && <span className="faint small">No shot types defined.</span>}
              </div>
            </div>
            <div className="field">
              Extra inputs
              <label className="inline">
                <input type="checkbox" checked={d.accepts_text_input} onChange={(e) => set("accepts_text_input", e.target.checked)} /> Accepts free text ({"{{input.text}}"})
              </label>
              <label className="inline">
                <input type="checkbox" checked={d.accepts_document} onChange={(e) => set("accepts_document", e.target.checked)} /> Accepts a document upload
              </label>
            </div>
          </div>

          <label className="field">
            Prompt body
            <textarea value={d.body} rows={12} onChange={(e) => set("body", e.target.value)} placeholder="Write the instructions. The brand voice is added by the backend." />
            <span className="help">
              Placeholders:{" "}
              {placeholders.map((p) => (
                <button key={p} type="button" className="chip-btn mono" title="Append to the body" onClick={() => set("body", d.body + (d.body.endsWith(" ") || d.body === "" ? "" : " ") + p)}>
                  {p}
                </button>
              ))}
            </span>
            {unusedInputs.length > 0 && <span className="help" style={{ color: "var(--amber)" }}>Input attributes not referenced in the body: {unusedInputs.join(", ")}</span>}
          </label>

          {template && editable && (
            <label className="field">
              Version note (optional, saved when the body changed)
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed and why" />
            </label>
          )}
          {save.isError && <ErrorBox error={save.error} title="Save failed" />}
        </div>
      </fieldset>
    </Dialog>
  );
}

function CheckGrid({
  grouped,
  groupLabel,
  selected,
  onToggle,
  filter,
}: {
  grouped: [string, AttributeDefinition[]][];
  groupLabel: (code: string) => string;
  selected: string[];
  onToggle: (code: string) => void;
  filter?: (a: AttributeDefinition) => boolean;
}) {
  return (
    <div className="check-grid">
      {grouped.map(([g, list]) => {
        const items = filter ? list.filter(filter) : list;
        if (!items.length) return null;
        return (
          <div key={g} className="check-group">
            <div className="check-group-head">{groupLabel(g)}</div>
            {items.map((a) => (
              <label key={a.code} className="inline" style={{ display: "flex" }}>
                <input type="checkbox" checked={selected.includes(a.code)} onChange={() => onToggle(a.code)} />
                <span>
                  {a.label} <span className="faint small">{a.level}</span>
                </span>
              </label>
            ))}
          </div>
        );
      })}
      {grouped.length === 0 && <span className="faint small">No attributes defined.</span>}
    </div>
  );
}

function PreviewDialog({ template, onClose }: { template: PromptTemplate; onClose: () => void }) {
  const attrs = useAttributes();
  const channels = useChannels();
  const [entityId, setEntityId] = useState("");
  const [styleQ, setStyleQ] = useState("");
  const [channel, setChannel] = useState(template.channel_code ?? "");
  const [text, setText] = useState("");
  const [result, setResult] = useState<TemplatePreview | null>(null);
  const attrByCode = useMemo(() => new Map((attrs.data ?? []).map((a) => [a.code, a])), [attrs.data]);
  // Search at the target attribute's level (style-color when unknown) by style number.
  const target = template.target_attribute ?? template.output_attributes[0];
  const level: Level = ((target && attrByCode.get(target)?.level) as Level | undefined) ?? "style_color";
  const search = useQuery({
    queryKey: ["products", "ai-preview-search", level, styleQ],
    queryFn: () =>
      api.products.query({ level, page: 1, page_size: 20, sort: [], filters: [{ field: "style_number", op: "contains", value: styleQ.trim() }], search: "", columns: [] }),
    enabled: styleQ.trim().length >= 2,
  });
  const preview = useMutation({
    mutationFn: () => aiApi.previewTemplate(template.code, { entity_id: entityId.trim(), channel_code: channel || undefined, text: text || undefined }),
    onSuccess: setResult,
  });

  return (
    <Dialog
      title={`Preview ${template.label} on a product`}
      onClose={onClose}
      wide
      footer={
        <>
          <button onClick={onClose}>Close</button>
          <button className="primary" disabled={!entityId.trim() || preview.isPending} onClick={() => preview.mutate()}>
            {preview.isPending ? "Rendering" : "Render prompt"}
          </button>
        </>
      }
    >
      <div className="stack gap16">
        <div className="form-grid">
          <label className="field">
            Entity id
            <input value={entityId} onChange={(e) => setEntityId(e.target.value)} placeholder="Paste an entity id or pick from the search" />
          </label>
          <label className="field">
            Or search by style number ({level.replace("_", "-")} level)
            <input value={styleQ} onChange={(e) => setStyleQ(e.target.value)} placeholder="e.g. 81" />
          </label>
          {(template.task_type === "adapt" || !template.channel_code) && (
            <label className="field">
              Channel (optional)
              <select value={channel} onChange={(e) => setChannel(e.target.value)} disabled={!!template.channel_code}>
                <option value="">None</option>
                {(channels.data ?? []).map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          {(template.accepts_text_input || template.task_type === "extract") && (
            <label className="field">
              Text input (optional)
              <textarea value={text} rows={3} onChange={(e) => setText(e.target.value)} />
            </label>
          )}
        </div>
        {styleQ.trim().length >= 2 && (
          <div className="search-results">
            {search.isLoading && <Spinner label="Searching" />}
            {search.isError && <ErrorBox error={search.error} title="Search failed" />}
            {search.data && search.data.rows.length === 0 && <div className="faint small">No products match.</div>}
            {(search.data?.rows ?? []).map((r) => (
              <div key={r.entity_id} className={`item${r.entity_id === entityId ? " selected" : ""}`} onClick={() => setEntityId(r.entity_id)}>
                <b>{r.label}</b> <span className="faint small mono">{r.entity_id}</span>
                {r.family_code && <Badge>{r.family_code}</Badge>}
              </div>
            ))}
          </div>
        )}
        {preview.isError && <ErrorBox error={preview.error} title="Preview failed" />}
        {result && (
          <div className="ai-preview">
            {result.missing_inputs.length > 0 && (
              <div className="banner warn boxed">
                Missing inputs: {result.missing_inputs.map((m) => attrByCode.get(m)?.label ?? m).join(", ")}.{" "}
                <Link to={`/products/${encodeURIComponent(entityId)}`}>Open the product</Link>
              </div>
            )}
            <div className="muted small">Rendered prompt</div>
            <pre className="ai-prompt">{result.prompt}</pre>
            <details>
              <summary className="muted small">Inputs ({Object.keys(result.inputs).length})</summary>
              <dl className="kv">
                {Object.entries(result.inputs).map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt className="mono">{k}</dt>
                    <dd className="pre">{typeof v === "string" ? v : JSON.stringify(v)}</dd>
                  </div>
                ))}
              </dl>
            </details>
          </div>
        )}
      </div>
    </Dialog>
  );
}

