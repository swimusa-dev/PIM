// EXP-13, Phase 5 D-03, D-13: Package detail. Status, snapshot time, summary counts, review rows (display only;
// the editable workbook is the XLSX), file downloads (now with the file kind, including matrixify.xlsx), review
// workbook upload, reconcile result, and the Shopify sandbox section: "Plan only" and "Run against sandbox"
// (POST /api/packages/{id}/sandbox-run, 409 shown as "Sandbox store not configured") with the SandboxReport view.

import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { AiBadge, ApprovalBadge, Badge, Confirm, Empty, ErrorBox, Spinner, StatusBadge, useToast } from "../components/Common";
import { clipboardValue, formatBytes, formatDate } from "../lib/format";
import type { PackageRow, ReconcileResult, SandboxReport } from "../api/types";

const RECONCILE_LABEL: Record<ReconcileResult, string> = {
  applied: "Applied",
  not_applied: "Not applied",
  changed_differently: "Changed differently in Shopify",
};

export function PackageDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [fieldFilter, setFieldFilter] = useState("");
  const [onlyIncluded, setOnlyIncluded] = useState(false);

  const q = useQuery({
    queryKey: ["packages", "detail", id],
    queryFn: () => api.packages.detail(id),
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "pending" || s === "building" ? 5000 : false;
    },
  });

  const reviewUpload = useMutation({
    mutationFn: (file: File) => api.packages.reviewUpload(id, file),
    onSuccess: () => {
      toast("Reviewed workbook uploaded. CSVs regenerated from included rows.", "ok");
      qc.invalidateQueries({ queryKey: ["packages"] });
    },
    onError: (e) => toast(`Upload failed: ${(e as Error).message}`, "error"),
  });
  const reconcile = useMutation({
    mutationFn: () => api.packages.reconcile(id),
    onSuccess: () => {
      toast("Reconciled against a fresh Shopify snapshot.", "ok");
      qc.invalidateQueries({ queryKey: ["packages"] });
    },
    onError: (e) => toast(`Reconcile failed: ${(e as Error).message}`, "error"),
  });

  const rows = useMemo(() => {
    let r = q.data?.rows ?? [];
    if (fieldFilter) r = r.filter((x) => x.field === fieldFilter);
    if (onlyIncluded) r = r.filter((x) => x.include);
    return r;
  }, [q.data, fieldFilter, onlyIncluded]);

  const fields = useMemo(() => Array.from(new Set((q.data?.rows ?? []).map((r) => r.field))).sort(), [q.data]);
  const byField = useMemo(() => {
    const s = q.data?.summary;
    if (s?.by_field && Array.isArray(s.by_field)) return s.by_field;
    const m = new Map<string, number>();
    for (const r of q.data?.rows ?? []) m.set(r.field, (m.get(r.field) ?? 0) + 1);
    return Array.from(m, ([field, count]) => ({ field, count })).sort((a, b) => b.count - a.count);
  }, [q.data]);
  const byProduct = useMemo(() => {
    const s = q.data?.summary;
    if (s?.by_product && Array.isArray(s.by_product)) return s.by_product;
    const m = new Map<string, { handle: string; title: string; count: number }>();
    for (const r of q.data?.rows ?? []) {
      const e = m.get(r.handle) ?? { handle: r.handle, title: r.title, count: 0 };
      e.count += 1;
      m.set(r.handle, e);
    }
    return Array.from(m.values()).sort((a, b) => b.count - a.count);
  }, [q.data]);

  if (q.isLoading) return <Spinner label="Loading package" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load the package" />;
  const p = q.data!;
  const hasReconcile = p.rows.some((r) => r.reconcile_result);
  const reconcileCounts = p.rows.reduce(
    (acc, r) => {
      if (r.reconcile_result) acc[r.reconcile_result] += 1;
      return acc;
    },
    { applied: 0, not_applied: 0, changed_differently: 0 } as Record<ReconcileResult, number>,
  );

  return (
    <div className="stack gap16">
      <div className="page-header">
        <div>
          <div className="muted small">
            <Link to="/packages">Update packages</Link> / {p.channel_code}
          </div>
          <h1 className="row">
            <span className="mono">{p.id}</span> <StatusBadge status={p.status} />
          </h1>
          <div className="muted small">
            Created {formatDate(p.created_at)} by {p.created_by}. Snapshot{" "}
            {p.snapshot_at ? `taken ${formatDate(p.snapshot_at)}` : "not taken yet"}.
          </div>
        </div>
        <div className="actions">
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) reviewUpload.mutate(f);
              e.target.value = "";
            }}
          />
          <button onClick={() => fileRef.current?.click()} disabled={reviewUpload.isPending || p.status !== "ready"}>
            {reviewUpload.isPending ? "Uploading" : "Upload reviewed workbook"}
          </button>
          <button
            className="primary"
            onClick={() => reconcile.mutate()}
            disabled={reconcile.isPending || (p.status !== "ready" && p.status !== "reconciled")}
            title="Take a fresh snapshot and mark each change applied, not applied, or changed differently"
          >
            {reconcile.isPending ? "Reconciling" : "Reconcile"}
          </button>
        </div>
      </div>

      {(p.status === "pending" || p.status === "building") && (
        <div className="banner warn" style={{ borderRadius: "var(--radius)", border: "1px solid var(--border)" }}>
          The package is still building. This page refreshes automatically.
        </div>
      )}
      {p.status === "failed" && (
        <ErrorBox error="The package build failed. Check Admin, Telemetry for the job error, then create a new package." title="Build failed" />
      )}

      <div className="cards">
        <div className="card">
          <div className="card-title">Products</div>
          <div className="card-value">{p.products}</div>
        </div>
        <div className="card">
          <div className="card-title">Field changes</div>
          <div className="card-value">{p.changes}</div>
        </div>
        <div className="card">
          <div className="card-title">Included</div>
          <div className="card-value">{p.rows.filter((r) => r.include).length}</div>
        </div>
        {hasReconcile && (
          <>
            <div className="card">
              <div className="card-title">Applied</div>
              <div className="card-value">{reconcileCounts.applied}</div>
            </div>
            <div className="card">
              <div className="card-title">Not applied</div>
              <div className="card-value alert">{reconcileCounts.not_applied}</div>
            </div>
            <div className="card">
              <div className="card-title">Changed differently</div>
              <div className="card-value alert">{reconcileCounts.changed_differently}</div>
            </div>
          </>
        )}
      </div>

      <div className="two-col">
        <div className="panel">
          <div className="panel-header">
            <h3>Files</h3>
          </div>
          <div className="panel-body flush">
            {p.files.length === 0 ? (
              <Empty title="No files yet">The review workbook and import CSVs appear here once the build finishes.</Empty>
            ) : (
              <table className="data compact">
                <tbody>
                  {p.files.map((f) => (
                    <tr key={f.name}>
                      <td>
                        <a href={api.packages.fileUrl(p.id, f.name)} download className="mono">
                          {f.name}
                        </a>
                      </td>
                      <td>{f.kind ? <Badge color={f.kind === "matrixify" ? "teal" : undefined}>{f.kind}</Badge> : null}</td>
                      <td className="num muted">{formatBytes(f.size)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
        <div className="panel">
          <div className="panel-header">
            <h3>Summary by field</h3>
          </div>
          <div className="panel-body flush" style={{ maxHeight: 260, overflow: "auto" }}>
            {byField.length === 0 ? (
              <Empty title="No changes">Every selected product already matches Shopify for the fields the PIM owns.</Empty>
            ) : (
              <table className="data compact">
                <tbody>
                  {byField.map((f) => (
                    <tr key={f.field} className="clickable" onClick={() => setFieldFilter(fieldFilter === f.field ? "" : f.field)}>
                      <td className="mono">{f.field}</td>
                      <td className="num">{f.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      <div className="two-col">
        <div className="panel">
          <div className="panel-header">
            <h3>Summary by product</h3>
          </div>
          <div className="panel-body flush" style={{ maxHeight: 260, overflow: "auto" }}>
            <table className="data compact">
              <tbody>
                {byProduct.map((pr) => (
                  <tr key={pr.handle}>
                    <td className="mono">{pr.handle}</td>
                    <td>{pr.title ?? ""}</td>
                    <td className="num">{pr.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="panel">
          <div className="panel-header">
            <h3>Skipped and intentional clears</h3>
          </div>
          <div className="panel-body" style={{ maxHeight: 260, overflow: "auto" }}>
            {(p.summary.skipped?.length ?? 0) === 0 && (p.summary.intentional_clears?.length ?? 0) === 0 ? (
              <span className="muted">No products were skipped as not ready or ineligible, and no field is being cleared.</span>
            ) : (
              <>
                {(p.summary.skipped ?? []).map((s, i) => (
                  <div key={`s${i}`} className="small">
                    <Badge color="amber">skipped</Badge> <span className="mono">{s.handle}</span>: {s.reason}
                  </div>
                ))}
                {(p.summary.intentional_clears ?? []).map((c, i) => (
                  <div key={`c${i}`} className="small">
                    <Badge color="red">clear</Badge> <span className="mono">{c.handle}</span> {c.field}
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      </div>

      <SandboxSection packageId={p.id} stored={p.sandbox_report ?? null} ready={p.status === "ready" || p.status === "reconciled"} />

      <div className="panel">
        <div className="panel-header">
          <h3>Review rows</h3>
          <div className="row">
            <span className="muted small">
              Include is display only. Edit the Include column in the XLSX workbook and upload it to change what is imported.
            </span>
            <select value={fieldFilter} onChange={(e) => setFieldFilter(e.target.value)}>
              <option value="">All fields</option>
              {fields.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
            <label className="inline">
              <input type="checkbox" checked={onlyIncluded} onChange={(e) => setOnlyIncluded(e.target.checked)} /> Included only
            </label>
          </div>
        </div>
        <div className="panel-body flush" style={{ maxHeight: "60vh", overflow: "auto" }}>
          {rows.length === 0 ? (
            <Empty title="No rows to show">Adjust the filters above or wait for the build to finish.</Empty>
          ) : (
            <table className="data compact">
              <thead>
                <tr>
                  <th>Include</th>
                  <th>Handle</th>
                  <th>Title</th>
                  <th>Field</th>
                  <th>Current Shopify value</th>
                  <th>Proposed value</th>
                  <th>Source</th>
                  <th>Approval</th>
                  {hasReconcile && <th>Reconcile result</th>}
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r: PackageRow, i) => (
                  <tr key={`${r.handle}:${r.field}:${i}`} style={{ opacity: r.include ? 1 : 0.55 }}>
                    <td>
                      <input type="checkbox" checked={r.include} readOnly disabled title="Edit Include in the XLSX workbook" />
                    </td>
                    <td className="mono">{r.handle}</td>
                    <td>{r.title}</td>
                    <td className="mono">{r.field}</td>
                    <td className="pre" style={{ maxWidth: 280 }}>
                      {clipboardValue(r.current_value) || <span className="faint">(empty)</span>}
                    </td>
                    <td className="pre" style={{ maxWidth: 280 }}>
                      {clipboardValue(r.proposed_value) || <span className="faint">(clear)</span>}
                      {r.ai_generated && <AiBadge />}
                    </td>
                    <td>{r.source_type}</td>
                    <td>
                      <ApprovalBadge state={r.approval_state} />
                    </td>
                    {hasReconcile && (
                      <td>
                        {r.reconcile_result ? <StatusBadge status={RECONCILE_LABEL[r.reconcile_result]} /> : <span className="faint">pending</span>}
                      </td>
                    )}
                    <td className="muted small">{r.note ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

// ---- Phase 5 (D-03): Shopify sandbox write path, production flag off ----
function SandboxSection({ packageId, stored, ready }: { packageId: string; stored: SandboxReport | null; ready: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [confirmRun, setConfirmRun] = useState(false);
  const run = useMutation({
    mutationFn: (planOnly: boolean) => api.packages.sandboxRun(packageId, planOnly),
    onSuccess: (r) => {
      setConfirmRun(false);
      toast(r.mode === "plan" ? `Plan built: ${r.mutations.length} mutation${r.mutations.length === 1 ? "" : "s"} for ${r.products} product${r.products === 1 ? "" : "s"}.` : `Sandbox run finished on ${r.store}: ${r.errors.length === 0 ? "no errors" : `${r.errors.length} error${r.errors.length === 1 ? "" : "s"}`}.`, r.errors.length === 0 ? "ok" : "warn");
      if (r.mode === "executed") qc.invalidateQueries({ queryKey: ["packages"] });
    },
    onError: (e) => {
      setConfirmRun(false);
      if (!(e instanceof ApiError && e.status === 409)) toast(`Sandbox run failed: ${(e as Error).message}`, "error");
    },
  });
  const notConfigured = run.error instanceof ApiError && run.error.status === 409;
  const report = run.data ?? stored;
  const fromThisRun = !!run.data;

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>
          Shopify sandbox <Badge color="amber" title="The production write path stays off (D-03); runs only touch the sandbox store">sandbox only</Badge>
        </h3>
        <div className="row">
          <button className="small" disabled={!ready || run.isPending} title="Build the targeted-mutation plan from the included rows without writing anything" onClick={() => run.mutate(true)}>
            {run.isPending && run.variables === true ? "Planning" : "Plan only"}
          </button>
          <button className="primary small" disabled={!ready || run.isPending} title="Run the plan against the sandbox store and check the protected fields before and after" onClick={() => setConfirmRun(true)}>
            {run.isPending && run.variables === false ? "Running" : "Run against sandbox"}
          </button>
        </div>
      </div>
      <div className="panel-body stack gap16">
        <span className="muted small">
          Builds productUpdate, metafieldsSet (batches of 25) and productVariantsBulkUpdate mutations from the included rows, never touching the channel's protected fields. The
          real run reads the protected metafields before and after and stores the report here.
        </span>
        {!ready && <span className="faint small">The package must be ready (or reconciled) before a sandbox run.</span>}
        {notConfigured && (
          <div className="banner warn" style={{ borderRadius: "var(--radius)" }}>
            Sandbox store not configured. Set <span className="mono">PIM_SHOPIFY_SANDBOX_DOMAIN</span> and <span className="mono">PIM_SHOPIFY_SANDBOX_TOKEN</span> on the app, then try again.
          </div>
        )}
        {run.isError && !notConfigured && <ErrorBox error={run.error} title="Sandbox run failed" />}
        {report ? (
          <SandboxReportView report={report} stored={!fromThisRun} />
        ) : (
          <Empty title="No sandbox report yet">Plan only shows what would be sent; Run against sandbox executes it on the sandbox store and keeps the report on this package.</Empty>
        )}
      </div>
      {confirmRun && (
        <Confirm
          title="Run against the sandbox store"
          confirmLabel="Run against sandbox"
          busy={run.isPending}
          onCancel={() => setConfirmRun(false)}
          onConfirm={() => run.mutate(false)}
          message={
            <div className="stack">
              <p style={{ margin: 0 }}>This executes the mutations for every included row on the Shopify sandbox store (not production). Protected fields are read before and after and reported below.</p>
              <p className="muted small" style={{ margin: 0 }}>The production write path stays off; this is the D-03 rehearsal only.</p>
            </div>
          }
        />
      )}
    </div>
  );
}

function MutationStatusBadge({ status }: { status: SandboxReport["mutations"][number]["status"] }) {
  const color = status === "ok" ? "green" : status === "error" ? "red" : "blue";
  return <Badge color={color}>{status}</Badge>;
}

function sandboxValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  return clipboardValue(v);
}

export function SandboxReportView({ report, stored }: { report: SandboxReport; stored: boolean }) {
  const changed = report.protected_check.filter((c) => !c.unchanged).length;
  const errors = report.mutations.filter((m) => m.status === "error").length;
  return (
    <div className="stack gap16">
      <dl className="kv">
        <dt>Store</dt>
        <dd className="mono">{report.store || <span className="faint">unknown</span>}</dd>
        <dt>Mode</dt>
        <dd>
          <Badge color={report.mode === "executed" ? "green" : "blue"}>{report.mode === "executed" ? "executed" : "plan"}</Badge>{" "}
          {stored && <span className="faint small">(stored report from the last run)</span>}
        </dd>
        <dt>Products</dt>
        <dd>{report.products}</dd>
        <dt>Time</dt>
        <dd>{formatDate(report.at)}</dd>
      </dl>

      <div>
        <div className="muted small mb8">
          Mutations ({report.mutations.length}){errors > 0 && <Badge color="red" title="Mutations that failed">{errors} failed</Badge>}
        </div>
        {report.mutations.length === 0 ? (
          <span className="faint small">No mutations: the included rows produce nothing to send.</span>
        ) : (
          <div style={{ maxHeight: 320, overflow: "auto" }}>
            <table className="data compact">
              <thead>
                <tr>
                  <th>Kind</th>
                  <th>Handle</th>
                  <th>Fields</th>
                  <th>Status</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {report.mutations.map((m, i) => (
                  <tr key={i}>
                    <td className="mono">{m.kind}</td>
                    <td className="mono">{m.handle}</td>
                    <td>
                      {m.fields.length === 0 ? (
                        <span className="faint">none</span>
                      ) : (
                        <div className="chips">
                          {m.fields.map((f) => (
                            <Badge key={f}>
                              <span className="mono">{f}</span>
                            </Badge>
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      <MutationStatusBadge status={m.status} />
                    </td>
                    <td className="small">{m.message ?? <span className="faint">none</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <div className="muted small mb8">
          Protected fields check ({report.protected_check.length}){" "}
          {report.protected_check.length > 0 && (changed === 0 ? <Badge color="green">all unchanged</Badge> : <Badge color="red">{changed} changed</Badge>)}
        </div>
        {report.protected_check.length === 0 ? (
          <span className="faint small">{report.mode === "plan" ? "Protected fields are checked when the plan is executed." : "No protected fields were read."}</span>
        ) : (
          <div style={{ maxHeight: 320, overflow: "auto" }}>
            <table className="data compact">
              <thead>
                <tr>
                  <th>Handle</th>
                  <th>Field</th>
                  <th>Before</th>
                  <th>After</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {report.protected_check.map((c, i) => (
                  <tr key={i} className={c.unchanged ? "" : "protected-changed"}>
                    <td className="mono">{c.handle}</td>
                    <td className="mono">{c.field}</td>
                    <td className="pre" style={{ maxWidth: 260 }}>
                      {sandboxValue(c.before) || <span className="faint">(empty)</span>}
                    </td>
                    <td className="pre" style={{ maxWidth: 260 }}>
                      {sandboxValue(c.after) || <span className="faint">(empty)</span>}
                    </td>
                    <td>{c.unchanged ? <Badge color="green">unchanged</Badge> : <Badge color="red">changed</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <div className="muted small mb8">Errors ({report.errors.length})</div>
        {report.errors.length === 0 ? (
          <span className="faint small">No errors.</span>
        ) : (
          <ul className="small" style={{ margin: 0, paddingLeft: 18, color: "var(--red)" }}>
            {report.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
