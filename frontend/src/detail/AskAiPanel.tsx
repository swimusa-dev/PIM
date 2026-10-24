// AI-03, AI-05, AI-06: Ask AI tab on the product detail page. Applicable templates grouped by task type, channel
// picker for adapt, free text, document upload (base64) and confirmed image picks for extract, prompt preview with
// missing inputs, run through POST /api/ai/ask with each output as a review card, and the product's previous
// outputs with status pills. The 409 "AI endpoint not configured" case is a banner. Hidden without run_ai.

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { aiApi, api } from "../api/client";
import { flattenTemplates, useChannels } from "../api/hooks";
import type { AiOutput, AttributeDefinition, ImageLink, OptionList, PromptTemplate, TaskType, TemplatePreview } from "../api/types";
import { Badge, Empty, ErrorBox, Spinner } from "../components/Common";
import { OutputCard } from "../ai/OutputCard";
import { AiError, OutputStatusPill, TASK_ORDER, TASK_TYPES, TaskBadge, taskLabel } from "../ai/shared";
import { formatDate } from "../lib/format";

async function fileToBase64(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

export function AskAiPanel({
  entityId,
  attributes,
  optionLists,
  onGoToAttribute,
}: {
  entityId: string;
  attributes: AttributeDefinition[];
  optionLists: Record<string, OptionList>;
  onGoToAttribute: (code: string) => void;
}) {
  const channels = useChannels();
  const templates = useQuery({ queryKey: ["ai", "product-templates", entityId], queryFn: () => aiApi.productTemplates(entityId) });
  const images = useQuery({ queryKey: ["product", entityId, "images"], queryFn: () => api.products.images(entityId) });
  const previous = useQuery({ queryKey: ["ai", "outputs", { entity_id: entityId }], queryFn: () => aiApi.outputs({ entity_id: entityId }) });

  const attrByCode = useMemo(() => new Map(attributes.map((a) => [a.code, a])), [attributes]);
  const list = useMemo(() => flattenTemplates(templates.data), [templates.data]);
  const grouped = useMemo(() => {
    const m = new Map<TaskType, PromptTemplate[]>();
    for (const t of list) m.set(t.task_type, [...(m.get(t.task_type) ?? []), t]);
    return TASK_ORDER.filter((t) => m.has(t)).map((t) => [t, m.get(t)!] as const);
  }, [list]);
  const confirmedImages = useMemo(() => {
    const source = images.data?.links ?? (images.data?.slots ?? []).map((s) => s.link);
    return source.filter((l): l is ImageLink => !!l && l.status === "confirmed").sort((a, b) => a.sort_order - b.sort_order);
  }, [images.data]);

  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [channel, setChannel] = useState("");
  const [text, setText] = useState("");
  const [doc, setDoc] = useState<{ name: string; content_base64: string } | null>(null);
  const [assetIds, setAssetIds] = useState<string[]>([]);
  const [preview, setPreview] = useState<TemplatePreview | null>(null);
  const [results, setResults] = useState<AiOutput[]>([]);

  const selected = list.find((t) => t.code === selectedCode) ?? null;
  const effectiveChannel = selected?.channel_code || channel || "";
  const isExtract = selected?.task_type === "extract";
  const wantsText = !!selected && (isExtract || selected.accepts_text_input);
  const wantsDoc = !!selected && (isExtract || selected.accepts_document);
  const wantsImages = !!selected && (isExtract || selected.input_shot_types.length > 0);

  const choose = (t: PromptTemplate) => {
    setSelectedCode(t.code);
    setChannel(t.channel_code ?? "");
    setPreview(null);
  };

  const previewM = useMutation({
    mutationFn: () => aiApi.previewTemplate(selected!.code, { entity_id: entityId, channel_code: effectiveChannel || undefined, text: text || undefined }),
    onSuccess: (p) => setPreview(p),
  });
  const ask = useMutation({
    mutationFn: () =>
      aiApi.ask({
        entity_id: entityId,
        template_code: selected!.code,
        channel_code: effectiveChannel || undefined,
        text: wantsText && text ? text : undefined,
        document: wantsDoc && doc ? doc : undefined,
        image_asset_ids: wantsImages && assetIds.length ? assetIds : undefined,
      }),
    onSuccess: (r) => {
      setResults((prev) => [...r.outputs, ...prev]);
      setPreview(null);
      void previous.refetch();
    },
  });

  const onUpdated = (next: AiOutput, replacedId?: string) =>
    setResults((prev) => {
      const id = replacedId ?? next.id;
      const ix = prev.findIndex((o) => o.id === id);
      if (ix < 0) return [next, ...prev];
      const copy = prev.slice();
      copy[ix] = next;
      return copy;
    });

  const targets = (t: PromptTemplate) => {
    const codes = t.output_attributes.length ? t.output_attributes : t.target_attribute ? [t.target_attribute] : [];
    return codes.map((c) => attrByCode.get(c)?.label ?? c);
  };

  return (
    <div className="ask-ai">
      <div className="panel">
        <div className="panel-header">
          <h3>Templates</h3>
          <span className="muted small">Applicable to this product's level, family and brand</span>
        </div>
        <div className="panel-body flush ask-ai-templates">
          {templates.isLoading && <Spinner label="Loading templates" />}
          {templates.isError && <ErrorBox error={templates.error} title="Could not load templates" />}
          {templates.data && list.length === 0 && (
            <Empty title="No templates apply">An administrator can create prompt templates under Admin, AI.</Empty>
          )}
          {grouped.map(([task, items]) => (
            <div key={task} className="ask-ai-group">
              <div className="ask-ai-group-head" title={TASK_TYPES.find((x) => x.v === task)?.help}>
                {taskLabel(task)}
              </div>
              {items.map((t) => (
                <button key={t.code} className={`ask-ai-template${t.code === selectedCode ? " selected" : ""}`} onClick={() => choose(t)}>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <b>{t.label}</b>
                    {t.channel_code && <Badge>{t.channel_code}</Badge>}
                  </div>
                  <div className="small">
                    {targets(t).length ? targets(t).join(", ") : <span className="faint">no target attribute</span>}
                  </div>
                  <div className="faint small ask-ai-desc">{t.body.split("\n")[0].slice(0, 120)}</div>
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="stack gap16">
        {!selected ? (
          <Empty title="Pick a template">Choose a task on the left, then preview the prompt or run it.</Empty>
        ) : (
          <div className="panel">
            <div className="panel-header">
              <h3 className="row">
                {selected.label} <TaskBadge task={selected.task_type} />
              </h3>
              <span className="faint small mono">
                {selected.code} v{selected.version}, {selected.model_task} endpoint
              </span>
            </div>
            <div className="panel-body stack">
              <div className="small">
                <span className="muted">Writes:</span> {targets(selected).join(", ") || "n/a"}
                {selected.input_attributes.length > 0 && (
                  <>
                    {" "}
                    <span className="muted">Reads:</span> {selected.input_attributes.map((c) => attrByCode.get(c)?.label ?? c).join(", ")}
                  </>
                )}
                {selected.input_shot_types.length > 0 && (
                  <>
                    {" "}
                    <span className="muted">Shots:</span> {selected.input_shot_types.join(", ")}
                  </>
                )}
              </div>

              {selected.task_type === "adapt" && (
                <label className="field">
                  Channel
                  {selected.channel_code ? (
                    <span>
                      <Badge>{selected.channel_code}</Badge> <span className="faint small">fixed by the template</span>
                    </span>
                  ) : (
                    <select value={channel} onChange={(e) => { setChannel(e.target.value); setPreview(null); }}>
                      <option value="">Choose a channel</option>
                      {(channels.data ?? []).map((c) => (
                        <option key={c.code} value={c.code}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                  )}
                </label>
              )}

              {wantsText && (
                <label className="field">
                  Text to work from {isExtract ? "" : "(optional)"}
                  <textarea value={text} rows={5} onChange={(e) => { setText(e.target.value); setPreview(null); }} placeholder="Paste a tech pack note, a supplier email or copy from another channel" />
                </label>
              )}
              {wantsDoc && (
                <label className="field">
                  Document (optional)
                  <input
                    type="file"
                    onChange={async (e) => {
                      const f = e.target.files?.[0];
                      if (!f) {
                        setDoc(null);
                        return;
                      }
                      setDoc({ name: f.name, content_base64: await fileToBase64(f) });
                    }}
                  />
                  {doc && <span className="help">{doc.name} will be sent with the request.</span>}
                </label>
              )}
              {wantsImages && (
                <div>
                  <div className="muted small mb8">Confirmed images to read (optional)</div>
                  {images.isLoading && <Spinner />}
                  {images.isError && <ErrorBox error={images.error} title="Could not load images" />}
                  {images.data && confirmedImages.length === 0 && <span className="faint small">No confirmed images on this product.</span>}
                  <div className="row" style={{ flexWrap: "wrap" }}>
                    {confirmedImages.map((l) => {
                      const on = assetIds.includes(l.asset_id);
                      return (
                        <label key={l.id} className={`ask-ai-image${on ? " on" : ""}`} title={l.filename}>
                          <input type="checkbox" checked={on} onChange={() => setAssetIds((s) => (on ? s.filter((x) => x !== l.asset_id) : [...s, l.asset_id]))} />
                          {l.thumbnail_url ? <img src={l.thumbnail_url} alt={l.filename} /> : <span className="thumb placeholder">{l.shot_type ?? "img"}</span>}
                          <span className="faint small">{l.shot_type ?? "no shot"}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="row">
                <button className="small" disabled={previewM.isPending} onClick={() => previewM.mutate()}>
                  {previewM.isPending ? "Rendering" : "Preview prompt"}
                </button>
                <button
                  className="primary"
                  disabled={ask.isPending || (selected.task_type === "adapt" && !effectiveChannel)}
                  onClick={() => ask.mutate()}
                  title={selected.task_type === "adapt" && !effectiveChannel ? "Choose a channel first" : ""}
                >
                  {ask.isPending ? "Asking the model" : "Run"}
                </button>
                {ask.isPending && <Spinner label="This can take a few seconds" />}
              </div>
              {previewM.isError && <ErrorBox error={previewM.error} title="Preview failed" />}
              {preview && (
                <div className="ai-preview">
                  {preview.missing_inputs.length > 0 && (
                    <div className="banner warn boxed">
                      Missing inputs:{" "}
                      {preview.missing_inputs.map((m) => (
                        <button key={m} className="chip-btn" onClick={() => onGoToAttribute(m)}>
                          {attrByCode.get(m)?.label ?? m}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="muted small">Rendered prompt</div>
                  <pre className="ai-prompt">{preview.prompt}</pre>
                  {Object.keys(preview.inputs).length > 0 && (
                    <details>
                      <summary className="muted small">Inputs ({Object.keys(preview.inputs).length})</summary>
                      <dl className="kv">
                        {Object.entries(preview.inputs).map(([k, v]) => (
                          <div key={k} style={{ display: "contents" }}>
                            <dt className="mono">{k}</dt>
                            <dd className="pre">{typeof v === "string" ? v : JSON.stringify(v)}</dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                  )}
                </div>
              )}
              <AiError error={ask.error} title="The request failed" />
            </div>
          </div>
        )}

        {results.length > 0 && (
          <div className="stack">
            <h3 style={{ margin: 0 }}>Suggestions</h3>
            {results.map((o) => (
              <OutputCard key={o.id} output={o} attrByCode={attrByCode} optionLists={optionLists} onUpdated={onUpdated} onGoToAttribute={onGoToAttribute} />
            ))}
          </div>
        )}

        <div className="panel">
          <div className="panel-header">
            <h3>Previous outputs</h3>
            <span className="muted small">{previous.data ? `${previous.data.total} total` : ""}</span>
          </div>
          <div className="panel-body flush">
            {previous.isLoading && <Spinner />}
            {previous.isError && <ErrorBox error={previous.error} title="Could not load previous outputs" />}
            {previous.data && previous.data.rows.length === 0 && <div className="empty">No AI outputs for this product yet.</div>}
            {previous.data && previous.data.rows.length > 0 && (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Attribute</th>
                    <th>Task</th>
                    <th>Template</th>
                    <th>Status</th>
                    <th>Proposed</th>
                    <th>By</th>
                  </tr>
                </thead>
                <tbody>
                  {previous.data.rows.map((o) => (
                    <tr key={o.id} className="clickable" onClick={() => setResults((r) => (r.some((x) => x.id === o.id) ? r : [o, ...r]))} title="Open as a card above">
                      <td className="nowrap">{formatDate(o.created_at)}</td>
                      <td>{attrByCode.get(o.attribute_code)?.label ?? o.attribute_code}</td>
                      <td>{taskLabel(o.task_type)}</td>
                      <td className="mono small">
                        {o.template_code} v{o.template_version}
                      </td>
                      <td>
                        <OutputStatusPill status={o.status} />
                      </td>
                      <td className="small" style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {typeof o.proposed_value === "string" ? o.proposed_value : JSON.stringify(o.proposed_value ?? null)}
                      </td>
                      <td className="small">{o.created_by}</td>
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
