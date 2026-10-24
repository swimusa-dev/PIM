// IMP-05 matching: run, rows with match status (matched with the key used, new, ambiguous, unmatched),
// candidate lists with Confirm, per-row action (create / update / skip) subject to the unmatched policy,
// keyless mode showing the extracted name.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ImportBatch, ImportRow, MatchStatus, RowAction } from "../api/types";
import { Badge, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { coreKeysForLevel, shortValue } from "./shared";

const PAGE_SIZE = 50;

export function MatchPill({ row }: { row: ImportRow }) {
  const s = row.match_status;
  const color = s === "matched" ? "green" : s === "new" ? "blue" : s === "ambiguous" ? "amber" : "red";
  return (
    <Badge color={color} title={row.match_key_used ? `Matched by ${row.match_key_used}` : undefined}>
      {s}
      {s === "matched" && row.match_key_used ? ` (${row.match_key_used})` : ""}
    </Badge>
  );
}

export function MatchStep({
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
  const [filter, setFilter] = useState<MatchStatus | "">("");
  const [page, setPage] = useState(1);
  const matched = !["uploaded", "mapped", "validated"].includes(batch.status);
  const keylessCol = batch.options?.keyless_name_column ?? null;
  const policy = batch.options?.unmatched_policy ?? "update_only";

  const run = useMutation({
    mutationFn: () => api.imports.match(batch.id),
    onSuccess: (b) => {
      onBatch(b);
      qc.invalidateQueries({ queryKey: ["imports", "rows", batch.id] });
      const s = b.stats;
      toast(`Matching finished: ${s.matched} matched, ${s.new} new, ${s.ambiguous} ambiguous, ${s.unmatched} unmatched.`, s.ambiguous + s.unmatched ? "warn" : "ok");
    },
  });

  const rows = useQuery({
    queryKey: ["imports", "rows", batch.id, "match", filter, page],
    queryFn: () => api.imports.rows(batch.id, { match: filter || undefined, page, page_size: PAGE_SIZE }),
    enabled: matched,
  });

  const updateRow = useMutation({
    mutationFn: ({ rowId, body }: { rowId: string; body: { entity_id?: string | null; action?: RowAction } }) => api.imports.updateRow(batch.id, rowId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["imports", "rows", batch.id] });
      qc.invalidateQueries({ queryKey: ["imports", "batch", batch.id] });
    },
    onError: (e) => toast(`Could not update the row: ${(e as Error).message}`, "error"),
  });

  const keyCols = useMemo(() => {
    const mappedTargets = new Set(batch.mapping.filter((m) => !m.skip).map((m) => m.target));
    return coreKeysForLevel(batch.level).filter((k) => mappedTargets.has(k.key));
  }, [batch.mapping, batch.level]);

  const stats = batch.stats;
  const total = rows.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const blocking = stats.ambiguous > 0;

  return (
    <div className="stack gap16">
      {keylessCol && (
        <div className="banner info">
          Keyless mode: rows are matched by the name in column <b className="mono">{keylessCol}</b>. Confirm the right candidate for each ambiguous or unmatched row.
        </div>
      )}
      <div className="row">
        <button className="primary" disabled={run.isPending} onClick={() => run.mutate()}>
          {run.isPending ? "Matching" : matched ? "Run matching again" : "Run matching"}
        </button>
        <span className="muted small">
          Match keys: <span className="mono">{batch.match_keys.join(", ") || "none"}</span>, unmatched policy: {policy.replace(/_/g, " ")}
        </span>
      </div>
      {run.isError && <ErrorBox error={run.error} title="Matching failed" />}
      {!matched && !run.isPending && <Empty title="Not matched yet">Run matching to find the existing product for each row.</Empty>}

      {matched && (
        <>
          <div className="cards">
            {(
              [
                ["matched", stats.matched, "green"],
                ["new", stats.new, "blue"],
                ["ambiguous", stats.ambiguous, "amber"],
                ["unmatched", stats.unmatched, "red"],
              ] as [MatchStatus, number, string][]
            ).map(([k, n, color]) => (
              <div key={k} className="card" style={{ cursor: "pointer", outline: filter === k ? "2px solid var(--teal)" : undefined }} onClick={() => { setFilter(filter === k ? "" : k); setPage(1); }}>
                <div className="card-title">{k}</div>
                <div className="card-value" style={{ color: `var(--${color})` }}>
                  {n}
                </div>
              </div>
            ))}
          </div>
          <div className="row">
            <select value={filter} onChange={(e) => { setFilter(e.target.value as MatchStatus | ""); setPage(1); }}>
              <option value="">All rows</option>
              <option value="matched">Matched</option>
              <option value="new">New</option>
              <option value="ambiguous">Ambiguous</option>
              <option value="unmatched">Unmatched</option>
            </select>
            <span className="faint small">{total} rows</span>
          </div>

          {rows.isLoading && <Spinner label="Loading rows" />}
          {rows.isError && <ErrorBox error={rows.error} title="Could not load rows" />}
          {rows.data && rows.data.rows.length === 0 && <Empty title="No rows match this filter" />}
          {rows.data && rows.data.rows.length > 0 && (
            <div className="panel" style={{ overflow: "auto" }}>
              <table className="data compact">
                <thead>
                  <tr>
                    <th>#</th>
                    {keyCols.map((k) => (
                      <th key={k.key}>{k.label}</th>
                    ))}
                    {keylessCol && <th>Extracted name</th>}
                    <th>Match</th>
                    <th>Product</th>
                    <th>Candidates</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.data.rows.map((r) => {
                    const needsHelp = r.match_status === "ambiguous" || r.match_status === "unmatched";
                    const canCreate = policy !== "update_only";
                    return (
                      <tr key={r.id}>
                        <td className="num nowrap">
                          {batch.files.length > 1 && <span className="faint">{r.file_index}:</span>}
                          {r.row_number}
                        </td>
                        {keyCols.map((k) => (
                          <td key={k.key} className="mono">
                            {shortValue(r.mapped[k.key], 30)}
                          </td>
                        ))}
                        {keylessCol && <td>{r.raw[keylessCol] ?? shortValue(r.mapped.name)}</td>}
                        <td>
                          <MatchPill row={r} />
                        </td>
                        <td>
                          {r.entity_id ? (
                            <Link to={`/products/${encodeURIComponent(r.entity_id)}`}>{r.entity_label ?? r.entity_id}</Link>
                          ) : (
                            <span className="faint">none</span>
                          )}
                        </td>
                        <td>
                          {needsHelp && r.candidates.length > 0 && (
                            <div className="stack" style={{ gap: 2 }}>
                              {r.candidates.map((c) => (
                                <div key={c.entity_id} className="row" style={{ gap: 6 }}>
                                  <span>{c.label}</span>
                                  <Badge title={c.reason}>{Math.round(c.score * 100)}%</Badge>
                                  <span className="faint small">{c.reason}</span>
                                  <button
                                    className="small primary"
                                    disabled={updateRow.isPending}
                                    onClick={() => updateRow.mutate({ rowId: r.id, body: { entity_id: c.entity_id, action: "update" } })}
                                  >
                                    Confirm
                                  </button>
                                </div>
                              ))}
                            </div>
                          )}
                          {needsHelp && r.candidates.length === 0 && <span className="faint small">no candidates</span>}
                          {r.match_status === "matched" && r.entity_id && (
                            <button className="small link" onClick={() => updateRow.mutate({ rowId: r.id, body: { entity_id: null } })}>
                              Unlink
                            </button>
                          )}
                        </td>
                        <td>
                          <select
                            value={r.action}
                            disabled={updateRow.isPending}
                            onChange={(e) => updateRow.mutate({ rowId: r.id, body: { action: e.target.value as RowAction } })}
                          >
                            <option value="update" disabled={!r.entity_id}>
                              update
                            </option>
                            <option value="create" disabled={!canCreate}>
                              create{canCreate ? "" : " (policy)"}
                            </option>
                            <option value="skip">skip</option>
                          </select>
                        </td>
                      </tr>
                    );
                  })}
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
        <div className="row">
          {blocking && <span className="muted small">Resolve ambiguous rows (confirm a candidate or skip) before reviewing.</span>}
          <button className="primary" disabled={!matched} onClick={onNext}>
            Next: Review
          </button>
        </div>
      </div>
    </div>
  );
}
