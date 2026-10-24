// IMP-07 (import history and per-batch rollback), IMP-02 (mapping templates), IMP-01 (import sources).
// Tabs: Batches, Templates, Sources (sources are editable by admins only).

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { isAdmin, useImportSources, useMe } from "../api/hooks";
import type { BatchStatus, ImportBatch, ImportRollbackResult, ImportSource, ImportSourceKind, OnErrorPolicy, UnmatchedPolicy } from "../api/types";
import { Badge, Confirm, Dialog, Empty, ErrorBox, Spinner, StatusBadge, Tabs, useToast } from "../components/Common";
import { formatDate, LEVEL_LABEL } from "../lib/format";

type Tab = "batches" | "templates" | "sources";

export const SOURCE_KIND_TEXT: Record<ImportSourceKind, string> = {
  supplier: "Supplier spreadsheet: a vendor or factory workbook in their own layout.",
  retailer: "Retailer template: a wholesale account's item setup form.",
  shopify: "Shopify pull: product data read from the Shopify Admin API or a product CSV export.",
  worksheet: "Keyed worksheet: a file exported from Imports > Worksheets, matched automatically.",
  other: "Other: any CSV or XLSX in a custom layout.",
};

const STATUSES: BatchStatus[] = ["uploaded", "mapped", "validated", "matched", "reviewed", "committing", "committed", "failed", "rolled_back"];

export function BatchStatusBadge({ status }: { status: BatchStatus }) {
  const color =
    status === "committed" ? "green" : status === "failed" ? "red" : status === "rolled_back" ? "purple" : status === "committing" ? "amber" : "blue";
  return <Badge color={color}>{status.replace(/_/g, " ")}</Badge>;
}

export function ImportsPage() {
  const [tab, setTab] = useState<Tab>("batches");
  const navigate = useNavigate();
  return (
    <div>
      <div className="page-header">
        <h1>Imports</h1>
        <div className="actions">
          <Link to="/worksheets" className="btn">
            Worksheet export
          </Link>
          <button className="primary" onClick={() => navigate("/imports/new")}>
            New import
          </button>
        </div>
      </div>
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "batches", label: "History" },
          { key: "templates", label: "Templates" },
          { key: "sources", label: "Sources" },
        ]}
      />
      {tab === "batches" && <BatchesTab />}
      {tab === "templates" && <TemplatesTab />}
      {tab === "sources" && <SourcesTab />}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Batches (IMP-07)
// ---------------------------------------------------------------------------------------------

export function useRollback(onDone?: () => void) {
  const qc = useQueryClient();
  const toast = useToast();
  const [result, setResult] = useState<ImportRollbackResult | null>(null);
  const m = useMutation({
    mutationFn: (id: string) => api.imports.rollback(id),
    onSuccess: (r) => {
      setResult(r);
      toast(`Rollback restored ${r.restored} value${r.restored === 1 ? "" : "s"}.`, "ok");
      qc.invalidateQueries({ queryKey: ["imports"] });
      qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
      onDone?.();
    },
    onError: (e) => toast(`Rollback failed: ${(e as Error).message}`, "error"),
  });
  return { ...m, result, clearResult: () => setResult(null) };
}

