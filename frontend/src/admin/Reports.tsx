// IMP-11 ERP defects report and GOV-07 attribute usage report with a Deprecate action.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useGroups } from "../api/hooks";
import type { AttributeUsageRow } from "../api/types";
import { Badge, Confirm, Empty, ErrorBox, PercentPill, Spinner, useToast } from "../components/Common";
import { formatDate } from "../lib/format";

export function ErpDefectsTab() {
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ["admin", "erp-defects", page], queryFn: () => api.admin.erpDefects(page) });
  if (q.isLoading) return <Spinner label="Loading ERP defects" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load the ERP defects report" />;
  const d = q.data!;
  const pageSize = d.page_size ?? Math.max(1, d.rows.length);
  const pageCount = Math.max(1, Math.ceil(d.total / pageSize));
  // Columns beyond the known ones are shown as they come so the report can grow without a UI change.
  const known = new Set(["id", "entity_id", "style_number", "color_code", "attribute_code", "raw_value", "issue", "seen_at"]);
  const extra = Array.from(new Set(d.rows.flatMap((r) => Object.keys(r).filter((k) => !known.has(k)))));
  return (
    <div>
      <p className="muted small">
        ERP values that could not be mapped to a clean option, or that failed normalization. Fix them in BlueCherry; the next ingest clears the row.
      </p>
      {d.rows.length === 0 ? (
        <Empty title="No ERP defects">Every Style Master value mapped cleanly on the last ingest.</Empty>
      ) : (
        <div className="panel">
          <table className="data compact">
            <thead>
              <tr>
                <th>Style</th>
                <th>Color</th>
                <th>Attribute</th>
                <th>Raw ERP value</th>
                <th>Issue</th>
                <th>Seen</th>
                {extra.map((k) => (
                  <th key={k}>{k}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r, i) => (
                <tr key={r.id ?? i}>
                  <td className="mono">
                    {r.entity_id ? <Link to={`/products/${encodeURIComponent(r.entity_id)}`}>{r.style_number ?? r.entity_id}</Link> : (r.style_number ?? "")}
                  </td>
                  <td className="mono">{r.color_code ?? ""}</td>
                  <td className="mono">{r.attribute_code}</td>
                  <td className="mono">{r.raw_value ?? <span className="faint">(empty)</span>}</td>
                  <td>{r.issue}</td>
                  <td className="nowrap">{r.seen_at ? formatDate(r.seen_at) : ""}</td>
                  {extra.map((k) => (
                    <td key={k}>{String(r[k] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="grid-status">
            <span>{d.total} defects</span>
            <span className="row">
              <button className="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </button>
              <span>
                Page {page} of {pageCount}
              </span>
              <button className="small" disabled={page >= pageCount} onClick={() => setPage((p) => p + 1)}>
                Next
              </button>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

export function AttributeUsageTab() {
  const q = useQuery({ queryKey: ["admin", "attribute-usage"], queryFn: api.admin.attributeUsage });
  const groups = useGroups();
  const qc = useQueryClient();
  const toast = useToast();
  const [sortKey, setSortKey] = useState<"fill_rate" | "label" | "group_code">("fill_rate");
  const [toDeprecate, setToDeprecate] = useState<AttributeUsageRow | null>(null);

  const deprecate = useMutation({
    mutationFn: (code: string) => api.metadata.updateAttribute(code, { status: "deprecated" }),
    onSuccess: () => {
      toast("Attribute deprecated. It stays readable but can no longer be edited.", "ok");
      setToDeprecate(null);
      qc.invalidateQueries({ queryKey: ["metadata"] });
      qc.invalidateQueries({ queryKey: ["admin", "attribute-usage"] });
    },
    onError: (e) => toast(`Could not deprecate: ${(e as Error).message}`, "error"),
  });

  const rows = useMemo(() => {
    const r = (q.data ?? []).slice();
    r.sort((a, b) =>
      sortKey === "fill_rate" ? a.fill_rate - b.fill_rate : sortKey === "label" ? a.label.localeCompare(b.label) : a.group_code.localeCompare(b.group_code),
    );
    return r;
  }, [q.data, sortKey]);

  if (q.isLoading) return <Spinner label="Loading attribute usage" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load the attribute usage report" />;
  const groupLabel = (code: string) => groups.data?.find((g) => g.code === code)?.label ?? code;

  return (
    <div>
      <div className="row mb8" style={{ justifyContent: "space-between" }}>
        <span className="muted small">
          Fill rate per attribute across the catalog. Attributes that are empty everywhere are candidates to deprecate (the sample Image Relay
          export had 134 such columns).
        </span>
        <label className="inline">
          Sort by
          <select value={sortKey} onChange={(e) => setSortKey(e.target.value as typeof sortKey)}>
            <option value="fill_rate">fill rate (lowest first)</option>
            <option value="label">label</option>
            <option value="group_code">group</option>
          </select>
        </label>
      </div>
      {rows.length === 0 ? (
        <Empty title="No usage data">The report fills in after the first ingest.</Empty>
      ) : (
        <div className="panel">
          <table className="data compact">
            <thead>
              <tr>
                <th>Attribute</th>
                <th>Group</th>
                <th>Level</th>
                <th>Status</th>
                <th className="right">Filled</th>
                <th className="right">Total</th>
                <th>Fill rate</th>
                <th className="right">Distinct</th>
                <th>Used by channels</th>
                <th>Last set</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.code}>
                  <td>
                    {r.label}
                    <div className="faint mono small">{r.code}</div>
                  </td>
                  <td>{groupLabel(r.group_code)}</td>
                  <td className="mono">{r.level}</td>
                  <td>
                    <Badge color={r.status === "confirmed" ? "green" : r.status === "deprecated" ? "red" : "amber"}>{r.status}</Badge>
                  </td>
                  <td className="num">{r.filled}</td>
                  <td className="num">{r.total}</td>
                  <td>
                    <PercentPill value={r.fill_rate <= 1 ? r.fill_rate * 100 : r.fill_rate} />
                  </td>
                  <td className="num">{r.distinct_values ?? ""}</td>
                  <td>
                    <div className="chips">
                      {(r.used_by_channels ?? []).map((c) => (
                        <span key={c} className="badge">
                          {c}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="nowrap">{r.last_set_at ? formatDate(r.last_set_at) : ""}</td>
                  <td>
                    {r.status !== "deprecated" && (
                      <button className="small danger" onClick={() => setToDeprecate(r)}>
                        Deprecate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {toDeprecate && (
        <Confirm
          title={`Deprecate ${toDeprecate.label}?`}
          message={
            <p>
              The attribute <b className="mono">{toDeprecate.code}</b> will be marked deprecated. Existing values stay readable and exportable,
              but no one can edit it and it leaves the default column and form lists. {toDeprecate.filled} of {toDeprecate.total} products have a value.
            </p>
          }
          confirmLabel="Deprecate"
          busy={deprecate.isPending}
          onCancel={() => setToDeprecate(null)}
          onConfirm={() => deprecate.mutate(toDeprecate.code)}
        />
      )}
    </div>
  );
}
