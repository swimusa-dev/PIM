// EXP-02: Target schema tab for a channel. Loaded fields table, "Refresh schema" with optional file upload
// and Walmart product_type, SchemaDiff panel with a warning when required fields were added or removed.

import { useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { channelApi } from "../../api/client";
import type { Channel, SchemaDiff, TargetField, TargetSchema } from "../../api/types";
import { Badge, Empty, ErrorBox, Spinner, useToast } from "../../components/Common";
import { formatDate } from "../../lib/format";

const SOURCE_LABEL: Record<TargetSchema["source"], string> = {
  walmart_spec: "Walmart spec",
  mirakl: "Mirakl",
  shopify: "Shopify metafield definitions",
  retailer_xlsx: "Retailer XLSX template",
  manual: "Manual",
};

/** Explains where each adapter loads its target schema from (used by the empty state and the refresh hint). */
export function schemaSourceText(channel: Channel): string {
  const a = channel.adapter.toLowerCase();
  if (a.includes("walmart")) return "Walmart loads the spec for a product type from the Walmart spec API, or from an uploaded spec JSON.";
  if (a.includes("mirakl")) return "Mirakl loads the H11, PM11 or VL11 definition from an uploaded CSV or ZIP.";
  if (a.includes("shopify")) return "Shopify loads metafield definitions from the Admin API, or from an uploaded metafield definitions JSON.";
  if (a.includes("feed") || a.includes("xlsx") || channel.kind === "retailer") return "Retailer channels load the column list from an uploaded XLSX template.";
  return "This channel has no adapter-backed schema; upload a spec file (JSON, CSV, ZIP or XLSX) to load one.";
}

function isWalmart(channel: Channel) {
  return channel.adapter.toLowerCase().includes("walmart");
}

export function SchemaTab({ channel }: { channel: Channel }) {
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [productType, setProductType] = useState(() => String(channel.config?.product_type ?? ""));
  const [diff, setDiff] = useState<SchemaDiff | null>(null);

  const schema = useQuery({ queryKey: ["channel", channel.code, "schema"], queryFn: () => channelApi.schema(channel.code) });
  const lastDiff = useQuery({ queryKey: ["channel", channel.code, "schema-diff"], queryFn: () => channelApi.schemaDiff(channel.code), retry: false });

  const refresh = useMutation({
    mutationFn: () => channelApi.refreshSchema(channel.code, file, isWalmart(channel) ? productType || undefined : undefined),
    onSuccess: (r) => {
      setDiff(r.diff);
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      toast(`Schema refreshed: ${r.schema.fields.length} fields loaded.`, "ok");
      qc.invalidateQueries({ queryKey: ["channel", channel.code] });
      qc.invalidateQueries({ queryKey: ["metadata", "channels"] });
    },
    onError: (e) => toast(`Refresh failed: ${(e as Error).message}`, "error"),
  });

  const shownDiff = diff ?? (lastDiff.data && diffHasChanges(lastDiff.data) ? lastDiff.data : null);

  return (
    <div className="stack gap16">
      <div className="panel">
        <div className="panel-header">
          <h3>Refresh schema</h3>
          <span className="muted small">{schemaSourceText(channel)}</span>
        </div>
        <div className="panel-body row" style={{ flexWrap: "wrap", gap: 12 }}>
          <label className="field">
            Spec file (optional)
            <input ref={fileRef} type="file" accept=".json,.csv,.zip,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          {isWalmart(channel) && (
            <label className="field">
              Walmart product type
              <input value={productType} placeholder="e.g. Swimwear" onChange={(e) => setProductType(e.target.value)} />
            </label>
          )}
          <button className="primary" style={{ alignSelf: "end" }} disabled={refresh.isPending} onClick={() => refresh.mutate()}>
            {refresh.isPending ? "Refreshing" : file ? "Refresh from file" : "Refresh from adapter"}
          </button>
          {refresh.isError && <ErrorBox error={refresh.error} title="Refresh failed" />}
        </div>
      </div>

      {shownDiff && <DiffPanel diff={shownDiff} fresh={!!diff} onDismiss={() => setDiff(null)} />}

      {schema.isLoading && <Spinner label="Loading target schema" />}
      {schema.isError && <ErrorBox error={schema.error} title="Could not load the target schema" />}
      {schema.data && schema.data.fields.length === 0 && (
        <Empty title="No target schema loaded">
          {schemaSourceText(channel)} Use Refresh schema above; the mapping tab then shows every target field with its type and required flag.
        </Empty>
      )}
      {schema.data && schema.data.fields.length > 0 && (
        <div className="panel">
          <div className="panel-header">
            <h3>
              Target fields <span className="muted small">({schema.data.fields.length})</span>
            </h3>
            <span className="muted small">
              {SOURCE_LABEL[schema.data.source] ?? schema.data.source}
              {schema.data.version ? `, version ${schema.data.version}` : ""}
              {schema.data.product_type ? `, product type ${schema.data.product_type}` : ""}, loaded {formatDate(schema.data.loaded_at)}
              {schema.data.raw_available ? "" : " (raw spec not stored)"}
            </span>
          </div>
          <div className="panel-body flush" style={{ maxHeight: 480, overflow: "auto" }}>
            <SchemaFieldsTable fields={schema.data.fields} />
          </div>
        </div>
      )}
    </div>
  );
}

