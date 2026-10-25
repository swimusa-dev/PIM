// EXP-09, EXP-10, EXP-11 (plus the EXP-08 Walmart settings and the D-01 / D-02 Rithum settings): Transport tab
// of the channel editor, backed by GET / PUT /api/channels/{code}/transport. Transport radio, file format, feed
// template upload (POST feed-template) with download link and returned header columns, header row, the feed
// columns table editor (one row per FeedColumn with a metadata-driven source picker, case transform, value map,
// flags, add / remove / reorder, "Columns from template"), and the conditional SFTP, Email, Walmart and Rithum
// sections. Save needs the edit_profile channel right (RBAC-03; "*" wildcard, admins pass).

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { channelApi } from "../../api/client";
import type {
  Channel,
  ChannelTransport,
  EmailSettings,
  FeedCaseTransform,
  FeedColumn,
  FeedFileFormat,
  RithumSettings,
  SftpSettings,
  TransportKind,
  WalmartSettings,
} from "../../api/types";
import { Badge, Empty, ErrorBox, Spinner, useToast } from "../../components/Common";
import { AttributePicker, useAttributePickerGroups, type PickerGroup } from "./MappingTab";

// The only hard-coded identifiers (DM-01), sent with the core. prefix the feed resolver expects.
const CORE_SOURCES: { value: string; label: string }[] = [
  { value: "core.style_number", label: "Style number" },
  { value: "core.color_code", label: "Color code" },
  { value: "core.size", label: "Size" },
  { value: "core.sku", label: "SKU" },
  { value: "core.upc", label: "UPC" },
];
const IMAGE_SOURCES: { value: string; label: string }[] = [1, 2, 3, 4, 5, 6].map((n) => ({ value: `image:${n}`, label: `Image ${n}` }));
const RETAIL_SOURCES: { value: string; label: string }[] = [
  { value: "nrf_color", label: "NRF color code" },
  { value: "nrf_size", label: "NRF size code" },
  { value: "gtin", label: "GTIN" },
];

const TRANSPORTS: { value: TransportKind; label: string; help: string }[] = [
  { value: "download", label: "Download", help: "Files are written to the volume and downloaded from the publish page." },
  { value: "sftp", label: "SFTP", help: "Files are uploaded to the retailer's SFTP folder after each publish." },
  { value: "email", label: "Email", help: "Files are emailed to the recipients below after each publish." },
  { value: "api", label: "API", help: "The channel adapter submits items directly (Walmart Marketplace feeds)." },
];
const FORMATS: FeedFileFormat[] = ["csv", "xlsx", "json"];
const CASES: { value: FeedCaseTransform; label: string }[] = [
  { value: "as_is", label: "As is" },
  { value: "title", label: "Title Case" },
  { value: "sentence", label: "Sentence case" },
  { value: "upper", label: "UPPER CASE" },
  { value: "lower", label: "lower case" },
];

export const EMPTY_TRANSPORT: ChannelTransport = {
  transport: "download",
  file_format: "csv",
  feed_template_path: null,
  feed_template_name: null,
  header_row: 1,
  feed_columns: [],
  sftp: null,
  email: null,
  walmart: null,
  rithum: null,
};
const EMPTY_SFTP: SftpSettings = { host: "", port: 22, path: "/", username: "", secret_name: "", host_key: "" };
const EMPTY_EMAIL: EmailSettings = { to: [], subject: "" };
const EMPTY_RITHUM: RithumSettings = { program: "nordstrom_dropship", supplier_id: null, vpn_prefix: null, family_rules: false };

function emptyColumn(header = ""): FeedColumn {
  return { header, source: "", always_include: false, case_transform: "as_is", value_map: {}, required: false };
}

export function isWalmartAdapter(channel: Channel): boolean {
  return channel.adapter.toLowerCase() === "walmart_mp" || channel.adapter.toLowerCase().includes("walmart");
}
export function isRithumAdapter(channel: Channel): boolean {
  return channel.adapter.toLowerCase().includes("rithum");
}

function emptyWalmart(channel: Channel): WalmartSettings {
  return { spec_version: "", product_type: String(channel.config?.product_type ?? ""), max_items_per_feed: 1000, variant_attribute_names: [] };
}

