// GOV-02: Field-level history with filter by attribute and user, a Restore button per row (single value),
// "Restore to this point" per row (whole product back to just before that change, POST restore-to, Phase 6)
// and a Change sets panel (GET /api/change-sets?entity_id=) with Roll back as a unit.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, changeSetApi } from "../api/client";
import type { AttributeDefinition, ChangeSet, HistoryRow, OptionList, RestoreToResult, RollbackResult } from "../api/types";
import { Badge, Dialog, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { displayValue, formatDate } from "../lib/format";

const PAGE_SIZE = 50;
const CHANGE_SET_PAGE = 50;

const KIND_COLOR: Record<string, string> = {
  edit: "teal",
  import: "blue",
  bulk: "blue",
  ai: "purple",
  rule: "amber",
  restore: "green",
  rollback: "amber",
  approval: "green",
};

const OUTCOME_COLOR: Record<string, string> = {
  approved: "green",
  draft: "amber",
  rejected: "red",
  unchanged: "",
  skipped: "",
};

export function HistoryTab({
  entityId,
  attributes,
  optionLists,
}: {
  entityId: string;
  attributes: AttributeDefinition[];
  optionLists: Record<string, OptionList>;
}) {
  const [attributeCode, setAttributeCode] = useState("");
  const [userInput, setUserInput] = useState("");
  const [user, setUser] = useState("");
  const [page, setPage] = useState(1);
  const [restorePoint, setRestorePoint] = useState<HistoryRow | null>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const attrByCode = new Map(attributes.map((a) => [a.code, a]));
  const attrLabel = (code: string) => attrByCode.get(code)?.label ?? code;

  const q = useQuery({
    queryKey: ["product", entityId, "history", attributeCode, user, page],
    queryFn: () => api.products.history(entityId, { attribute_code: attributeCode || undefined, user_email: user || undefined, page }),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["product", entityId] });
    qc.invalidateQueries({ queryKey: ["change-sets", entityId] });
    qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
  };

  const restore = useMutation({
    mutationFn: (historyId: string) => api.products.restore(entityId, historyId),
    onSuccess: (res) => {
      const r = res?.results?.[0];
      toast(r?.outcome === "draft" ? "Restored as a draft, pending approval" : "Value restored", "ok");
      invalidate();
    },
    onError: (e) => toast(`Restore failed: ${(e as Error).message}`, "error"),
  });

  return (
    <div className="stack gap16">
      <div className="row">
        <select
          value={attributeCode}
          onChange={(e) => {
            setAttributeCode(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All attributes</option>
          {attributes
            .slice()
            .sort((a, b) => a.label.localeCompare(b.label))
            .map((a) => (
              <option key={a.code} value={a.code}>
                {a.label}
              </option>
            ))}
        </select>
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            setUser(userInput.trim());
            setPage(1);
          }}
        >
          <input placeholder="Filter by user email" value={userInput} onChange={(e) => setUserInput(e.target.value)} />
          <button type="submit">Apply</button>
        </form>
      </div>
      {q.isLoading && <Spinner label="Loading history" />}
      {q.isError && <ErrorBox error={q.error} title="Could not load history" />}
      {q.data && q.data.rows.length === 0 && (
        <Empty title="No history">{attributeCode || user ? "No changes match the filters." : "No value on this product has changed yet."}</Empty>
      )}
      {q.data && q.data.rows.length > 0 && (
        <div className="panel">
          <table className="data compact">
            <thead>
              <tr>
                <th>When</th>
                <th>Attribute</th>
                <th>Channel</th>
                <th>Old value</th>
                <th>New value</th>
                <th>Source</th>
                <th>By</th>
                <th>Reason</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((h) => {
                const a = attrByCode.get(h.attribute_code);
                return (
                  <tr key={h.id}>
                    <td className="nowrap">{formatDate(h.set_at)}</td>
                    <td>
                      {a?.label ?? h.attribute_code}
                      <div className="faint mono small">{h.attribute_code}</div>
                    </td>
                    <td>{h.channel_code ?? <span className="faint">global</span>}</td>
                    <td className="pre" style={{ maxWidth: 240 }}>
                      {displayValue(h.old_value, a, optionLists) || <span className="faint">(empty)</span>}
                    </td>
                    <td className="pre" style={{ maxWidth: 240 }}>
                      {displayValue(h.new_value, a, optionLists) || <span className="faint">(empty)</span>}
                    </td>
                    <td>{h.source_type}</td>
                    <td>{h.set_by}</td>
                    <td className="muted small">
                      {h.reason ?? ""}
                      {h.change_set_id && <div className="faint mono">set {h.change_set_id}</div>}
                    </td>
                    <td className="nowrap">
                      <button
                        className="small"
                        disabled={restore.isPending}
                        onClick={() => restore.mutate(h.id)}
                        title="Restore the old value of this single attribute"
                      >
                        Restore
                      </button>{" "}
                      <button
                        className="small"
                        disabled={restore.isPending}
                        onClick={() => setRestorePoint(h)}
                        title="Put the whole product back to the state just before this change"
                      >
                        Restore to this point
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="grid-status">
            <span>{q.data.total} changes</span>
            <span className="row">
              <button className="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </button>
              <span>
                Page {page} of {Math.max(1, Math.ceil(q.data.total / PAGE_SIZE))}
              </span>
              <button className="small" disabled={page * PAGE_SIZE >= q.data.total} onClick={() => setPage((p) => p + 1)}>
                Next
              </button>
            </span>
          </div>
        </div>
      )}

      <ChangeSetsPanel entityId={entityId} attrLabel={attrLabel} onChanged={invalidate} />

      {restorePoint && (
        <RestoreToDialog
          entityId={entityId}
          row={restorePoint}
          attrLabel={attrLabel}
          onClose={() => setRestorePoint(null)}
          onRestored={invalidate}
        />
      )}
    </div>
  );
}

function RestoreToDialog({
  entityId,
  row,
  attrLabel,
  onClose,
  onRestored,
}: {
  entityId: string;
  row: HistoryRow;
  attrLabel: (code: string) => string;
  onClose: () => void;
  onRestored: () => void;
}) {
  const toast = useToast();
  const [result, setResult] = useState<RestoreToResult | null>(null);
  const run = useMutation({
    mutationFn: () => api.products.restoreTo(entityId, { history_id: row.id }),
    onSuccess: (res) => {
      setResult(res);
      toast(`Restored ${res.restored} attribute${res.restored === 1 ? "" : "s"}.`, res.restored ? "ok" : "warn");
      onRestored();
    },
  });
  const when = formatDate(row.set_at);

  return (
    <Dialog
      title="Restore to this point"
      onClose={onClose}
      footer={
        result ? (
          <button className="primary" onClick={onClose}>
            Close
          </button>
        ) : (
          <>
            <button onClick={onClose} disabled={run.isPending}>
              Cancel
            </button>
            <button className="primary" disabled={run.isPending} onClick={() => run.mutate()}>
              {run.isPending ? "Restoring" : "Restore product"}
            </button>
          </>
        )
      }
    >
      <div className="stack">
        {!result && (
          <>
            <p style={{ margin: 0 }}>
              The whole product returns to the state just before the change to <b>{attrLabel(row.attribute_code)}</b> by {row.set_by} on{" "}
              {when}.
            </p>
            <p className="muted small" style={{ margin: 0 }}>
              Every attribute changed since then goes back to the value it held at that time; a value that did not exist yet is cleared. The
              restore is recorded as one change set that can be rolled back. Attributes in groups you cannot approve are reported as rejected
              and left as they are.
            </p>
            {run.isError && <ErrorBox error={run.error} title="Could not restore" />}
          </>
        )}
        {result && (
          <>
            <div>
              Restored <b>{result.restored}</b> attribute{result.restored === 1 ? "" : "s"}.
              {result.change_set_id && (
                <span className="faint mono small"> set {result.change_set_id}</span>
              )}
            </div>
            {result.results.length === 0 ? (
              <span className="muted small">Nothing changed after that point.</span>
            ) : (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Attribute</th>
                    <th>Channel</th>
                    <th>Outcome</th>
                    <th>Note</th>
                  </tr>
                </thead>
                <tbody>
                  {result.results.map((r, i) => (
                    <tr key={i}>
                      <td>{attrLabel(r.attribute_code)}</td>
                      <td>{r.channel_code ?? <span className="faint">global</span>}</td>
                      <td>
                        <Badge color={OUTCOME_COLOR[r.outcome] || undefined}>{r.outcome}</Badge>
                      </td>
                      <td className="muted small">{r.message ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
    </Dialog>
  );
}

function ChangeSetsPanel({ entityId, attrLabel, onChanged }: { entityId: string; attrLabel: (code: string) => string; onChanged: () => void }) {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [lastRollback, setLastRollback] = useState<{ id: string; result: RollbackResult } | null>(null);
  const q = useQuery({
    queryKey: ["change-sets", entityId, page],
    queryFn: () => changeSetApi.list({ entity_id: entityId, page, page_size: CHANGE_SET_PAGE }),
  });
  const rollback = useMutation({
    mutationFn: (id: string) => changeSetApi.rollback(id),
    onSuccess: (res, id) => {
      setLastRollback({ id, result: res });
      const manual = res.manual?.length ?? 0;
      toast(`Rolled back ${res.restored} value${res.restored === 1 ? "" : "s"}${manual ? `, ${manual} need a manual check` : ""}.`, manual ? "warn" : "ok");
      onChanged();
    },
    onError: (e) => toast(`Roll back failed: ${(e as Error).message}`, "error"),
  });
  const rows: ChangeSet[] = q.data?.rows ?? [];
  const total = q.data?.total ?? 0;

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>
          Change sets <span className="muted small">{total}</span>
        </h3>
        <span className="muted small">Roll back undoes a whole set at once. Values touched since are listed, not reverted.</span>
      </div>
      {q.isLoading && (
        <div className="panel-body">
          <Spinner label="Loading change sets" />
        </div>
      )}
      {q.isError && (
        <div className="panel-body">
          <ErrorBox error={q.error} title="Could not load change sets" />
        </div>
      )}
      {q.data && rows.length === 0 && <Empty title="No change sets">Edits, imports, bulk actions, AI accepts, rule runs and restores appear here as units.</Empty>}
      {rows.length > 0 && (
        <>
          <table className="data compact">
            <thead>
              <tr>
                <th>Kind</th>
                <th>By</th>
                <th>When</th>
                <th>Description</th>
                <th>Changes</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Badge color={KIND_COLOR[c.kind]}>{c.kind}</Badge>
                  </td>
                  <td>{c.created_by}</td>
                  <td className="nowrap">{formatDate(c.created_at)}</td>
                  <td className="small">
                    {c.description ?? ""}
                    {c.source_ref && <div className="faint mono">{c.source_ref}</div>}
                    <div className="faint mono">{c.id}</div>
                  </td>
                  <td>{c.changes ?? ""}</td>
                  <td className="nowrap" style={{ textAlign: "right" }}>
                    {c.rolled_back_at ? (
                      <span className="muted small" title={formatDate(c.rolled_back_at)}>
                        rolled back {formatDate(c.rolled_back_at, false)}
                      </span>
                    ) : c.rollbackable === false ? (
                      <span className="muted small" title={c.kind === "ingest" ? "ERP loads are never undone in the PIM" : "Rolls back from its own page"}>
                        {c.kind === "import" ? "see import" : c.kind === "bulk" ? "see bulk action" : "not undoable"}
                      </span>
                    ) : (
                      <button
                        className="small"
                        disabled={rollback.isPending}
                        onClick={() => rollback.mutate(c.id)}
                        title="Undo every change in this set as a unit"
                      >
                        {rollback.isPending && rollback.variables === c.id ? "Rolling back" : "Roll back"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {total > CHANGE_SET_PAGE && (
            <div className="grid-status">
              <span>{total} change sets</span>
              <span className="row">
                <button className="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </button>
                <span>
                  Page {page} of {Math.max(1, Math.ceil(total / CHANGE_SET_PAGE))}
                </span>
                <button className="small" disabled={page * CHANGE_SET_PAGE >= total} onClick={() => setPage((p) => p + 1)}>
                  Next
                </button>
              </span>
            </div>
          )}
        </>
      )}
      {lastRollback && (
        <div className="panel-body small" style={{ borderTop: "1px solid var(--border)" }}>
          <div>
            Rolled back set <span className="mono">{lastRollback.id}</span>: restored <b>{lastRollback.result.restored}</b>.
          </div>
          {lastRollback.result.manual.length > 0 && (
            <>
              <div className="muted" style={{ marginTop: 4 }}>
                Changed since the set was written, check by hand:
              </div>
              <ul className="reasons small">
                {lastRollback.result.manual.map((m, i) => (
                  <li key={i}>
                    {attrLabel(m.attribute_code)}
                    {m.entity_id !== entityId && <span className="faint mono"> on {m.entity_id}</span>}: {m.reason}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
