// IMP-02 column mapping with transforms and suggestions (accepted one by one, never auto-applied),
// IMP-03 value mappings for select attributes, IMP-05 match keys and keyless name column,
// IMP-06 unmatched and on-error policies, multi-file precedence, mapping templates.

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAttributes, useGroups, useImportSources, useOptionLists } from "../api/hooks";
import type {
  ColumnMapping,
  ImportBatch,
  MappingSuggestion,
  MappingUpdate,
  OnErrorPolicy,
  Transform,
  TransformOp,
  UnmatchedPolicy,
  ValueMappingList,
} from "../api/types";
import { Badge, Dialog, ErrorBox, Spinner, useToast } from "../components/Common";
import {
  buildTargetOptions,
  confidenceClass,
  coreKeysForLevel,
  defaultArgs,
  groupTargetOptions,
  mappingForColumn,
  MAX_SOURCES,
  missingRequired,
  setColumnTarget,
  targetLabel,
  TRANSFORM_OPS,
} from "./shared";

export function MapStep({
  batch,
  onBatch,
  onNext,
  onBack,
}: {
  batch: ImportBatch;
  onBatch: (b: ImportBatch) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const attrs = useAttributes();
  const groups = useGroups();
  const sources = useImportSources();
  const toast = useToast();
  const qc = useQueryClient();

  const [mapping, setMapping] = useState<ColumnMapping[]>(batch.mapping ?? []);
  const [matchKeys, setMatchKeys] = useState<string[]>(batch.match_keys ?? []);
  const [unmatched, setUnmatched] = useState<string>(batch.options?.unmatched_policy ?? "");
  const [onError, setOnError] = useState<OnErrorPolicy>(batch.options?.on_error ?? "skip_row");
  const [keylessCol, setKeylessCol] = useState<string>(batch.options?.keyless_name_column ?? "");
  const [precedence, setPrecedence] = useState<number[]>(() =>
    batch.files.slice().sort((a, b) => a.precedence - b.precedence).map((f) => f.index),
  );
  const [suggestions, setSuggestions] = useState<MappingSuggestion[] | null>(null);
  const [showTemplate, setShowTemplate] = useState(false);
  const [serverMissing, setServerMissing] = useState<string | null>(null);

  // Defaults from the source once sources load.
  const source = sources.data?.find((s) => s.code === batch.source_code);
  useEffect(() => {
    if (!unmatched && source) setUnmatched(source.default_policy.unmatched);
  }, [source, unmatched]);

  const targetOptions = useMemo(() => buildTargetOptions(batch.level, attrs.data ?? [], groups.data ?? []), [batch.level, attrs.data, groups.data]);
  const groupedTargets = useMemo(() => groupTargetOptions(targetOptions), [targetOptions]);
  const attrByCode = useMemo(() => new Map((attrs.data ?? []).map((a) => [a.code, a])), [attrs.data]);

  const allColumns = useMemo(
    () => batch.files.flatMap((f) => f.columns.map((c) => ({ ...c, file: f.name, fileIndex: f.index }))),
    [batch.files],
  );
  const usedColumns = useMemo(() => new Set(mapping.flatMap((m) => m.sources)), [mapping]);
  const keyless = !!keylessCol;
  const missing = useMemo(() => missingRequired(batch, mapping, matchKeys, keyless, unmatched), [batch, mapping, matchKeys, keyless, unmatched]);
  const targetMappings = mapping.filter((m) => !m.skip && m.target !== "skip");

  const buildUpdate = (): MappingUpdate & { files: { index: number; header_row: number; group_header_row?: number | null; data_start_row: number }[] } => ({
    mapping,
    match_keys: matchKeys,
    options: { on_error: onError, unmatched_policy: unmatched, keyless_name_column: keylessCol || null },
    template_id: batch.template_id ?? undefined,
    precedence,
    // Header row edits from the Upload step travel with the mapping (not in the contract; ignored by servers that do not read it).
    files: batch.files.map((f) => ({ index: f.index, header_row: f.header_row, group_header_row: f.group_header_row ?? null, data_start_row: f.data_start_row })),
  });

  const save = useMutation({
    mutationFn: () => api.imports.saveMapping(batch.id, buildUpdate()),
    onSuccess: (b) => {
      setServerMissing(null);
      onBatch(b);
      qc.invalidateQueries({ queryKey: ["imports", "value-mappings", batch.id] });
      toast("Mapping saved.", "ok");
    },
    onError: (e) => setServerMissing((e as Error).message),
  });

  const suggest = useMutation({
    mutationFn: () => api.imports.suggestMapping(batch.id),
    onSuccess: (s) => {
      setSuggestions(s);
      if (s.length === 0) toast("No suggestions for the remaining columns.", "info");
    },
  });

  const acceptSuggestion = (s: MappingSuggestion) => {
    setMapping((m) => setColumnTarget(m, s.column, s.target));
    setSuggestions((list) => (list ?? []).filter((x) => x.column !== s.column));
  };

  const updateMapping = (ix: number, patch: Partial<ColumnMapping>) =>
    setMapping((m) => m.map((x, i) => (i === ix ? { ...x, ...patch } : x)));

  const addSource = (ix: number, column: string) => {
    if (!column) return;
    setMapping((m) => {
      let next = m.map((x) => ({ ...x, sources: x.sources.filter((s) => s !== column) })).filter((x) => x.sources.length > 0 || x.required);
      const t = m[ix].target;
      const j = next.findIndex((x) => x.target === t && !x.skip);
      if (j < 0) next = [...next, { ...m[ix], sources: [column] }];
      else if (next[j].sources.length < MAX_SOURCES) next[j] = { ...next[j], sources: [...next[j].sources, column] };
      return next;
    });
  };

  const move = <T,>(arr: T[], i: number, d: -1 | 1): T[] => {
    const j = i + d;
    if (j < 0 || j >= arr.length) return arr;
    const c = arr.slice();
    [c[i], c[j]] = [c[j], c[i]];
    return c;
  };

  const availableKeys = useMemo(() => {
    const core = coreKeysForLevel(batch.level).map((k) => ({ key: k.key, label: k.label }));
    const mappedAttrs = targetMappings
      .filter((m) => attrByCode.has(m.target))
      .map((m) => ({ key: m.target, label: attrByCode.get(m.target)!.label }));
    return [...core, ...mappedAttrs].filter((k) => !matchKeys.includes(k.key));
  }, [batch.level, targetMappings, attrByCode, matchKeys]);

  const canProceed = missing.length === 0 && targetMappings.length > 0;
  const metaLoading = attrs.isLoading || groups.isLoading;

  return (
    <div className="stack gap16">
      {batch.worksheet_id && <div className="banner ok">Keyed worksheet: columns are mapped from the worksheet itself. Review and continue.</div>}
      {batch.template_id && <div className="banner info">Template {batch.template_id} applied. Changes here affect this batch only unless you save a new template.</div>}
      {metaLoading && <Spinner label="Loading attribute metadata" />}
      {(attrs.isError || groups.isError) && <ErrorBox error={attrs.error ?? groups.error} title="Could not load metadata" />}

      <div className="map-layout">
        <div className="stack gap16">
          <div className="panel">
            <div className="panel-header">
              <h3>File columns</h3>
              <div className="row">
                <button className="small" disabled={suggest.isPending} onClick={() => suggest.mutate()}>
                  {suggest.isPending ? "Suggesting" : "Suggest mappings"}
                </button>
              </div>
            </div>
            {suggest.isError && <ErrorBox error={suggest.error} title="Could not get suggestions" />}
            {suggestions && suggestions.length > 0 && (
              <div className="panel-body" style={{ borderBottom: "1px solid var(--border)", background: "var(--teal-faint)" }}>
                <div className="muted small mb8">Suggestions are never applied automatically. Accept the ones that are right.</div>
                <table className="data compact">
                  <tbody>
                    {suggestions.map((s) => (
                      <tr key={s.column}>
                        <td className="mono">{s.column}</td>
                        <td>
                          to <b>{targetLabel(s.target, targetOptions)}</b>
                        </td>
                        <td>
                          <span className={`confidence ${confidenceClass(s.confidence)}`}>{Math.round(s.confidence * 100)}%</span>
                        </td>
                        <td className="muted small">{s.reason}</td>
                        <td className="right">
                          <button className="small primary" onClick={() => acceptSuggestion(s)}>
                            Accept
                          </button>
                          <button className="small link" style={{ marginLeft: 6 }} onClick={() => setSuggestions((l) => (l ?? []).filter((x) => x.column !== s.column))}>
                            Dismiss
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <table className="data compact">
              <thead>
                <tr>
                  {batch.files.length > 1 && <th>File</th>}
                  <th>Column</th>
                  <th>Group</th>
                  <th>Samples</th>
                  <th>Target</th>
                </tr>
              </thead>
              <tbody>
                {allColumns.map((c) => {
                  const m = mappingForColumn(mapping, c.name);
                  const value = m ? (m.skip ? "skip" : m.target) : "";
                  return (
                    <tr key={`${c.fileIndex}:${c.name}`}>
                      {batch.files.length > 1 && <td className="faint small mono">{c.file}</td>}
                      <td className="mono">{c.name}</td>
                      <td className="muted small">{c.group ?? ""}</td>
                      <td>
                        <div className="samples" title={c.samples.join(" | ")}>
                          {c.samples.slice(0, 3).join(" | ")}
                        </div>
                      </td>
                      <td>
                        <select value={value} onChange={(e) => setMapping((mm) => setColumnTarget(mm, c.name, e.target.value))}>
                          <option value="">(not mapped)</option>
                          {groupedTargets.map((g) => (
                            <optgroup key={g.group} label={g.group}>
                              {g.options.map((o) => (
                                <option key={o.value} value={o.value}>
                                  {o.label}
                                </option>
                              ))}
                            </optgroup>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
                {allColumns.length === 0 && (
                  <tr>
                    <td colSpan={5} className="empty">
                      No columns detected. Check the header row on the Upload step.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Targets and transforms</h3>
              <span className="faint small">Up to {MAX_SOURCES} source columns per target; transforms run in order.</span>
            </div>
            {targetMappings.length === 0 && <div className="empty">Pick a target for at least one column above.</div>}
            {targetMappings.length > 0 && (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Target</th>
                    <th>Sources</th>
                    <th>Transforms</th>
                    <th>Required</th>
                  </tr>
                </thead>
                <tbody>
                  {mapping.map((m, ix) => {
                    if (m.skip || m.target === "skip") return null;
                    const opt = targetOptions.find((o) => o.value === m.target);
                    const free = allColumns.filter((c) => !usedColumns.has(c.name));
                    return (
                      <tr key={`${m.target}-${ix}`}>
                        <td>
                          <b>{targetLabel(m.target, targetOptions)}</b>
                          <div className="faint small mono">
                            {m.target}
                            {opt?.attr ? ` (${opt.attr.data_type})` : opt ? " (core key)" : " (unknown target)"}
                          </div>
                        </td>
                        <td>
                          <div className="chips">
                            {m.sources.map((s) => (
                              <span key={s} className="chip">
                                {s}
                                <button onClick={() => setMapping((mm) => setColumnTarget(mm, s, ""))} aria-label={`Remove ${s}`} title="Remove source">
                                  &times;
                                </button>
                              </span>
                            ))}
                            {m.sources.length < MAX_SOURCES && free.length > 0 && (
                              <select value="" onChange={(e) => addSource(ix, e.target.value)} style={{ padding: "1px 4px", fontSize: 11 }}>
                                <option value="">Add source</option>
                                {free.map((c) => (
                                  <option key={`${c.fileIndex}:${c.name}`} value={c.name}>
                                    {c.name}
                                  </option>
                                ))}
                              </select>
                            )}
                          </div>
                        </td>
                        <td>
                          <TransformsEditor transforms={m.transforms ?? []} onChange={(t) => updateMapping(ix, { transforms: t })} />
                        </td>
                        <td>
                          <input type="checkbox" checked={!!m.required} onChange={(e) => updateMapping(ix, { required: e.target.checked })} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {batch.status !== "uploaded" && <ValueMappingsPanel batch={batch} attrByCode={attrByCode} />}
        </div>

        <div className="stack gap16">
          <div className="panel">
            <div className="panel-header">
              <h3>Required targets</h3>
            </div>
            <div className="panel-body">
              {missing.length === 0 ? (
                <div className="row">
                  <Badge color="green">All required targets mapped</Badge>
                </div>
              ) : (
                <>
                  <div className="muted small mb8">Map these before validating:</div>
                  <div className="checklist">
                    {missing.map((t) => (
                      <Badge key={t} color="red">
                        {targetLabel(t, targetOptions)}
                      </Badge>
                    ))}
                  </div>
                </>
              )}
              {serverMissing && <div className="field-error mt8">{serverMissing}</div>}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Match keys</h3>
              <span className="faint small">Tried in order (IMP-05)</span>
            </div>
            <div className="panel-body stack">
              <div className="ordered-list">
                {matchKeys.map((k, i) => (
                  <div className="item" key={k}>
                    <span className="idx">{i + 1}</span>
                    <span className="grow mono">{k}</span>
                    {!mappingForTarget(mapping, k) && !keyless && <Badge color="red">unmapped</Badge>}
                    <button className="icon small" disabled={i === 0} onClick={() => setMatchKeys((a) => move(a, i, -1))} aria-label="Move up">
                      &uarr;
                    </button>
                    <button className="icon small" disabled={i === matchKeys.length - 1} onClick={() => setMatchKeys((a) => move(a, i, 1))} aria-label="Move down">
                      &darr;
                    </button>
                    <button className="icon small" onClick={() => setMatchKeys((a) => a.filter((x) => x !== k))} aria-label="Remove">
                      &times;
                    </button>
                  </div>
                ))}
                {matchKeys.length === 0 && <div className="faint small">No match keys. Rows will be treated as new unless a keyless name column is set.</div>}
              </div>
              <select value="" onChange={(e) => e.target.value && setMatchKeys((a) => [...a, e.target.value])}>
                <option value="">Add match key</option>
                {availableKeys.map((k) => (
                  <option key={k.key} value={k.key}>
                    {k.label}
                  </option>
                ))}
              </select>
              <label className="field">
                Keyless name column (assisted matching)
                <select value={keylessCol} onChange={(e) => setKeylessCol(e.target.value)}>
                  <option value="">none</option>
                  {allColumns.map((c) => (
                    <option key={`${c.fileIndex}:${c.name}`} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Policies</h3>
            </div>
            <div className="panel-body stack">
              <label className="field">
                Unmatched rows
                <select value={unmatched} onChange={(e) => setUnmatched(e.target.value as UnmatchedPolicy)}>
                  <option value="create">create new products</option>
                  <option value="update_only">update only (skip unmatched)</option>
                  <option value="create_under_match">create under the matched parent</option>
                </select>
              </label>
              <label className="field">
                On error
                <select value={onError} onChange={(e) => setOnError(e.target.value as OnErrorPolicy)}>
                  <option value="skip_row">skip the whole row</option>
                  <option value="skip_value">skip only the bad value</option>
                </select>
              </label>
            </div>
          </div>

          {batch.files.length > 1 && (
            <div className="panel">
              <div className="panel-header">
                <h3>File precedence</h3>
                <span className="faint small">First wins on conflicts</span>
              </div>
              <div className="panel-body">
                <div className="ordered-list">
                  {precedence.map((ix, i) => {
                    const f = batch.files.find((x) => x.index === ix);
                    return (
                      <div className="item" key={ix}>
                        <span className="idx">{i + 1}</span>
                        <span className="grow mono">{f?.name ?? ix}</span>
                        <button className="icon small" disabled={i === 0} onClick={() => setPrecedence((a) => move(a, i, -1))} aria-label="Move up">
                          &uarr;
                        </button>
                        <button className="icon small" disabled={i === precedence.length - 1} onClick={() => setPrecedence((a) => move(a, i, 1))} aria-label="Move down">
                          &darr;
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          <button onClick={() => setShowTemplate(true)} disabled={targetMappings.length === 0}>
            Save as template
          </button>
        </div>
      </div>

      {save.isError && !serverMissing && <ErrorBox error={save.error} title="Could not save the mapping" />}

      <div className="wizard-footer">
        <button onClick={onBack}>Back</button>
        <div className="row">
          <button disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving" : "Save mapping"}
          </button>
          <button
            className="primary"
            disabled={!canProceed || save.isPending}
            title={canProceed ? "" : "Map every required target first"}
            onClick={() => save.mutateAsync().then(onNext).catch(() => undefined)}
          >
            Next: Validate
          </button>
        </div>
      </div>

      {showTemplate && (
        <SaveTemplateDialog
          batch={batch}
          mapping={mapping}
          matchKeys={matchKeys}
          unmatched={(unmatched || "update_only") as UnmatchedPolicy}
          onClose={() => setShowTemplate(false)}
        />
      )}
    </div>
  );
}

function mappingForTarget(mapping: ColumnMapping[], target: string) {
  return mapping.find((m) => m.target === target && !m.skip && m.sources.length > 0);
}

// ---------------------------------------------------------------------------------------------
// Transforms editor
// ---------------------------------------------------------------------------------------------

function TransformsEditor({ transforms, onChange }: { transforms: Transform[]; onChange: (t: Transform[]) => void }) {
  const update = (i: number, patch: Partial<Transform>) => onChange(transforms.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  const setArg = (i: number, key: string, value: unknown) => update(i, { args: { ...transforms[i].args, [key]: value } });
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= transforms.length) return;
    const c = transforms.slice();
    [c[i], c[j]] = [c[j], c[i]];
    onChange(c);
  };
  return (
    <div className="transforms">
      {transforms.map((t, i) => (
        <div className="transform-row" key={i}>
          <span className="faint small">{i + 1}.</span>
          <select value={t.op} onChange={(e) => update(i, { op: e.target.value as TransformOp, args: defaultArgs(e.target.value as TransformOp) })}>
            {TRANSFORM_OPS.map((o) => (
              <option key={o.op} value={o.op}>
                {o.label}
              </option>
            ))}
          </select>
          <TransformArgs t={t} setArg={(k, v) => setArg(i, k, v)} />
          <button className="icon small" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up">
            &uarr;
          </button>
          <button className="icon small" disabled={i === transforms.length - 1} onClick={() => move(i, 1)} aria-label="Move down">
            &darr;
          </button>
          <button className="icon small" onClick={() => onChange(transforms.filter((_, j) => j !== i))} aria-label="Remove transform">
            &times;
          </button>
        </div>
      ))}
      <select value="" style={{ padding: "1px 4px", fontSize: 11, maxWidth: 160 }} onChange={(e) => e.target.value && onChange([...transforms, { op: e.target.value as TransformOp, args: defaultArgs(e.target.value as TransformOp) }])}>
        <option value="">Add transform</option>
        {TRANSFORM_OPS.map((o) => (
          <option key={o.op} value={o.op}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function TransformArgs({ t, setArg }: { t: Transform; setArg: (k: string, v: unknown) => void }) {
  const a = t.args ?? {};
  const str = (k: string) => (a[k] === undefined || a[k] === null ? "" : String(a[k]));
  switch (t.op) {
    case "split":
      return (
        <>
          <input style={{ width: 50 }} value={str("delimiter")} placeholder="delim" onChange={(e) => setArg("delimiter", e.target.value)} title="Delimiter" />
          <input type="number" style={{ width: 55 }} value={str("index")} placeholder="part" onChange={(e) => setArg("index", Number(e.target.value))} title="Part index (0 based)" />
        </>
      );
    case "concat":
      return <input style={{ width: 60 }} value={str("separator")} placeholder="sep" onChange={(e) => setArg("separator", e.target.value)} title="Separator" />;
    case "regex_extract":
      return (
        <>
          <input style={{ width: 140 }} value={str("pattern")} placeholder="pattern" onChange={(e) => setArg("pattern", e.target.value)} title="Regular expression" />
          <input type="number" style={{ width: 55 }} value={str("group")} placeholder="grp" onChange={(e) => setArg("group", Number(e.target.value))} title="Capture group" />
        </>
      );
    case "value_replace": {
      const map = (a.map ?? {}) as Record<string, string>;
      const text = Object.entries(map)
        .map(([k, v]) => `${k}=${v}`)
        .join("\n");
      return (
        <textarea
          style={{ minHeight: 40, width: 180, fontSize: 11 }}
          defaultValue={text}
          placeholder={"from=to\none per line"}
          title="One from=to pair per line"
          onBlur={(e) => {
            const m: Record<string, string> = {};
            for (const line of e.target.value.split("\n")) {
              const ix = line.indexOf("=");
              if (ix > 0) m[line.slice(0, ix).trim()] = line.slice(ix + 1).trim();
            }
            setArg("map", m);
          }}
        />
      );
    }
    case "unit_convert":
      return (
        <>
          <input style={{ width: 50 }} value={str("from")} placeholder="from" onChange={(e) => setArg("from", e.target.value)} />
          <input style={{ width: 50 }} value={str("to")} placeholder="to" onChange={(e) => setArg("to", e.target.value)} />
        </>
      );
    case "date_parse": {
      const formats = Array.isArray(a.formats) ? (a.formats as string[]).join(", ") : "";
      return (
        <input
          style={{ width: 160 }}
          defaultValue={formats}
          placeholder="%m/%d/%Y, %Y-%m-%d"
          title="Formats tried in order, comma separated"
          onBlur={(e) => setArg("formats", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
        />
      );
    }
    case "case":
      return (
        <select value={str("mode") || "title"} onChange={(e) => setArg("mode", e.target.value)}>
          <option value="upper">UPPER</option>
          <option value="lower">lower</option>
          <option value="title">Title Case</option>
          <option value="sentence">Sentence case</option>
        </select>
      );
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------------------------
// Value mappings (IMP-03)
// ---------------------------------------------------------------------------------------------

function ValueMappingsPanel({ batch, attrByCode }: { batch: ImportBatch; attrByCode: Map<string, { label: string }> }) {
  const optionLists = useOptionLists();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["imports", "value-mappings", batch.id], queryFn: () => api.imports.valueMappings(batch.id) });
  const [edits, setEdits] = useState<Record<string, string | null>>({}); // key `${list_code}\u0000${raw}`

  const keyOf = (l: ValueMappingList, raw: string) => `${l.list_code}\u0000${raw}`;
  const currentFor = (l: ValueMappingList, v: { raw: string; option_code?: string | null }) => {
    const k = keyOf(l, v.raw);
    return k in edits ? edits[k] : (v.option_code ?? null);
  };

  const save = useMutation({
    mutationFn: () => {
      const items = Object.entries(edits).map(([k, option_code]) => {
        const [list_code, raw] = k.split("\u0000");
        return { list_code, raw, option_code };
      });
      return api.imports.saveValueMappings(batch.id, items);
    },
    onSuccess: () => {
      setEdits({});
      toast("Value mappings saved and remembered for this source.", "ok");
      qc.invalidateQueries({ queryKey: ["imports", "value-mappings", batch.id] });
    },
  });

  const listByCode = useMemo(() => new Map((optionLists.data ?? []).map((l) => [l.code, l])), [optionLists.data]);
  const lists = q.data?.lists ?? [];
  const unmappedCount = lists.reduce((n, l) => n + l.values.filter((v) => !currentFor(l, v)).length, 0);

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Value mappings (select attributes)</h3>
        <div className="row">
          {unmappedCount > 0 && <Badge color="amber">{unmappedCount} unmapped</Badge>}
          <button className="small primary" disabled={Object.keys(edits).length === 0 || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving" : `Save value mappings${Object.keys(edits).length ? ` (${Object.keys(edits).length})` : ""}`}
          </button>
        </div>
      </div>
      {q.isLoading && (
        <div className="panel-body">
          <Spinner />
        </div>
      )}
      {q.isError && (
        <div className="panel-body">
          <ErrorBox error={q.error} title="Could not load value mappings" />
        </div>
      )}
      {q.data && lists.length === 0 && <div className="empty">No select attributes are mapped, so there are no incoming values to translate.</div>}
      {lists.map((l) => {
        const list = listByCode.get(l.list_code);
        const options = (list?.values ?? []).slice().sort((a, b) => a.sort_order - b.sort_order);
        return (
          <div key={`${l.attribute_code}:${l.list_code}`}>
            <div className="group-head" style={{ padding: "6px 12px", background: "var(--teal-faint)", borderBottom: "1px solid var(--border)", fontWeight: 600 }}>
              {attrByCode.get(l.attribute_code)?.label ?? l.attribute_code} <span className="faint small mono">list {l.list_code}</span>
            </div>
            <table className="data compact">
              <thead>
                <tr>
                  <th>Incoming value</th>
                  <th className="right">Rows</th>
                  <th>Our option</th>
                  <th>Suggestion</th>
                </tr>
              </thead>
              <tbody>
                {l.values.map((v) => {
                  const cur = currentFor(l, v);
                  const suggestedLabel = v.suggested ? (options.find((o) => o.code === v.suggested)?.label ?? v.suggested) : null;
                  return (
                    <tr key={v.raw}>
                      <td className="mono">{v.raw || <span className="faint">(blank)</span>}</td>
                      <td className="num">{v.count}</td>
                      <td>
                        <select value={cur ?? ""} onChange={(e) => setEdits((ed) => ({ ...ed, [keyOf(l, v.raw)]: e.target.value || null }))}>
                          <option value="">(not mapped)</option>
                          {options.map((o) => (
                            <option key={o.code} value={o.code}>
                              {o.label}
                            </option>
                          ))}
                          {!list && cur && <option value={cur}>{cur}</option>}
                        </select>
                      </td>
                      <td>
                        {v.suggested && v.suggested !== cur ? (
                          <span className="row">
                            <span>{suggestedLabel}</span>
                            {v.confidence !== undefined && <span className={`confidence ${confidenceClass(v.confidence)}`}>{Math.round(v.confidence * 100)}%</span>}
                            <button className="small" onClick={() => setEdits((ed) => ({ ...ed, [keyOf(l, v.raw)]: v.suggested ?? null }))}>
                              Accept
                            </button>
                          </span>
                        ) : (
                          <span className="faint small">{v.suggested ? "accepted" : ""}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        );
      })}
      {save.isError && (
        <div className="panel-body">
          <ErrorBox error={save.error} title="Could not save value mappings" />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Save as template
// ---------------------------------------------------------------------------------------------

function SaveTemplateDialog({
  batch,
  mapping,
  matchKeys,
  unmatched,
  onClose,
}: {
  batch: ImportBatch;
  mapping: ColumnMapping[];
  matchKeys: string[];
  unmatched: UnmatchedPolicy;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const toast = useToast();
  const qc = useQueryClient();
  const first = batch.files[0];
  const save = useMutation({
    mutationFn: () =>
      api.imports.createTemplate({
        batch_id: batch.id,
        source_code: batch.source_code,
        name: name.trim(),
        level: batch.level,
        header_row: first?.header_row ?? 1,
        group_header_row: first?.group_header_row ?? null,
        data_start_row: first?.data_start_row ?? 2,
        columns: mapping,
        match_keys: matchKeys,
        unmatched_policy: unmatched,
      }),
    onSuccess: () => {
      toast("Template saved. It applies automatically to future files with this layout.", "ok");
      qc.invalidateQueries({ queryKey: ["imports", "templates"] });
      onClose();
    },
  });
  return (
    <Dialog
      title="Save mapping as template"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving" : "Save template"}
          </button>
        </>
      }
    >
      <div className="stack">
        <label className="field">
          Template name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Factory line sheet 2026" autoFocus />
        </label>
        <div className="muted small">
          Source {batch.source_code}, level {batch.level}, {mapping.filter((m) => !m.skip).length} mapped targets, match keys {matchKeys.join(", ") || "none"}.
          The structure signature comes from the uploaded file.
        </div>
        {save.isError && <ErrorBox error={save.error} title="Could not save the template" />}
      </div>
    </Dialog>
  );
}
