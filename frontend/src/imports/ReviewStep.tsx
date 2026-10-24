// IMP-06 survivorship and conflicts, IMP-07 review, commit, report and rollback.
// Diff summary tabs (creates, adds, changes, conflicts, skipped), conflict decisions (accept / reject / edit,
// single and bulk), commit with polling, report, rollback with the manual follow-up list.

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAttributes } from "../api/hooks";
import type { ImportBatch, ImportConflict, ImportDiff } from "../api/types";
import { Badge, Confirm, Dialog, Empty, ErrorBox, Spinner, Tabs, useToast } from "../components/Common";
import { formatDate } from "../lib/format";
import { BatchStatusBadge, RollbackResultDialog, useRollback } from "../pages/Imports";
import { shortValue } from "./shared";

type DiffTab = "creates" | "adds" | "changes" | "conflicts" | "skipped";

export function ReviewStep({
  batch,
  onBatch,
  onBack,
}: {
  batch: ImportBatch;
  onBatch: (b: ImportBatch) => void;
  onBack: () => void;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const attrs = useAttributes();
  const attrLabel = (code: string) => attrs.data?.find((a) => a.code === code)?.label ?? code;
  const [diff, setDiff] = useState<ImportDiff | null>(batch.diff ?? null);
  const [tab, setTab] = useState<DiffTab>("changes");
  const [confirmCommit, setConfirmCommit] = useState(false);
  const [confirmRollback, setConfirmRollback] = useState(false);

  const reviewed = !["uploaded", "mapped", "validated", "matched"].includes(batch.status);
  const committed = batch.status === "committed";
  const committing = batch.status === "committing";
  const finished = committed || batch.status === "failed" || batch.status === "rolled_back";

  useEffect(() => {
    if (batch.diff) setDiff(batch.diff);
  }, [batch.diff]);

  const review = useMutation({
    mutationFn: () => api.imports.review(batch.id),
    onSuccess: (b) => {
      onBatch(b);
      setDiff(b.diff ?? null);
      qc.invalidateQueries({ queryKey: ["imports", "conflicts", batch.id] });
      toast("Review computed.", "ok");
    },
  });

  const commit = useMutation({
    mutationFn: () => api.imports.commit(batch.id),
    onSuccess: (b) => {
      onBatch(b);
      setConfirmCommit(false);
      qc.invalidateQueries({ queryKey: ["imports", "batches"] });
      toast(b.status === "committed" ? "Import committed." : "Commit queued. This page refreshes until it finishes.", "ok");
    },
  });

  const report = useQuery({
    queryKey: ["imports", "report", batch.id],
    queryFn: () => api.imports.report(batch.id),
    enabled: committed || batch.status === "rolled_back",
  });

  const rollback = useRollback(() => setConfirmRollback(false));
  useEffect(() => {
    if (rollback.isSuccess) qc.invalidateQueries({ queryKey: ["imports", "batch", batch.id] });
  }, [rollback.isSuccess, qc, batch.id]);

  const stats = batch.stats;
  const conflictsOpen = stats.conflicts;

  return (
    <div className="stack gap16">
      {!finished && !committing && (
        <div className="row">
          <button className="primary" disabled={review.isPending} onClick={() => review.mutate()}>
            {review.isPending ? "Computing" : reviewed ? "Run review again" : "Run review"}
          </button>
          <span className="muted small">Computes the diff against current values with survivorship rules (IMP-06).</span>
        </div>
      )}
      {review.isError && <ErrorBox error={review.error} title="Review failed" />}
      {!reviewed && !review.isPending && <Empty title="Not reviewed yet">Run review to see what the import will create and change.</Empty>}

      {committing && (
        <div className="banner warn boxed">
          <Spinner label="Committing the batch. This page refreshes automatically." />
        </div>
      )}
      {batch.status === "failed" && (
        <ErrorBox error={batch.error ?? "The commit failed."} title="Commit failed" />
      )}
      {batch.status === "rolled_back" && <div className="banner info">This batch was rolled back.</div>}

      {reviewed && (
        <>
          <div className="cards">
            <div className="card">
              <div className="card-title">Products to create</div>
              <div className="card-value">{stats.creates}</div>
            </div>
            <div className="card">
              <div className="card-title">Values to add</div>
              <div className="card-value">{stats.adds}</div>
            </div>
            <div className="card">
              <div className="card-title">Values to change</div>
              <div className="card-value">{stats.changes}</div>
            </div>
            <div className="card">
              <div className="card-title">Conflicts held</div>
              <div className={`card-value${conflictsOpen ? " alert" : ""}`}>{conflictsOpen}</div>
            </div>
            <div className="card">
              <div className="card-title">Rows skipped</div>
              <div className="card-value">{stats.skipped}</div>
            </div>
          </div>

          {Object.keys(stats.placeholders_removed ?? {}).length > 0 && (
            <div className="banner info">
              Placeholders removed:{" "}
              {Object.entries(stats.placeholders_removed)
                .map(([k, v]) => `${attrLabel(k)} (${v})`)
                .join(", ")}
            </div>
          )}

          <Tabs<DiffTab>
            value={tab}
            onChange={setTab}
            tabs={[
              { key: "changes", label: "Changes", count: stats.changes },
              { key: "adds", label: "Adds", count: stats.adds },
              { key: "creates", label: "Creates", count: stats.creates },
              { key: "conflicts", label: "Conflicts", count: conflictsOpen },
              { key: "skipped", label: "Skipped", count: stats.skipped },
            ]}
          />
          {tab === "changes" && <ChangesTable rows={diff?.changes ?? []} attrLabel={attrLabel} hasDiff={!!diff} />}
          {tab === "adds" && <GenericTable rows={diff?.adds ?? []} attrLabel={attrLabel} hasDiff={!!diff} empty="No values to add" />}
          {tab === "creates" && <GenericTable rows={diff?.creates ?? []} attrLabel={attrLabel} hasDiff={!!diff} empty="No products to create" />}
          {tab === "skipped" && <GenericTable rows={diff?.skipped ?? []} attrLabel={attrLabel} hasDiff={!!diff} empty="No rows skipped" />}
          {tab === "conflicts" && <ConflictsTab batch={batch} attrLabel={attrLabel} readOnly={finished || committing} />}
        </>
      )}

      {(committed || batch.status === "rolled_back") && (
        <div className="panel">
          <div className="panel-header">
            <h3>Report</h3>
            <div className="row">
              <BatchStatusBadge status={batch.status} />
              {batch.change_set_id && <span className="faint small mono">change set {batch.change_set_id}</span>}
            </div>
          </div>
          <div className="panel-body">
            {report.isLoading && <Spinner />}
            {report.isError && <ErrorBox error={report.error} title="Could not load the report" />}
            {report.data && <ReportView report={report.data} attrLabel={attrLabel} />}
            <div className="row mt8">
              <Link to="/imports" className="btn">
                Back to import history
              </Link>
              {committed && (
                <button className="danger" onClick={() => setConfirmRollback(true)}>
                  Rollback this import
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="wizard-footer">
        <button onClick={onBack} disabled={committing}>
          Back
        </button>
        {!finished && !committing && (
          <div className="row">
            {conflictsOpen > 0 && <span className="muted small">{conflictsOpen} conflict{conflictsOpen === 1 ? "" : "s"} still held; they stay unchanged unless accepted.</span>}
            <button className="primary" disabled={!reviewed || commit.isPending} onClick={() => setConfirmCommit(true)}>
              Commit
            </button>
          </div>
        )}
      </div>
      {commit.isError && <ErrorBox error={commit.error} title="Could not commit" />}

      {confirmCommit && (
        <Confirm
          title="Commit this import?"
          message={
            <div className="stack">
              <div>
                {stats.creates} product{stats.creates === 1 ? "" : "s"} created, {stats.adds + stats.changes} value{stats.adds + stats.changes === 1 ? "" : "s"} written,{" "}
                {stats.skipped} row{stats.skipped === 1 ? "" : "s"} skipped.
              </div>
              {conflictsOpen > 0 && <div className="muted small">{conflictsOpen} held conflict{conflictsOpen === 1 ? "" : "s"} will keep the current value.</div>}
              <div className="muted small">The batch can be rolled back afterwards from the import history.</div>
            </div>
          }
          confirmLabel="Commit"
          busy={commit.isPending}
          onCancel={() => setConfirmCommit(false)}
          onConfirm={() => commit.mutate()}
        />
      )}
      {confirmRollback && (
        <Confirm
          title="Roll back this import?"
          message="Every value this batch set is restored. Values edited again after the import are listed for manual review."
          confirmLabel="Roll back"
          busy={rollback.isPending}
          onCancel={() => setConfirmRollback(false)}
          onConfirm={() => rollback.mutate(batch.id)}
        />
      )}
      {rollback.result && <RollbackResultDialog result={rollback.result} onClose={rollback.clearResult} />}
    </div>
  );
}

function ChangesTable({ rows, attrLabel, hasDiff }: { rows: ImportDiff["changes"]; attrLabel: (c: string) => string; hasDiff: boolean }) {
  if (!hasDiff) return <Empty title="Run review to list the changes" />;
  if (rows.length === 0) return <Empty title="No values change" />;
  return (
    <div className="panel">
      <table className="data compact">
        <thead>
          <tr>
            <th>Product</th>
            <th>Attribute</th>
            <th>Current</th>
            <th>Incoming</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c, i) => (
            <tr key={`${c.entity_id}-${c.attribute_code}-${i}`}>
              <td>
                <Link to={`/products/${encodeURIComponent(c.entity_id)}`}>{c.label}</Link>
              </td>
              <td>{attrLabel(c.attribute_code)}</td>
              <td className="diff-old">{shortValue(c.old, 80) || <span className="faint">empty</span>}</td>
              <td className="diff-new">{shortValue(c.new, 80)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="faint small" style={{ padding: 8 }}>
        First {rows.length} shown.
      </div>
    </div>
  );
}

/** Creates, adds and skipped rows: the contract fixes only that they exist, so the columns come from the data. */
function GenericTable({ rows, attrLabel, hasDiff, empty }: { rows: Record<string, unknown>[]; attrLabel: (c: string) => string; hasDiff: boolean; empty: string }) {
  const columns = useMemo(() => {
    const seen = new Set<string>();
    for (const r of rows) for (const k of Object.keys(r)) seen.add(k);
    const order = ["row_number", "file", "entity_id", "label", "attribute_code", "old", "new", "value", "reason", "level", "style_number", "color_code", "size", "sku", "upc"];
    return Array.from(seen).sort((a, b) => (order.indexOf(a) === -1 ? 99 : order.indexOf(a)) - (order.indexOf(b) === -1 ? 99 : order.indexOf(b)));
  }, [rows]);
  if (!hasDiff) return <Empty title="Run review to list these rows" />;
  if (rows.length === 0) return <Empty title={empty} />;
  return (
    <div className="panel" style={{ overflow: "auto" }}>
      <table className="data compact">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c.replace(/_/g, " ")}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => {
                const v = r[c];
                if (c === "attribute_code" && typeof v === "string") return <td key={c}>{attrLabel(v)}</td>;
                if (c === "entity_id" && typeof v === "string")
                  return (
                    <td key={c}>
                      <Link to={`/products/${encodeURIComponent(v)}`}>{String(r.label ?? v)}</Link>
                    </td>
                  );
                if (c === "label" && typeof r.entity_id === "string") return <td key={c} className="faint small">{String(v ?? "")}</td>;
                return <td key={c}>{shortValue(v, 80)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="faint small" style={{ padding: 8 }}>
        First {rows.length} shown.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Conflicts (IMP-06)
// ---------------------------------------------------------------------------------------------

function ConflictsTab({ batch, attrLabel, readOnly }: { batch: ImportBatch; attrLabel: (c: string) => string; readOnly: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [status, setStatus] = useState("open");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<ImportConflict | null>(null);
  const q = useQuery({ queryKey: ["imports", "conflicts", batch.id, status], queryFn: () => api.imports.conflicts(batch.id, status || undefined) });

  const decide = useMutation({
    mutationFn: ({ ids, decision, value }: { ids: string[]; decision: "accept" | "reject" | "edit"; value?: unknown }) => api.imports.decideConflicts(ids, decision, value),
    onSuccess: (_, v) => {
      toast(`${v.ids.length} conflict${v.ids.length === 1 ? "" : "s"} ${v.decision === "edit" ? "edited" : `${v.decision}ed`}.`, "ok");
      setSelected(new Set());
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["imports", "conflicts", batch.id] });
      qc.invalidateQueries({ queryKey: ["imports", "batch", batch.id] });
    },
    onError: (e) => toast(`Could not decide: ${(e as Error).message}`, "error"),
  });

  const rows = q.data?.rows ?? [];
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          <select value={status} onChange={(e) => { setStatus(e.target.value); setSelected(new Set()); }}>
            <option value="open">Open</option>
            <option value="accepted">Accepted</option>
            <option value="rejected">Rejected</option>
            <option value="edited">Edited</option>
            <option value="">All</option>
          </select>
          <span className="faint small">{q.data?.total ?? 0} conflicts</span>
        </div>
        {!readOnly && selected.size > 0 && (
          <div className="row">
            <span className="muted small">{selected.size} selected</span>
            <button className="small primary" disabled={decide.isPending} onClick={() => decide.mutate({ ids: Array.from(selected), decision: "accept" })}>
              Accept incoming
            </button>
            <button className="small" disabled={decide.isPending} onClick={() => decide.mutate({ ids: Array.from(selected), decision: "reject" })}>
              Keep current
            </button>
          </div>
        )}
      </div>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} title="Could not load conflicts" />}
      {q.data && rows.length === 0 && <Empty title={status === "open" ? "No open conflicts" : "No conflicts in this state"} />}
      {rows.length > 0 && (
        <div className="panel">
          <table className="data compact">
            <thead>
              <tr>
                {!readOnly && (
                  <th>
                    <input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map((r) => r.id)))} aria-label="Select all" />
                  </th>
                )}
                <th>Product</th>
                <th>Attribute</th>
                <th>Current</th>
                <th>Incoming</th>
                <th>Policy</th>
                <th>Status</th>
                {!readOnly && <th>Decide</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className={selected.has(c.id) ? "selected" : ""}>
                  {!readOnly && (
                    <td>
                      <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggle(c.id)} aria-label="Select conflict" />
                    </td>
                  )}
                  <td>
                    <Link to={`/products/${encodeURIComponent(c.entity_id)}`}>{c.entity_label}</Link>
                    {c.channel_code && <Badge>{c.channel_code}</Badge>}
                  </td>
                  <td>{attrLabel(c.attribute_code)}</td>
                  <td>
                    <div>{shortValue(c.current.value, 80) || <span className="faint">empty</span>}</div>
                    <div className="faint small">
                      {c.current.source_type}
                      {c.current.set_by ? `, ${c.current.set_by}` : ""}
                      {c.current.set_at ? `, ${formatDate(c.current.set_at)}` : ""}, {c.current.approval_state}
                    </div>
                  </td>
                  <td>
                    <div className="diff-new">{shortValue(c.incoming.value, 80) || <span className="faint">empty</span>}</div>
                    <div className="faint small">
                      {c.incoming.source}
                      {c.incoming.file ? `, ${c.incoming.file}` : ""}
                      {c.incoming.row_number !== undefined ? ` row ${c.incoming.row_number}` : ""}
                    </div>
                    {c.status === "edited" && c.resolved_value !== undefined && <div className="small">Resolved: {shortValue(c.resolved_value, 80)}</div>}
                  </td>
                  <td className="small">{c.policy.replace(/_/g, " ")}</td>
                  <td>
                    <Badge color={c.status === "open" ? "amber" : c.status === "accepted" ? "green" : c.status === "rejected" ? "red" : "blue"}>{c.status}</Badge>
                  </td>
                  {!readOnly && (
                    <td className="nowrap">
                      <button className="small primary" disabled={decide.isPending} onClick={() => decide.mutate({ ids: [c.id], decision: "accept" })}>
                        Accept
                      </button>{" "}
                      <button className="small" disabled={decide.isPending} onClick={() => decide.mutate({ ids: [c.id], decision: "reject" })}>
                        Reject
                      </button>{" "}
                      <button className="small" disabled={decide.isPending} onClick={() => setEditing(c)}>
                        Edit
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <EditConflictDialog
          conflict={editing}
          attrLabel={attrLabel}
          busy={decide.isPending}
          onClose={() => setEditing(null)}
          onSave={(v) => decide.mutate({ ids: [editing.id], decision: "edit", value: v })}
        />
      )}
    </div>
  );
}

function EditConflictDialog({
  conflict,
  attrLabel,
  busy,
  onClose,
  onSave,
}: {
  conflict: ImportConflict;
  attrLabel: (c: string) => string;
  busy: boolean;
  onClose: () => void;
  onSave: (v: unknown) => void;
}) {
  const initial = conflict.incoming.value;
  const [text, setText] = useState(typeof initial === "string" ? initial : initial === null || initial === undefined ? "" : JSON.stringify(initial));
  const parse = (): unknown => {
    const t = text.trim();
    if (t === "") return null;
    if (typeof initial === "number" && !Number.isNaN(Number(t))) return Number(t);
    if (typeof initial === "boolean") return /^(true|yes|1)$/i.test(t);
    if (Array.isArray(initial) || (typeof initial === "object" && initial !== null)) {
      try {
        return JSON.parse(t);
      } catch {
        return t;
      }
    }
    return t;
  };
  return (
    <Dialog
      title={`Edit value for ${attrLabel(conflict.attribute_code)}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy} onClick={() => onSave(parse())}>
            {busy ? "Saving" : "Save resolved value"}
          </button>
        </>
      }
    >
      <div className="stack">
        <div className="muted small">
          {conflict.entity_label}: current <b>{shortValue(conflict.current.value, 60) || "empty"}</b>, incoming <b>{shortValue(conflict.incoming.value, 60) || "empty"}</b>
        </div>
        <textarea value={text} onChange={(e) => setText(e.target.value)} autoFocus />
      </div>
    </Dialog>
  );
}

function ReportView({ report, attrLabel }: { report: Record<string, unknown>; attrLabel: (c: string) => string }) {
  const entries = Object.entries(report);
  if (entries.length === 0) return <div className="muted small">The report is empty.</div>;
  return (
    <dl className="kv">
      {entries.map(([k, v]) => (
        <ReportEntry key={k} name={k} value={v} attrLabel={attrLabel} />
      ))}
    </dl>
  );
}

function ReportEntry({ name, value, attrLabel }: { name: string; value: unknown; attrLabel: (c: string) => string }) {
  const label = name.replace(/_/g, " ");
  if (value === null || value === undefined) return null;
  if (typeof value !== "object") {
    return (
      <>
        <dt>{label}</dt>
        <dd>{String(value)}</dd>
      </>
    );
  }
  if (Array.isArray(value)) {
    return (
      <>
        <dt>{label}</dt>
        <dd>
          {value.length === 0 ? (
            <span className="faint">none</span>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {value.slice(0, 50).map((v, i) => (
                <li key={i}>{typeof v === "object" ? JSON.stringify(v) : String(v)}</li>
              ))}
              {value.length > 50 && <li className="faint">and {value.length - 50} more</li>}
            </ul>
          )}
        </dd>
      </>
    );
  }
  const obj = value as Record<string, unknown>;
  return (
    <>
      <dt>{label}</dt>
      <dd>
        {Object.keys(obj).length === 0 ? (
          <span className="faint">none</span>
        ) : (
          Object.entries(obj).map(([k, v]) => (
            <div key={k}>
              {name === "placeholders_removed" ? attrLabel(k) : k.replace(/_/g, " ")}: {typeof v === "object" ? JSON.stringify(v) : String(v)}
            </div>
          ))
        )}
      </dd>
    </>
  );
}