/** Normalizes what the server returns so every section the UI edits has a value. */
function fromServer(t: ChannelTransport, channel: Channel): ChannelTransport {
  return {
    ...EMPTY_TRANSPORT,
    ...t,
    feed_columns: (t.feed_columns ?? []).map((c) => ({ ...emptyColumn(), ...c, value_map: { ...(c.value_map ?? {}) } })),
    sftp: t.sftp ? { ...EMPTY_SFTP, ...t.sftp } : null,
    email: t.email ? { ...EMPTY_EMAIL, ...t.email, to: [...(t.email.to ?? [])] } : null,
    walmart: t.walmart ? { ...emptyWalmart(channel), ...t.walmart, variant_attribute_names: [...(t.walmart.variant_attribute_names ?? [])] } : null,
    rithum: t.rithum ? { ...EMPTY_RITHUM, ...t.rithum } : null,
  };
}

export function TransportTab({ channel, canEdit }: { channel: Channel; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const q = useQuery({ queryKey: ["channel", channel.code, "transport"], queryFn: () => channelApi.transport(channel.code) });
  const [draft, setDraft] = useState<ChannelTransport | null>(null);
  const [dirty, setDirty] = useState(false);
  const [templateColumns, setTemplateColumns] = useState<string[] | null>(null);
  const [templateFile, setTemplateFile] = useState<File | null>(null);

  useEffect(() => {
    if (q.data && !dirty) setDraft(fromServer(q.data, channel));
  }, [q.data, dirty, channel]);

  const update = (patch: Partial<ChannelTransport>) => {
    setDraft((d) => ({ ...(d ?? EMPTY_TRANSPORT), ...patch }));
    setDirty(true);
  };

  const save = useMutation({
    mutationFn: () => channelApi.saveTransport(channel.code, draft!),
    onSuccess: () => {
      toast("Transport saved. The channel version was bumped.", "ok");
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["channel", channel.code] });
      qc.invalidateQueries({ queryKey: ["metadata", "channels"] });
    },
    onError: (e) => toast(`Save failed: ${(e as Error).message}`, "error"),
  });

  const upload = useMutation({
    mutationFn: (file: File) => channelApi.uploadFeedTemplate(channel.code, file),
    onSuccess: async (r) => {
      setTemplateColumns(r.columns);
      setTemplateFile(null);
      if (fileRef.current) fileRef.current.value = "";
      // The server stored the template, may have switched the file format to xlsx and appended one unmapped feed
      // column per new header. Fold that into the draft (keeping any unsaved edits) instead of marking the stale
      // columns dirty: a later Save would otherwise PUT the pre-upload columns and format over what was just added.
      const fresh = fromServer(await channelApi.transport(channel.code), channel);
      setDraft((d) => {
        const base = d ?? fresh;
        const have = new Set(base.feed_columns.map((c) => c.header));
        return {
          ...base,
          feed_template_path: fresh.feed_template_path,
          feed_template_name: fresh.feed_template_name,
          file_format: fresh.file_format,
          feed_columns: [...base.feed_columns, ...fresh.feed_columns.filter((c) => !have.has(c.header))],
        };
      });
      qc.setQueryData(["channel", channel.code, "transport"], fresh);
      toast(
        `Template stored: ${r.columns.length} header column${r.columns.length === 1 ? "" : "s"} read${r.schema_loaded ? "; the target schema was loaded from it" : ""}.`,
        "ok",
      );
      // The server may have loaded a schema and added unmapped feed_columns to the mapping.
      qc.invalidateQueries({ queryKey: ["channel", channel.code, "schema"] });
      qc.invalidateQueries({ queryKey: ["channel", channel.code, "mapping"] });
    },
    onError: (e) => toast(`Template upload failed: ${(e as Error).message}`, "error"),
  });

  const picker = useAttributePickerGroups();
  const sourceGroups = useMemo<PickerGroup[]>(
    () => [
      { label: "Core identifiers", options: CORE_SOURCES },
      ...picker.groups.filter((g) => g.label !== "Core identifiers"),
      { label: "Images", options: IMAGE_SOURCES },
      { label: "Retail codes", options: RETAIL_SOURCES },
    ],
    [picker.groups],
  );
  const attributeGroups = useMemo<PickerGroup[]>(() => picker.groups.filter((g) => g.label !== "Core identifiers"), [picker.groups]);

  if (q.isLoading || !draft) return <Spinner label="Loading transport" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load the channel transport" />;

  const showWalmart = isWalmartAdapter(channel) || !!draft.walmart;
  const showRithum = isRithumAdapter(channel) || !!draft.rithum;
  const problems = validate(draft);
  const headers = templateColumns ?? null;

  const columnsFromTemplate = () => {
    if (!headers || headers.length === 0) return;
    const existing = new Map(draft.feed_columns.map((c) => [c.header, c]));
    update({ feed_columns: headers.map((h) => existing.get(h) ?? emptyColumn(h)) });
  };
  const discard = () => {
    setDirty(false);
    if (q.data) setDraft(fromServer(q.data, channel));
    qc.invalidateQueries({ queryKey: ["channel", channel.code, "transport"] });
  };

  return (
    <div className="stack gap16">
      {!canEdit && <div className="banner warn">You can view the transport settings but editing them needs the edit_profile right for {channel.label}.</div>}

      <div className="panel">
        <div className="panel-header">
          <h3>Transport</h3>
          <div className="row">
            {dirty && <span className="faint small">Unsaved changes</span>}
            <button className="small" disabled={!dirty || save.isPending} onClick={discard}>
              Discard
            </button>
            <button
              className="primary small"
              disabled={!canEdit || !dirty || save.isPending || problems.length > 0}
              title={problems.length > 0 ? problems.join("\n") : undefined}
              onClick={() => save.mutate()}
            >
              {save.isPending ? "Saving" : "Save transport"}
            </button>
          </div>
        </div>
        <div className="panel-body">
          <fieldset disabled={!canEdit} style={{ border: "none", padding: 0, margin: 0 }}>
            <div className="stack gap16">
              <div>
                <div className="muted small mb8">How the files of a publish leave the PIM</div>
                <div className="row" style={{ flexWrap: "wrap", gap: 16 }}>
                  {TRANSPORTS.map((t) => (
                    <label key={t.value} className="inline" title={t.help}>
                      <input type="radio" name={`transport-${channel.code}`} checked={draft.transport === t.value} onChange={() => update({ transport: t.value })} /> {t.label}
                    </label>
                  ))}
                </div>
                <span className="help">{TRANSPORTS.find((t) => t.value === draft.transport)?.help}</span>
              </div>
              <div className="form-grid">
                <label className="field">
                  File format
                  <select value={draft.file_format} onChange={(e) => update({ file_format: e.target.value as FeedFileFormat })}>
                    {FORMATS.map((f) => (
                      <option key={f} value={f}>
                        {f.toUpperCase()}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  Header row (1-based)
                  <input type="number" min={1} value={draft.header_row} onChange={(e) => update({ header_row: Math.max(1, Number(e.target.value) || 1) })} />
                  <span className="help">Row of the template that holds the column headers; data starts on the next row.</span>
                </label>
              </div>
            </div>
          </fieldset>
          {problems.length > 0 && (
            <ul className="small mt8" style={{ color: "var(--amber)", margin: "8px 0 0", paddingLeft: 18 }}>
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          {save.isError && <ErrorBox error={save.error} title="Save failed" />}
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Feed template</h3>
          <span className="muted small">XLSX or CSV template from the retailer; the header row names the feed columns (EXP-10).</span>
        </div>
        <div className="panel-body stack gap16">
          <dl className="kv">
            <dt>Stored template</dt>
            <dd>
              {draft.feed_template_name ? (
                <>
                  <a href={channelApi.feedTemplateUrl(channel.code)} download className="mono">
                    {draft.feed_template_name}
                  </a>
                  {draft.feed_template_path && <div className="faint small mono">{draft.feed_template_path}</div>}
                </>
              ) : (
                <span className="faint">none uploaded yet</span>
              )}
            </dd>
            <dt>Header columns</dt>
            <dd>
              {headers ? (
                headers.length === 0 ? (
                  <span className="faint">the uploaded template has no header columns on row {draft.header_row}</span>
                ) : (
                  <div className="chips">
                    {headers.map((h, i) => (
                      <Badge key={`${h}-${i}`} color="teal">
                        {h}
                      </Badge>
                    ))}
                  </div>
                )
              ) : (
                <span className="faint">{draft.feed_template_name ? "Upload the template again to read its header columns." : "Shown after an upload."}</span>
              )}
            </dd>
          </dl>
          {canEdit && (
            <div className="row" style={{ flexWrap: "wrap", gap: 12, alignItems: "end" }}>
              <label className="field">
                Upload template (.xlsx or .csv)
                <input
                  ref={fileRef}
                  type="file"
                  accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
                  onChange={(e) => setTemplateFile(e.target.files?.[0] ?? null)}
                />
              </label>
              <button className="primary" disabled={!templateFile || upload.isPending} onClick={() => templateFile && upload.mutate(templateFile)}>
                {upload.isPending ? "Uploading" : "Upload template"}
              </button>
              <button className="small" disabled={!headers || headers.length === 0} title="One feed column per template header; existing rows with the same header keep their source" onClick={columnsFromTemplate}>
                Columns from template
              </button>
            </div>
          )}
          {upload.isError && <ErrorBox error={upload.error} title="Template upload failed" />}
        </div>
      </div>

      <FeedColumnsEditor
        columns={draft.feed_columns}
        setColumns={(cols) => update({ feed_columns: cols })}
        sourceGroups={sourceGroups}
        loadingAttributes={picker.loading}
        canEdit={canEdit}
      />

      {draft.transport === "sftp" && <SftpSection sftp={draft.sftp ?? EMPTY_SFTP} setSftp={(s) => update({ sftp: s })} canEdit={canEdit} />}
      {draft.transport === "email" && <EmailSection email={draft.email ?? EMPTY_EMAIL} setEmail={(e) => update({ email: e })} canEdit={canEdit} />}
      {showWalmart && (
        <WalmartSection walmart={draft.walmart ?? emptyWalmart(channel)} setWalmart={(w) => update({ walmart: w })} attributeGroups={attributeGroups} canEdit={canEdit} />
      )}
      {showRithum && <RithumSection rithum={draft.rithum ?? EMPTY_RITHUM} setRithum={(r) => update({ rithum: r })} canEdit={canEdit} />}
    </div>
  );
}

function validate(t: ChannelTransport): string[] {
  const out: string[] = [];
  if (t.header_row < 1) out.push("The header row must be 1 or higher.");
  if (t.feed_columns.some((c) => !c.header.trim())) out.push("Every feed column needs a header.");
  if (t.transport === "sftp") {
    const s = t.sftp;
    if (!s || !s.host.trim() || !s.username.trim() || !s.secret_name.trim()) out.push("SFTP needs a host, a username and a secret name.");
    if (s && !(s.host_key ?? "").trim()) out.push("SFTP needs the server's host key so uploads go only to that server.");
    if (s && (!(s.port > 0) || s.port > 65535)) out.push("The SFTP port must be between 1 and 65535.");
  }
  if (t.transport === "email") {
    const e = t.email;
    if (!e || e.to.length === 0) out.push("Email needs at least one recipient.");
  }
  if (t.walmart && !(t.walmart.max_items_per_feed > 0)) out.push("Walmart max items per feed must be above zero.");
  return out;
}

// ---- Feed columns table ----
function FeedColumnsEditor({
  columns,
  setColumns,
  sourceGroups,
  loadingAttributes,
  canEdit,
}: {
  columns: FeedColumn[];
  setColumns: (c: FeedColumn[]) => void;
  sourceGroups: PickerGroup[];
  loadingAttributes: boolean;
  canEdit: boolean;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const patch = (i: number, p: Partial<FeedColumn>) => setColumns(columns.map((c, j) => (j === i ? { ...c, ...p } : c)));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= columns.length) return;
    const next = columns.slice();
    [next[i], next[j]] = [next[j], next[i]];
    setColumns(next);
    if (open === i) setOpen(j);
    else if (open === j) setOpen(i);
  };
  const remove = (i: number) => {
    setColumns(columns.filter((_, j) => j !== i));
    setOpen(null);
  };
  const unmapped = columns.filter((c) => !c.source && !c.always_include).length;

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>
          Feed columns <span className="muted small">({columns.length})</span>{" "}
          {unmapped > 0 && (
            <Badge color="amber" title="Columns without a source are written empty unless Always include carries a fixed value">
              {unmapped} without source
            </Badge>
          )}
        </h3>
        {canEdit && (
          <button className="small" onClick={() => setColumns([...columns, emptyColumn()])}>
            Add column
          </button>
        )}
      </div>
      <div className="panel-body flush" style={{ maxHeight: 560, overflow: "auto" }}>
        {loadingAttributes && <Spinner label="Loading attributes" />}
        {columns.length === 0 ? (
          <Empty title="No feed columns">Upload the retailer template and use "Columns from template", or add columns by hand. Each column takes one PIM source.</Empty>
        ) : (
          <table className="data compact feed-table">
            <thead>
              <tr>
                <th style={{ width: 32 }}>#</th>
                <th>Header</th>
                <th>Source</th>
                <th title="Write the column even when the value is empty">Always</th>
                <th>Case</th>
                <th>Value map</th>
                <th title="A row missing this value is invalid">Required</th>
                {canEdit && <th />}
              </tr>
            </thead>
            <tbody>
              {columns.map((c, i) => {
                const mapCount = Object.keys(c.value_map ?? {}).length;
                return (
                  <FeedColumnRows
                    key={i}
                    index={i}
                    column={c}
                    mapCount={mapCount}
                    open={open === i}
                    canEdit={canEdit}
                    sourceGroups={sourceGroups}
                    last={i === columns.length - 1}
                    onPatch={(p) => patch(i, p)}
                    onToggle={() => setOpen(open === i ? null : i)}
                    onMove={(d) => move(i, d)}
                    onRemove={() => remove(i)}
                  />
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function FeedColumnRows({
  index,
  column: c,
  mapCount,
  open,
  canEdit,
  sourceGroups,
  last,
  onPatch,
  onToggle,
  onMove,
  onRemove,
}: {
  index: number;
  column: FeedColumn;
  mapCount: number;
  open: boolean;
  canEdit: boolean;
  sourceGroups: PickerGroup[];
  last: boolean;
  onPatch: (p: Partial<FeedColumn>) => void;
  onToggle: () => void;
  onMove: (d: -1 | 1) => void;
  onRemove: () => void;
}) {
  return (
    <>
      <tr>
        <td className="num faint">{index + 1}</td>
        <td>
          <input value={c.header} disabled={!canEdit} placeholder="Column header" className={c.header.trim() ? "" : "invalid"} style={{ width: 160 }} onChange={(e) => onPatch({ header: e.target.value })} />
        </td>
        <td>
          <AttributePicker value={c.source} groups={sourceGroups} disabled={!canEdit} onChange={(v) => onPatch({ source: v })} />
        </td>
        <td>
          <input type="checkbox" checked={c.always_include} disabled={!canEdit} onChange={(e) => onPatch({ always_include: e.target.checked })} />
        </td>
        <td>
          <select value={c.case_transform} disabled={!canEdit} onChange={(e) => onPatch({ case_transform: e.target.value as FeedCaseTransform })}>
            {CASES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </td>
        <td>
          <button className="small link" onClick={onToggle} title="Map PIM values to the retailer's expected values for this column">
            {mapCount === 0 ? "none" : `${mapCount} value${mapCount === 1 ? "" : "s"}`} {open ? "(hide)" : "(edit)"}
          </button>
        </td>
        <td>
          <input type="checkbox" checked={c.required} disabled={!canEdit} onChange={(e) => onPatch({ required: e.target.checked })} />
        </td>
        {canEdit && (
          <td className="nowrap">
            <button className="icon small" aria-label="Move up" title="Move up" disabled={index === 0} onClick={() => onMove(-1)}>
              &uarr;
            </button>{" "}
            <button className="icon small" aria-label="Move down" title="Move down" disabled={last} onClick={() => onMove(1)}>
              &darr;
            </button>{" "}
            <button className="icon small" aria-label="Remove column" title="Remove column" onClick={onRemove}>
              x
            </button>
          </td>
        )}
      </tr>
      {open && (
        <tr className="value-map-row">
          <td />
          <td colSpan={canEdit ? 7 : 6}>
            <ValueMapEditor map={c.value_map ?? {}} setMap={(m) => onPatch({ value_map: m })} canEdit={canEdit} />
          </td>
        </tr>
      )}
    </>
  );
}

/** Key / value rows: PIM value (option code or text) to the value written in the feed. */
function ValueMapEditor({ map, setMap, canEdit }: { map: Record<string, string>; setMap: (m: Record<string, string>) => void; canEdit: boolean }) {
  const [rows, setRows] = useState<{ k: string; v: string }[]>(() => Object.entries(map).map(([k, v]) => ({ k, v })));
  const commit = (next: { k: string; v: string }[]) => {
    setRows(next);
    const out: Record<string, string> = {};
    for (const r of next) if (r.k.trim()) out[r.k.trim()] = r.v;
    setMap(out);
  };
  return (
    <div className="stack" style={{ gap: 4, padding: "4px 0" }}>
      <span className="muted small">Value map: PIM value on the left, feed value on the right. Values not listed pass through unchanged.</span>
      {rows.length === 0 && <span className="faint small">No mapped values.</span>}
      {rows.map((r, i) => (
        <div key={i} className="transform-row">
          <input className="mono" value={r.k} disabled={!canEdit} placeholder="PIM value" style={{ width: 180 }} onChange={(e) => commit(rows.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)))} />
          <span className="faint">to</span>
          <input value={r.v} disabled={!canEdit} placeholder="Feed value" style={{ width: 180 }} onChange={(e) => commit(rows.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)))} />
          {canEdit && (
            <button className="icon small" aria-label="Remove mapping" onClick={() => commit(rows.filter((_, j) => j !== i))}>
              x
            </button>
          )}
        </div>
      ))}
      {canEdit && (
        <div>
          <button className="small" onClick={() => commit([...rows, { k: "", v: "" }])}>
            Add value
          </button>
        </div>
      )}
    </div>
  );
}

// ---- Conditional sections ----
function SftpSection({ sftp, setSftp, canEdit }: { sftp: SftpSettings; setSftp: (s: SftpSettings) => void; canEdit: boolean }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>SFTP settings</h3>
      </div>
      <div className="panel-body">
        <fieldset disabled={!canEdit} style={{ border: "none", padding: 0, margin: 0 }}>
          <div className="form-grid">
            <label className="field">
              Host
              <input value={sftp.host} className={sftp.host.trim() ? "" : "invalid"} placeholder="sftp.retailer.com" onChange={(e) => setSftp({ ...sftp, host: e.target.value })} />
            </label>
            <label className="field">
              Port
              <input type="number" min={1} max={65535} value={sftp.port} onChange={(e) => setSftp({ ...sftp, port: Number(e.target.value) || 22 })} />
            </label>
            <label className="field">
              Remote path
              <input className="mono" value={sftp.path} placeholder="/inbound/items" onChange={(e) => setSftp({ ...sftp, path: e.target.value })} />
            </label>
            <label className="field">
              Username
              <input value={sftp.username} className={sftp.username.trim() ? "" : "invalid"} onChange={(e) => setSftp({ ...sftp, username: e.target.value })} />
            </label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>
              Secret name
              <input className="mono" value={sftp.secret_name} placeholder="retailer-sftp" onChange={(e) => setSftp({ ...sftp, secret_name: e.target.value })} />
              <span className="help">The password or private key is never stored in the PIM. It lives in an app secret resource with this name, bound to the Databricks App.</span>
            </label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>
              Server host key
              <input
                className={`mono${(sftp.host_key ?? "").trim() ? "" : " invalid"}`}
                value={sftp.host_key ?? ""}
                placeholder="ssh-keyscan output (ssh-ed25519 AAAA...) or SHA256:fingerprint"
                onChange={(e) => setSftp({ ...sftp, host_key: e.target.value })}
              />
              <span className="help">The key the retailer's server presents must match this before the password or key is sent. Run ssh-keyscan against the host, or paste the SHA256 fingerprint from the retailer's onboarding sheet.</span>
            </label>
          </div>
        </fieldset>
      </div>
    </div>
  );
}

function EmailSection({ email, setEmail, canEdit }: { email: EmailSettings; setEmail: (e: EmailSettings) => void; canEdit: boolean }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const parts = draft.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
    if (parts.length === 0) return;
    setEmail({ ...email, to: Array.from(new Set([...email.to, ...parts])) });
    setDraft("");
  };
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Email settings</h3>
      </div>
      <div className="panel-body">
        <fieldset disabled={!canEdit} style={{ border: "none", padding: 0, margin: 0 }}>
          <div className="stack gap16">
            <div>
              <div className="muted small mb8">Recipients</div>
              {email.to.length === 0 && <div className="faint small mb8">No recipients yet.</div>}
              <div className="chips mb8">
                {email.to.map((r) => (
                  <span key={r} className="chip">
                    {r}
                    {canEdit && (
                      <button aria-label={`Remove ${r}`} onClick={() => setEmail({ ...email, to: email.to.filter((x) => x !== r) })}>
                        x
                      </button>
                    )}
                  </span>
                ))}
              </div>
              {canEdit && (
                <div className="row">
                  <input
                    type="email"
                    value={draft}
                    placeholder="buyer@retailer.com"
                    style={{ width: 280 }}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        add();
                      }
                    }}
                  />
                  <button className="small" onClick={add} disabled={!draft.trim()}>
                    Add recipient
                  </button>
                </div>
              )}
            </div>
            <label className="field">
              Subject
              <input value={email.subject} placeholder="Swim USA item feed {{channel}} {{date}}" onChange={(e) => setEmail({ ...email, subject: e.target.value })} />
            </label>
          </div>
        </fieldset>
      </div>
    </div>
  );
}

function WalmartSection({
  walmart,
  setWalmart,
  attributeGroups,
  canEdit,
}: {
  walmart: WalmartSettings;
  setWalmart: (w: WalmartSettings) => void;
  attributeGroups: PickerGroup[];
  canEdit: boolean;
}) {
  const names = [0, 1, 2].map((i) => walmart.variant_attribute_names[i] ?? "");
  const setName = (i: number, v: string) => {
    const next = names.slice();
    next[i] = v;
    setWalmart({ ...walmart, variant_attribute_names: next.filter(Boolean) });
  };
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Walmart Marketplace settings</h3>
        <span className="muted small">MP_ITEM feeds are submitted in batches of at most "max items per feed" (EXP-08).</span>
      </div>
      <div className="panel-body">
        <fieldset disabled={!canEdit} style={{ border: "none", padding: 0, margin: 0 }}>
          <div className="form-grid">
            <label className="field">
              Spec version
              <input value={walmart.spec_version} placeholder="e.g. 5.0" onChange={(e) => setWalmart({ ...walmart, spec_version: e.target.value })} />
            </label>
            <label className="field">
              Product type
              <input value={walmart.product_type} placeholder="e.g. Swimwear" onChange={(e) => setWalmart({ ...walmart, product_type: e.target.value })} />
            </label>
            <label className="field">
              Max items per feed
              <input type="number" min={1} value={walmart.max_items_per_feed} onChange={(e) => setWalmart({ ...walmart, max_items_per_feed: Number(e.target.value) || 0 })} />
            </label>
          </div>
          <div className="mt8">
            <div className="muted small mb8">Variant attributes (up to three; the attributes that distinguish the items of one variant group)</div>
            <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
              {names.map((n, i) => (
                <AttributePicker key={i} value={n} groups={attributeGroups} disabled={!canEdit} onChange={(v) => setName(i, v)} />
              ))}
            </div>
          </div>
        </fieldset>
      </div>
    </div>
  );
}

