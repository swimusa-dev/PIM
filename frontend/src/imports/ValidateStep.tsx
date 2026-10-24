// IMP-04 validation: run, summary (rows OK / warnings / errors by type), problem-row filter, error grid
// with inline errors, error file download, per-import on-error choice (skip row or skip value).

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ImportBatch, ImportRow, OnErrorPolicy } from "../api/types";
import { Badge, Empty, ErrorBox, Spinner, useToast } from "../components/Common";

const PAGE_SIZE = 50;
type RowFilter = "" | "error" | "warning" | "ok";

export function ValidateStep({
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
  const toast = useToast();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<RowFilter>("");
  const [page, setPage] = useState(1);
  const validated = batch.status !== "uploaded" && batch.status !== "mapped";

  const validate = useMutation({
    mutationFn: () => api.imports.validate(batch.id),
    onSuccess: (b) => {
      onBatch(b);
      qc.invalidateQueries({ queryKey: ["imports", "rows", batch.id] });
      toast(`Validation finished: ${b.stats.errors} error${b.stats.errors === 1 ? "" : "s"}, ${b.stats.warnings} warning${b.stats.warnings === 1 ? "" : "s"}.`, b.stats.errors ? "warn" : "ok");
    },
  });

  const policy = useMutation({
    mutationFn: (on_error: OnErrorPolicy) =>
      api.imports.saveMapping(batch.id, {
        mapping: batch.mapping,
        match_keys: batch.match_keys,
        options: { ...batch.options, on_error },
        template_id: batch.template_id ?? undefined,
      }),
    onSuccess: (b) => {
      onBatch(b);
      toast("On-error policy saved. Run validation again to apply it.", "ok");
    },
    onError: (e) => toast(`Could not save the policy: ${(e as Error).message}`, "error"),
  });

  const rows = useQuery({
    queryKey: ["imports", "rows", batch.id, "validate", filter, page],
    queryFn: () => api.imports.rows(batch.id, { status: filter || undefined, page, page_size: PAGE_SIZE }),
    enabled: validated,
  });

  const stats = batch.stats;
  const byType = useMemo(() => {
    const fromReport = batch.report?.errors_by_type as Record<string, number> | { type: string; count: number }[] | undefined;
    if (Array.isArray(fromReport)) return fromReport.map((e) => ({ type: e.type, count: e.count }));
    if (fromReport && typeof fromReport === "object") return Object.entries(fromReport).map(([type, count]) => ({ type, count: Number(count) }));
    const m = new Map<string, number>();
    for (const r of rows.data?.rows ?? []) for (const e of r.errors) m.set(e.message, (m.get(e.message) ?? 0) + 1);
    return Array.from(m.entries())
      .map(([type, count]) => ({ type, count }))
      .sort((a, b) => b.count - a.count);
  }, [batch.report, rows.data]);

  const columns = useMemo(() => {
    const seen = new Set<string>();
    for (const f of batch.files) for (const c of f.columns) seen.add(c.name);
    for (const r of rows.data?.rows ?? []) for (const k of Object.keys(r.raw)) seen.add(k);
    return Array.from(seen);
  }, [batch.files, rows.data]);

  const total = rows.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="stack gap16">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          <button className="primary" disabled={validate.isPending} onClick={() => validate.mutate()}>
            {validate.isPending ? "Validating" : validated ? "Run validation again" : "Run validation"}
          </button>
          <label className="inline">
            On error
            <select value={batch.options?.on_error ?? "skip_row"} disabled={policy.isPending} onChange={(e) => policy.mutate(e.target.value as OnErrorPolicy)}>
              <option value="skip_row">skip the whole row</option>
              <option value="skip_value">skip only the bad value</option>
            </select>
          </label>
        </div>
        {validated && (
          <a className="btn" href={api.imports.errorFileUrl(batch.id)} download>
            Download error file
          </a>
        )}
      </div>
      {validate.isError && <ErrorBox error={validate.error} title="Validation failed" />}

      {!validated && !validate.isPending && (
        <Empty title="Not validated yet">Run validation to check every mapped value against its attribute definition and option list.</Empty>
      )}

      {validated && (
        <>
          <div className="cards">
            <div className="card">
              <div className="card-title">Rows</div>
              <div className="card-value">{stats.rows}</div>
            </div>
            <div className="card">
              <div className="card-title">OK</div>
              <div className="card-value" style={{ color: "var(--green)" }}>
                {stats.ok}
              </div>
            </div>
            <div className="card">
              <div className="card-title">Warnings</div>
              <div className="card-value" style={{ color: "var(--amber)" }}>
                {stats.warnings}
              </div>
            </div>
            <div className="card">
              <div className="card-title">Errors</div>
              <div className={`card-value${stats.errors ? " alert" : ""}`}>{stats.errors}</div>
            </div>
          </div>

          {byType.length > 0 && (
            <div className="panel" style={{ maxWidth: 560 }}>
              <div className="panel-header">
                <h3>Errors by type</h3>
              </div>
              <table className="data compact">
                <tbody>
                  {byType.map((e) => (
                    <tr key={e.type}>
                      <td>{e.type}</td>
                      <td className="num">{e.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="row">
            <label className="inline">
              <input type="checkbox" checked={filter === "error"} onChange={(e) => { setFilter(e.target.checked ? "error" : ""); setPage(1); }} />
              Show only problem rows
            </label>
            <select value={filter} onChange={(e) => { setFilter(e.target.value as RowFilter); setPage(1); }}>
              <option value="">All rows</option>
              <option value="error">Rows with errors</option>
              <option value="warning">Rows with warnings</option>
              <option value="ok">OK rows</option>
            </select>
            <span className="faint small">{total} rows</span>
          </div>

          {rows.isLoading && <Spinner label="Loading rows" />}
          {rows.isError && <ErrorBox error={rows.error} title="Could not load rows" />}
          {rows.data && rows.data.rows.length === 0 && <Empty title="No rows match this filter" />}
          {rows.data && rows.data.rows.length > 0 && (
            <div className="panel" style={{ overflow: "auto" }}>
              <table className="data compact" style={{ minWidth: 700 }}>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Status</th>
                    {columns.map((c) => (
                      <th key={c} className="mono">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.data.rows.map((r) => (
                    <ErrorGridRow key={r.id} row={r} columns={columns} multiFile={batch.files.length > 1} />
                  ))}
                </tbody>
              </table>
              <div className="row" style={{ justifyContent: "flex-end", padding: 8 }}>
                <button className="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </button>
                <span className="muted small">
                  Page {page} of {pageCount}
                </span>
                <button className="small" disabled={page >= pageCount} onClick={() => setPage((p) => p + 1)}>
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}

      <div className="wizard-footer">
        <button onClick={onBack}>Back</button>
        <button className="primary" disabled={!validated} onClick={onNext}>
          Next: Match
        </button>
      </div>
    </div>
  );
}

function ErrorGridRow({ row, columns, multiFile }: { row: ImportRow; columns: string[]; multiFile: boolean }) {
  const errCols = new Map<string, string[]>();
  const warnCols = new Map<string, string[]>();
  const rowLevelErrors: string[] = [];
  const rowLevelWarnings: string[] = [];
  for (const e of row.errors) {
    if (e.column) errCols.set(e.column, [...(errCols.get(e.column) ?? []), e.message]);
    else rowLevelErrors.push(`${e.attribute ? `${e.attribute}: ` : ""}${e.message}`);
  }
  for (const w of row.warnings) {
    if (w.column) warnCols.set(w.column, [...(warnCols.get(w.column) ?? []), w.message]);
    else rowLevelWarnings.push(`${w.attribute ? `${w.attribute}: ` : ""}${w.message}`);
  }
  const status = row.errors.length ? "error" : row.warnings.length ? "warning" : "ok";
  return (
    <tr>
      <td className="num nowrap">
        {multiFile && <span className="faint">{row.file_index}:</span>}
        {row.row_number}
      </td>
      <td>
        <Badge color={status === "error" ? "red" : status === "warning" ? "amber" : "green"}>{status}</Badge>
        {rowLevelErrors.map((m, i) => (
          <span className="issue" key={`e${i}`}>
            {m}
          </span>
        ))}
        {rowLevelWarnings.map((m, i) => (
          <span className="issue warn" key={`w${i}`}>
            {m}
          </span>
        ))}
      </td>
      {columns.map((c) => {
        const errs = errCols.get(c);
        const warns = warnCols.get(c);
        return (
          <td key={c} style={errs ? { background: "var(--red-bg)" } : warns ? { background: "var(--amber-bg)" } : undefined}>
            {row.raw[c] ?? ""}
            {errs?.map((m, i) => (
              <span className="issue" key={`e${i}`}>
                {m}
              </span>
            ))}
            {warns?.map((m, i) => (
              <span className="issue warn" key={`w${i}`}>
                {m}
              </span>
            ))}
          </td>
        );
      })}
    </tr>
  );
}