export function RollbackResultDialog({ result, onClose }: { result: ImportRollbackResult; onClose: () => void }) {
  return (
    <Dialog
      title="Rollback complete"
      onClose={onClose}
      footer={
        <button className="primary" onClick={onClose}>
          Close
        </button>
      }
    >
      <p>
        {result.restored} value{result.restored === 1 ? "" : "s"} restored to the state before the import.
      </p>
      {result.manual.length > 0 ? (
        <>
          <p className="muted small">
            These values changed again after the import and were not touched. Review them manually:
          </p>
          <table className="data compact">
            <thead>
              <tr>
                <th>Product</th>
                <th>Attribute</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {result.manual.map((m, i) => (
                <tr key={i}>
                  <td>
                    <Link to={`/products/${encodeURIComponent(m.entity_id)}`}>{m.label}</Link>
                  </td>
                  <td className="mono">{m.attribute_code}</td>
                  <td>{m.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <p className="muted small">Nothing needs manual follow-up.</p>
      )}
    </Dialog>
  );
}

function BatchesTab() {
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const [page, setPage] = useState(1);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const sources = useImportSources();
  const q = useQuery({
    queryKey: ["imports", "batches", status, source, page],
    queryFn: () => api.imports.batches({ status: status || undefined, source: source || undefined, page }),
    refetchInterval: (query) => (query.state.data?.rows.some((b) => b.status === "committing") ? 5000 : false),
  });
  const rollback = useRollback(() => setConfirmId(null));
  const sourceLabel = (code: string) => sources.data?.find((s) => s.code === code)?.label ?? code;
  const total = q.data?.total ?? 0;
  const pageSize = q.data?.rows.length ? Math.max(q.data.rows.length, 50) : 50;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div>
      <div className="row mb8">
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <select value={source} onChange={(e) => { setSource(e.target.value); setPage(1); }}>
          <option value="">All sources</option>
          {(sources.data ?? []).map((s) => (
            <option key={s.code} value={s.code}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      {q.isLoading && <Spinner label="Loading import history" />}
      {q.isError && <ErrorBox error={q.error} title="Could not load import history" />}
      {q.data && q.data.rows.length === 0 && (
        <Empty title="No imports yet">Click New import to upload a supplier spreadsheet, retailer template, Shopify export or keyed worksheet.</Empty>
      )}
      {q.data && q.data.rows.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Batch</th>
                <th>Status</th>
                <th>Source</th>
                <th>Level</th>
                <th>Created</th>
                <th>By</th>
                <th className="right">Rows</th>
                <th className="right">Errors</th>
                <th className="right">Creates</th>
                <th className="right">Changes</th>
                <th className="right">Conflicts</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((b: ImportBatch) => (
                <tr key={b.id}>
                  <td>
                    <Link to={`/imports/${encodeURIComponent(b.id)}`} className="mono">
                      {b.id}
                    </Link>
                    {b.worksheet_id && (
                      <Badge color="teal" title={`Keyed worksheet ${b.worksheet_id}`}>
                        worksheet
                      </Badge>
                    )}
                  </td>
                  <td>
                    <BatchStatusBadge status={b.status} />
                    {b.error && (
                      <div className="issue" title={b.error}>
                        {b.error.slice(0, 80)}
                      </div>
                    )}
                  </td>
                  <td>{sourceLabel(b.source_code)}</td>
                  <td>{LEVEL_LABEL[b.level] ?? b.level}</td>
                  <td className="nowrap">{formatDate(b.created_at)}</td>
                  <td>{b.created_by}</td>
                  <td className="num">{b.stats?.rows ?? 0}</td>
                  <td className="num">{b.stats?.errors ?? 0}</td>
                  <td className="num">{b.stats?.creates ?? 0}</td>
                  <td className="num">{b.stats?.changes ?? 0}</td>
                  <td className="num">{b.stats?.conflicts ?? 0}</td>
                  <td className="nowrap">
                    <Link to={`/imports/${encodeURIComponent(b.id)}`} className="btn small">
                      Open
                    </Link>{" "}
                    {b.status === "committed" && (
                      <button className="small danger" onClick={() => setConfirmId(b.id)}>
                        Rollback
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row" style={{ justifyContent: "flex-end", padding: 8 }}>
            <button className="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </button>
            <span className="muted small">
              Page {page} of {pageCount} ({total} batches)
            </span>
            <button className="small" disabled={page >= pageCount} onClick={() => setPage((p) => p + 1)}>
              Next
            </button>
          </div>
        </div>
      )}
      {confirmId && (
        <Confirm
          title="Roll back this import?"
          message={
            <p>
              Every value this batch set is restored to its previous state. Values that were edited again after the import
              are left alone and listed for manual review.
            </p>
          }
          confirmLabel="Roll back"
          busy={rollback.isPending}
          onCancel={() => setConfirmId(null)}
          onConfirm={() => rollback.mutate(confirmId)}
        />
      )}
      {rollback.result && <RollbackResultDialog result={rollback.result} onClose={rollback.clearResult} />}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Templates (IMP-02)
// ---------------------------------------------------------------------------------------------

function TemplatesTab() {
  const [source, setSource] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const sources = useImportSources();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["imports", "templates", source], queryFn: () => api.imports.templates(source || undefined) });
  const remove = useMutation({
    mutationFn: (id: string) => api.imports.deleteTemplate(id),
    onSuccess: () => {
      toast("Template deleted", "ok");
      setConfirmId(null);
      qc.invalidateQueries({ queryKey: ["imports", "templates"] });
    },
    onError: (e) => toast(`Could not delete: ${(e as Error).message}`, "error"),
  });
  const sourceLabel = (code: string) => sources.data?.find((s) => s.code === code)?.label ?? code;

  return (
    <div>
      <p className="muted small">
        A template remembers the column mapping, match keys and policy for a file layout. It is applied automatically when a
        file with the same structure is uploaded for the same source.
      </p>
      <div className="row mb8">
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">All sources</option>
          {(sources.data ?? []).map((s) => (
            <option key={s.code} value={s.code}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} title="Could not load templates" />}
      {q.data && q.data.length === 0 && <Empty title="No templates">Save one from the Map step of an import.</Empty>}
      {q.data && q.data.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Name</th>
                <th>Source</th>
                <th>Level</th>
                <th className="right">Columns</th>
                <th>Match keys</th>
                <th>Unmatched policy</th>
                <th className="right">Header row</th>
                <th className="right">Version</th>
                <th>By</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {q.data.map((t) => (
                <tr key={t.id}>
                  <td>
                    <b>{t.name}</b>
                    <div className="faint small mono" title="Structure signature">
                      {t.structure_signature?.slice(0, 24)}
                    </div>
                  </td>
                  <td>{sourceLabel(t.source_code)}</td>
                  <td>{LEVEL_LABEL[t.level] ?? t.level}</td>
                  <td className="num">{t.columns.filter((c) => !c.skip && c.target !== "skip").length}</td>
                  <td className="mono small">{t.match_keys.join(", ")}</td>
                  <td>{t.unmatched_policy.replace(/_/g, " ")}</td>
                  <td className="num">{t.header_row}</td>
                  <td className="num">{t.version}</td>
                  <td>{t.created_by}</td>
                  <td>
                    <button className="small danger" onClick={() => setConfirmId(t.id)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {confirmId && (
        <Confirm
          title="Delete this template?"
          message="Future uploads with this layout will need to be mapped by hand."
          confirmLabel="Delete"
          busy={remove.isPending}
          onCancel={() => setConfirmId(null)}
          onConfirm={() => remove.mutate(confirmId)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Sources (admin)
// ---------------------------------------------------------------------------------------------

const EMPTY_SOURCE: ImportSource = {
  code: "",
  label: "",
  kind: "supplier",
  default_policy: { unmatched: "update_only", on_error: "skip_row" },
};

function SourcesTab() {
  const me = useMe();
  const admin = isAdmin(me.data);
  const sources = useImportSources();
  const [editing, setEditing] = useState<{ source: ImportSource; isNew: boolean } | null>(null);

  return (
    <div>
      <div className="row mb8" style={{ justifyContent: "space-between" }}>
        <span className="muted small">Each source carries a kind and a default policy for unmatched rows and errors.</span>
        {admin && (
          <button className="primary" onClick={() => setEditing({ source: { ...EMPTY_SOURCE }, isNew: true })}>
            Add source
          </button>
        )}
      </div>
      {sources.isLoading && <Spinner />}
      {sources.isError && <ErrorBox error={sources.error} title="Could not load sources" />}
      {sources.data && sources.data.length === 0 && (
        <Empty title="No import sources">{admin ? "Add a source to start importing." : "Ask an admin to add an import source."}</Empty>
      )}
      {sources.data && sources.data.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Code</th>
                <th>Label</th>
                <th>Kind</th>
                <th>Unmatched rows</th>
                <th>On error</th>
                {admin && <th />}
              </tr>
            </thead>
            <tbody>
              {sources.data.map((s) => (
                <tr key={s.code}>
                  <td className="mono">{s.code}</td>
                  <td>{s.label}</td>
                  <td>
                    <StatusBadge status={s.kind} />
                    <div className="faint small">{SOURCE_KIND_TEXT[s.kind]}</div>
                  </td>
                  <td>{s.default_policy.unmatched.replace(/_/g, " ")}</td>
                  <td>{s.default_policy.on_error.replace(/_/g, " ")}</td>
                  {admin && (
                    <td>
                      <button className="small" onClick={() => setEditing({ source: { ...s, default_policy: { ...s.default_policy } }, isNew: false })}>
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
      {editing && <SourceDialog source={editing.source} isNew={editing.isNew} onClose={() => setEditing(null)} />}
    </div>
  );
}

function SourceDialog({ source, isNew, onClose }: { source: ImportSource; isNew: boolean; onClose: () => void }) {
  const [s, setS] = useState<ImportSource>(source);
  const qc = useQueryClient();
  const toast = useToast();
  const save = useMutation({
    mutationFn: () => (isNew ? api.imports.createSource(s) : api.imports.updateSource(s.code, s)),
    onSuccess: () => {
      toast(isNew ? "Source added" : "Source saved", "ok");
      qc.invalidateQueries({ queryKey: ["imports", "sources"] });
      onClose();
    },
  });
  const valid = /^[a-z0-9_]+$/.test(s.code) && s.label.trim().length > 0;
  return (
    <Dialog
      title={isNew ? "Add import source" : `Edit source ${s.code}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={!valid || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving" : "Save"}
          </button>
        </>
      }
    >
      <div className="stack gap16">
        <div className="form-grid">
          <label className="field">
            Code
            <input value={s.code} disabled={!isNew} placeholder="lowercase_with_underscores" onChange={(e) => setS({ ...s, code: e.target.value })} />
          </label>
          <label className="field">
            Label
            <input value={s.label} onChange={(e) => setS({ ...s, label: e.target.value })} />
          </label>
          <label className="field">
            Kind
            <select value={s.kind} onChange={(e) => setS({ ...s, kind: e.target.value as ImportSourceKind })}>
              {(Object.keys(SOURCE_KIND_TEXT) as ImportSourceKind[]).map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Unmatched rows (default)
            <select
              value={s.default_policy.unmatched}
              onChange={(e) => setS({ ...s, default_policy: { ...s.default_policy, unmatched: e.target.value as UnmatchedPolicy } })}
            >
              <option value="create">create new products</option>
              <option value="update_only">update only (skip unmatched)</option>
              <option value="create_under_match">create under the matched parent</option>
            </select>
          </label>
          <label className="field">
            On error (default)
            <select
              value={s.default_policy.on_error}
              onChange={(e) => setS({ ...s, default_policy: { ...s.default_policy, on_error: e.target.value as OnErrorPolicy } })}
            >
              <option value="skip_row">skip the whole row</option>
              <option value="skip_value">skip only the bad value</option>
            </select>
          </label>
        </div>
        <div className="help">{SOURCE_KIND_TEXT[s.kind]}</div>
        {save.isError && <ErrorBox error={save.error} title="Could not save the source" />}
      </div>
    </Dialog>
  );
}