function RithumSection({ rithum, setRithum, canEdit }: { rithum: RithumSettings; setRithum: (r: RithumSettings) => void; canEdit: boolean }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Rithum settings</h3>
        <span className="muted small">Nordstrom dropship and Target+ both go through Rithum as template-based flat files (D-01, D-02).</span>
      </div>
      <div className="panel-body">
        <fieldset disabled={!canEdit} style={{ border: "none", padding: 0, margin: 0 }}>
          <div className="stack gap16">
            <div>
              <div className="muted small mb8">Program</div>
              <div className="row" style={{ gap: 16 }}>
                <label className="inline">
                  <input type="radio" checked={rithum.program === "nordstrom_dropship"} onChange={() => setRithum({ ...rithum, program: "nordstrom_dropship" })} /> Nordstrom dropship
                </label>
                <label className="inline">
                  <input type="radio" checked={rithum.program === "targetplus"} onChange={() => setRithum({ ...rithum, program: "targetplus" })} /> Target+
                </label>
              </div>
            </div>
            <div className="form-grid">
              <label className="field">
                Supplier id
                <input value={rithum.supplier_id ?? ""} onChange={(e) => setRithum({ ...rithum, supplier_id: e.target.value || null })} />
              </label>
              <label className="field">
                VPN prefix
                <input className="mono" value={rithum.vpn_prefix ?? ""} placeholder="e.g. VA-" onChange={(e) => setRithum({ ...rithum, vpn_prefix: e.target.value || null })} />
                <span className="help">Prepended to the style number to form the vendor part number.</span>
              </label>
            </div>
            <label className="inline">
              <input type="checkbox" checked={rithum.family_rules} onChange={(e) => setRithum({ ...rithum, family_rules: e.target.checked })} /> Family rules
            </label>
            <span className="help">Target+: a family is checked as a unit; one invalid child fails the family.</span>
          </div>
        </fieldset>
      </div>
    </div>
  );
}
