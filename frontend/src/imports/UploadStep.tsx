// IMP-01 Upload step, IMP-08 Shopify pull, IMP-12 keyed worksheet recognition, IMP-05 hint.
// Source picker, level picker, drag-and-drop file input (CSV / XLSX, several files), detected files.

import { useRef, useState, type DragEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useImportSources } from "../api/hooks";
import type { ImportBatch, ImportFile, Level } from "../api/types";
import { Badge, ErrorBox, Spinner, useToast } from "../components/Common";
import { LEVEL_LABEL } from "../lib/format";
import { SOURCE_KIND_TEXT } from "../pages/Imports";

const ACCEPT = ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function FileDrop({ onFiles, label, multiple = true }: { onFiles: (f: File[]) => void; label: string; multiple?: boolean }) {
  const [over, setOver] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const files = Array.from(e.dataTransfer.files).filter((f) => /\.(csv|xlsx)$/i.test(f.name));
    if (files.length) onFiles(multiple ? files : files.slice(0, 1));
  };
  return (
    <div
      className={`dropzone${over ? " over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      onClick={() => ref.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && ref.current?.click()}
    >
      <div>{label}</div>
      <div className="faint small">Drop .csv or .xlsx files here, or click to choose</div>
      <input
        ref={ref}
        type="file"
        accept={ACCEPT}
        multiple={multiple}
        style={{ display: "none" }}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) onFiles(files);
          e.target.value = "";
        }}
      />
    </div>
  );
}

export function UploadStep({
  batch,
  onBatch,
  onNext,
}: {
  batch: ImportBatch | null;
  onBatch: (b: ImportBatch) => void;
  onNext: () => void;
}) {
  const sources = useImportSources();
  const toast = useToast();
  // IMP-01: header, group header and data-start rows chosen on this step are applied server-side before mapping,
  // so the Map step always sees the real column names. The server ignores unchanged files and refuses worksheets.
  const applyEdits = useMutation({
    mutationFn: async () => {
      if (!batch || batch.worksheet_id) return batch;
      const editable = batch.files.filter((f) => f.name !== "shopify snapshot");
      if (editable.length === 0) return batch;
      return api.imports.editFiles(
        batch.id,
        editable.map((f) => ({ index: f.index, header_row: f.header_row, group_header_row: f.group_header_row ?? null, data_start_row: f.data_start_row })),
      );
    },
    onSuccess: (b) => {
      if (b) onBatch(b);
      onNext();
    },
    onError: (e) => toast(`Could not apply the header rows: ${(e as Error).message}`, "error"),
  });
  const qc = useQueryClient();
  const [sourceCode, setSourceCode] = useState(batch?.source_code ?? "");
  const [level, setLevel] = useState<Level>(batch?.level ?? "style_color");
  const [pending, setPending] = useState<File[]>([]);
  const [shopifyCsv, setShopifyCsv] = useState<File | null>(null);

  const effectiveSource = sourceCode || sources.data?.[0]?.code || "";
  const source = sources.data?.find((s) => s.code === effectiveSource);
  const isShopify = source?.kind === "shopify";

  const create = useMutation({
    mutationFn: (files: File[]) => api.imports.createBatch(files, effectiveSource, level),
    onSuccess: (b) => {
      setPending([]);
      qc.invalidateQueries({ queryKey: ["imports", "batches"] });
      onBatch(b);
      toast(b.status === "mapped" ? "Files uploaded. A template matched the layout." : "Files uploaded and parsed.", "ok");
    },
  });
  const addFiles = useMutation({
    mutationFn: (files: File[]) => api.imports.addFiles(batch!.id, files, effectiveSource),
    onSuccess: (b) => {
      setPending([]);
      onBatch(b);
      toast("File added to the batch.", "ok");
    },
  });
  const shopify = useMutation({
    mutationFn: async (file: File | null) => {
      let b = batch;
      if (!b) b = await api.imports.createBatch(file ? [file] : [], effectiveSource, level);
      return api.imports.shopifyPull(b.id, file);
    },
    onSuccess: (b) => {
      setShopifyCsv(null);
      qc.invalidateQueries({ queryKey: ["imports", "batches"] });
      onBatch(b);
      toast("Shopify rows loaded into the batch.", "ok");
    },
  });

  const busy = create.isPending || addFiles.isPending || shopify.isPending;
  const upload = () => {
    if (!pending.length) return;
    if (batch) addFiles.mutate(pending);
    else create.mutate(pending);
  };
  const templateApplied = !!batch?.template_id;
  const worksheet = !!batch?.worksheet_id;

  return (
    <div className="stack gap16">
      <div className="banner info">
        Files without an identifier column need assisted matching; keyed worksheets (Imports &gt; Worksheet export) avoid this step.
      </div>

      {!batch && (
        <>
          <div>
            <h3 className="mb8">Source</h3>
            {sources.isLoading && <Spinner />}
            {sources.isError && <ErrorBox error={sources.error} title="Could not load import sources" />}
            {sources.data && sources.data.length === 0 && <div className="empty">No import sources are configured. Add one under Imports, Sources.</div>}
            <div className="source-cards">
              {(sources.data ?? []).map((s) => (
                <div
                  key={s.code}
                  className={`source-card${s.code === effectiveSource ? " selected" : ""}`}
                  onClick={() => setSourceCode(s.code)}
                  role="radio"
                  aria-checked={s.code === effectiveSource}
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && setSourceCode(s.code)}
                >
                  <b>{s.label}</b>
                  <div className="kind">{SOURCE_KIND_TEXT[s.kind]}</div>
                  <div className="faint small">
                    Unmatched: {s.default_policy.unmatched.replace(/_/g, " ")}, errors: {s.default_policy.on_error.replace(/_/g, " ")}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="row">
            <span className="muted">Level</span>
            <div className="seg grid-toolbar" style={{ padding: 0, border: "none", background: "none" }}>
              <div className="seg">
                {(["style", "style_color", "sku"] as Level[]).map((l) => (
                  <button key={l} className={l === level ? "active" : ""} onClick={() => setLevel(l)}>
                    {LEVEL_LABEL[l]}
                  </button>
                ))}
              </div>
            </div>
            <span className="faint small">Rows in the file describe entities at this level.</span>
          </div>
        </>
      )}

      {batch && (
        <div className="row">
          <span className="muted">Source</span>
          <b>{source?.label ?? batch.source_code}</b>
          <span className="muted">Level</span>
          <b>{LEVEL_LABEL[batch.level]}</b>
          <span className="muted">Created</span>
          <span>{batch.created_by}</span>
        </div>
      )}

      {worksheet && <div className="banner ok">Keyed worksheet detected: mapping and matching are automatic.</div>}
      {templateApplied && !worksheet && (
        <div className="banner ok">
          A saved mapping template matched this file layout and was applied. Review it on the Map step or go straight to Validate.
        </div>
      )}

      {isShopify && (
        <div className="panel">
          <div className="panel-header">
            <h3>Shopify pull (IMP-08)</h3>
          </div>
          <div className="panel-body stack">
            <div className="muted small">Read the current products through the Shopify Admin API, or upload a product CSV export instead.</div>
            <div className="row">
              <button className="primary" disabled={busy || !effectiveSource} onClick={() => shopify.mutate(null)}>
                {shopify.isPending ? "Pulling" : "Pull from Shopify"}
              </button>
              <span className="muted">or</span>
              <input type="file" accept=".csv,text/csv" onChange={(e) => setShopifyCsv(e.target.files?.[0] ?? null)} />
              <button disabled={!shopifyCsv || busy} onClick={() => shopify.mutate(shopifyCsv)}>
                Use this CSV
              </button>
            </div>
            {shopify.isError && <ErrorBox error={shopify.error} title="Shopify pull failed" />}
          </div>
        </div>
      )}

      <div>
        <h3 className="mb8">{batch ? "Add another file" : "Files"}</h3>
        <FileDrop onFiles={(f) => setPending((p) => [...p, ...f])} label={batch ? "Add another file to this batch (mixed sources are allowed)" : "Upload one or more files"} />
        {pending.length > 0 && (
          <div className="stack mt8">
            {pending.map((f, i) => (
              <div key={`${f.name}-${i}`} className="row">
                <span className="mono">{f.name}</span>
                <span className="faint small">{Math.round(f.size / 1024)} KB</span>
                <button className="link small" onClick={() => setPending((p) => p.filter((_, j) => j !== i))}>
                  remove
                </button>
              </div>
            ))}
            <div className="row">
              <button className="primary" disabled={busy || !effectiveSource} onClick={upload}>
                {busy ? "Uploading" : batch ? "Add to batch" : "Upload and parse"}
              </button>
              <button className="link small" onClick={() => setPending([])}>
                Clear
              </button>
            </div>
          </div>
        )}
        {create.isError && <ErrorBox error={create.error} title="Upload failed" />}
        {addFiles.isError && <ErrorBox error={addFiles.error} title="Could not add the file" />}
      </div>

      {batch && batch.files.length > 0 && <DetectedFiles batch={batch} onBatch={onBatch} />}

      {batch && (
        <div className="wizard-footer">
          <span className="muted small">
            {batch.files.length} file{batch.files.length === 1 ? "" : "s"}, {batch.stats?.rows ?? batch.files.reduce((n, f) => n + f.rows, 0)} rows
          </span>
          <button className="primary" disabled={applyEdits.isPending} onClick={() => applyEdits.mutate()}>
            {applyEdits.isPending ? "Applying header rows..." : `Next: ${worksheet ? "Validate" : "Map columns"}`}
          </button>
        </div>
      )}
    </div>
  );
}

/** Detected files with editable header rows. Edits are applied through the files endpoint when leaving this step. */
function DetectedFiles({ batch, onBatch }: { batch: ImportBatch; onBatch: (b: ImportBatch) => void }) {
  const update = (ix: number, patch: Partial<ImportFile>) => {
    onBatch({ ...batch, files: batch.files.map((f) => (f.index === ix ? { ...f, ...patch } : f)) });
  };
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Detected files</h3>
        <span className="faint small">Header rows are detected automatically; adjust them if the preview looks wrong.</span>
      </div>
      <table className="data compact">
        <thead>
          <tr>
            <th>File</th>
            <th>Sheet</th>
            <th>Header row</th>
            <th>Group header row</th>
            <th>Data starts</th>
            <th className="right">Rows</th>
            <th className="right">Columns</th>
            <th>Precedence</th>
          </tr>
        </thead>
        <tbody>
          {batch.files.map((f) => (
            <tr key={f.index}>
              <td className="mono">{f.name}</td>
              <td>{f.sheet ?? <span className="faint">n/a</span>}</td>
              <td>
                <input type="number" min={1} style={{ width: 70 }} value={f.header_row} onChange={(e) => update(f.index, { header_row: Number(e.target.value) })} />
              </td>
              <td>
                <input
                  type="number"
                  min={0}
                  style={{ width: 70 }}
                  value={f.group_header_row ?? ""}
                  placeholder="none"
                  onChange={(e) => update(f.index, { group_header_row: e.target.value === "" ? null : Number(e.target.value) })}
                />
              </td>
              <td>
                <input type="number" min={1} style={{ width: 70 }} value={f.data_start_row} onChange={(e) => update(f.index, { data_start_row: Number(e.target.value) })} />
              </td>
              <td className="num">{f.rows}</td>
              <td className="num">{f.columns.length}</td>
              <td>
                <Badge>{f.precedence}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