export function diffHasChanges(d: SchemaDiff): boolean {
  return d.added.length + d.removed.length + d.required_changed.length + d.enum_changed.length > 0;
}

function EnumBadge({ f }: { f: TargetField }) {
  if (!f.enum || f.enum.length === 0) return <span className="faint">none</span>;
  const list = f.enum.slice(0, 40).join("\n") + (f.enum.length > 40 ? `\n... ${f.enum.length - 40} more` : "");
  return (
    <span className="badge tip" data-tip={list}>
      {f.enum.length} value{f.enum.length === 1 ? "" : "s"}
    </span>
  );
}

export function SchemaFieldsTable({ fields }: { fields: TargetField[] }) {
  return (
    <table className="data compact">
      <thead>
        <tr>
          <th>Field</th>
          <th>Type</th>
          <th>Required</th>
          <th>Enum</th>
          <th className="right">Max length</th>
          <th>Group</th>
        </tr>
      </thead>
      <tbody>
        {fields.map((f) => (
          <tr key={f.name}>
            <td>
              <span className="mono">{f.name}</span>
              {f.path && <div className="faint small mono">{f.path}</div>}
              {f.description && <div className="faint small">{f.description}</div>}
            </td>
            <td>{f.type}</td>
            <td>{f.required ? <Badge color="red">required</Badge> : <span className="faint">optional</span>}</td>
            <td>
              <EnumBadge f={f} />
            </td>
            <td className="num">{f.max_length ?? <span className="faint">n/a</span>}</td>
            <td>{f.group ?? <span className="faint">none</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DiffPanel({ diff, fresh, onDismiss }: { diff: SchemaDiff; fresh: boolean; onDismiss: () => void }) {
  const requiredAdded = diff.added.filter((f) => f.required).length;
  const requiredRemoved = diff.removed.filter((f) => f.required).length;
  const requiredFlipped = diff.required_changed.filter((r) => r.after && !r.before).length;
  const warn = requiredAdded + requiredRemoved + requiredFlipped > 0;
  return (
    <div className="panel">
      <div className="panel-header">
        <h3 className="row">
          {fresh ? "Changes from this refresh" : "Changes from the last refresh"}
          {warn && (
            <Badge color="amber" title="Required fields were added or removed; check the mapping gaps">
              required fields changed
            </Badge>
          )}
        </h3>
        {fresh && (
          <button className="small" onClick={onDismiss}>
            Dismiss
          </button>
        )}
      </div>
      <div className="panel-body">
        {!diffHasChanges(diff) ? (
          <span className="muted">No differences against the previously loaded schema.</span>
        ) : (
          <div className="cards">
            <DiffCard title={`Added (${diff.added.length})`}>
              {diff.added.map((f) => (
                <li key={f.name}>
                  <span className="mono">{f.name}</span> {f.required && <Badge color="red">required</Badge>}
                </li>
              ))}
            </DiffCard>
            <DiffCard title={`Removed (${diff.removed.length})`}>
              {diff.removed.map((f) => (
                <li key={f.name}>
                  <span className="mono">{f.name}</span> {f.required && <Badge color="amber">was required</Badge>}
                </li>
              ))}
            </DiffCard>
            <DiffCard title={`Required changed (${diff.required_changed.length})`}>
              {diff.required_changed.map((r) => (
                <li key={r.name}>
                  <span className="mono">{r.name}</span> {r.before ? "required" : "optional"} to <b>{r.after ? "required" : "optional"}</b>
                </li>
              ))}
            </DiffCard>
            <DiffCard title={`Enum changed (${diff.enum_changed.length})`}>
              {diff.enum_changed.map((r) => (
                <li key={r.name}>
                  <span className="mono">{r.name}</span>
                  {r.added.length > 0 && (
                    <div className="small">
                      <span className="diff-new">+ {r.added.join(", ")}</span>
                    </div>
                  )}
                  {r.removed.length > 0 && (
                    <div className="small">
                      <span className="diff-old">{r.removed.join(", ")}</span>
                    </div>
                  )}
                </li>
              ))}
            </DiffCard>
          </div>
        )}
      </div>
    </div>
  );
}

function DiffCard({ title, children }: { title: string; children: ReactNode[] }) {
  return (
    <div className="card">
      <div className="card-title">{title}</div>
      {children.length === 0 ? <span className="faint small">none</span> : <ul className="diff-list">{children}</ul>}
    </div>
  );
}
