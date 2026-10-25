// GOV-04, IMP-09: Operational telemetry (job runs, adapter errors, adapter error rates over 30 days, AI spend)
// and "Run ingest now".

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AdapterErrorRate } from "../api/types";
import { Empty, ErrorBox, Spinner, StatusBadge, useToast } from "../components/Common";
import { formatDate } from "../lib/format";

/** Error rate as a percent pill: green under 5 percent, amber under 20, red otherwise; null means no calls. */
function ErrorRatePill({ rate }: { rate: number | null }) {
  if (rate === null || rate === undefined || Number.isNaN(rate)) return <span className="faint">no calls</span>;
  const pct = rate * 100;
  const cls = pct < 5 ? "p-high" : pct < 20 ? "p-mid" : "p-low";
  return <span className={`pill ${cls}`}>{pct < 10 ? pct.toFixed(1) : Math.round(pct)}%</span>;
}

function AdapterErrorRates({ rows }: { rows: AdapterErrorRate[] }) {
  const windowDays = rows[0]?.window_days;
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Adapter error rates</h3>
        {windowDays !== undefined && <span className="muted small">last {windowDays} days</span>}
      </div>
      <div className="panel-body flush" style={{ maxHeight: 300, overflow: "auto" }}>
        {rows.length === 0 ? (
          <div className="empty">No adapter calls recorded in the window.</div>
        ) : (
          <table className="data compact">
            <thead>
              <tr>
                <th>Adapter</th>
                <th>Calls</th>
                <th>Errors</th>
                <th>Error rate</th>
                <th>Last error</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.adapter}>
                  <td className="mono">{r.adapter}</td>
                  <td>{r.calls}</td>
                  <td>{r.errors}</td>
                  <td>
                    <ErrorRatePill rate={r.error_rate} />
                  </td>
                  <td className="small">
                    {r.last_error ? (
                      <>
                        {r.last_error}
                        {r.last_error_at && <div className="faint nowrap">{formatDate(r.last_error_at)}</div>}
                      </>
                    ) : (
                      <span className="faint">none</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export function TelemetryTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["admin", "telemetry"], queryFn: api.admin.telemetry, refetchInterval: 30_000 });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });

  const run = useMutation({
    mutationFn: api.jobs.runIngest,
    onSuccess: (r) => {
      toast(`Ingest started${r?.id ? ` (run ${r.id})` : ""}`, "ok");
      qc.invalidateQueries({ queryKey: ["admin", "telemetry"] });
      qc.invalidateQueries({ queryKey: ["health"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e) => toast(`Could not start ingest: ${(e as Error).message}`, "error"),
  });

  if (q.isLoading) return <Spinner label="Loading telemetry" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load telemetry" />;
  const t = q.data!;
  const spend = t.ai_spend ?? {};
  const spendEntries = Object.entries(spend).filter(([, v]) => v !== null && v !== undefined && typeof v !== "object");

  return (
    <div className="stack gap16">
      <div className="panel">
        <div className="panel-body row" style={{ justifyContent: "space-between" }}>
          <div>
            <b>Style Master ingest</b>
            <div className="muted small">
              Last successful load: {health.data?.erp_last_load_at ? formatDate(health.data.erp_last_load_at) : "never"}.
              {health.data?.erp_stale ? ` Older than the ${health.data.erp_stale_threshold_hours} hour threshold.` : ""}
            </div>
          </div>
          <button className="primary" disabled={run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? "Starting" : "Run ingest now"}
          </button>
        </div>
      </div>

      <div className="two-col">
        <div className="panel">
          <div className="panel-header">
            <h3>Job runs</h3>
          </div>
          <div className="panel-body flush" style={{ maxHeight: "50vh", overflow: "auto" }}>
            {(t.job_runs ?? []).length === 0 ? (
              <Empty title="No job runs recorded">Ingest, bulk edit, AI and export jobs appear here with their status.</Empty>
            ) : (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Kind</th>
                    <th>Status</th>
                    <th>Started</th>
                    <th>Finished</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {t.job_runs.map((j) => (
                    <tr key={j.id}>
                      <td className="mono">{j.kind}</td>
                      <td>
                        <StatusBadge status={j.status} />
                      </td>
                      <td className="nowrap">{formatDate(j.started_at)}</td>
                      <td className="nowrap">{j.finished_at ? formatDate(j.finished_at) : ""}</td>
                      <td className="muted small">{j.message ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="stack gap16">
          <div className="panel">
            <div className="panel-header">
              <h3>AI spend</h3>
            </div>
            <div className="panel-body">
              {spendEntries.length === 0 ? (
                <span className="muted">No AI calls recorded yet.</span>
              ) : (
                <dl className="kv">
                  {spendEntries.map(([k, v]) => (
                    <div key={k} style={{ display: "contents" }}>
                      <dt>{k.replace(/_/g, " ")}</dt>
                      <dd>{typeof v === "number" && k.includes("cost") ? `$${v.toFixed(2)}` : String(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </div>
          <AdapterErrorRates rows={t.adapter_error_rates ?? []} />
          <div className="panel">
            <div className="panel-header">
              <h3>Adapter errors</h3>
            </div>
            <div className="panel-body flush" style={{ maxHeight: 300, overflow: "auto" }}>
              {(t.adapter_errors ?? []).length === 0 ? (
                <div className="empty">No adapter errors.</div>
              ) : (
                <table className="data compact">
                  <thead>
                    <tr>
                      <th>Adapter</th>
                      <th>When</th>
                      <th>Message</th>
                    </tr>
                  </thead>
                  <tbody>
                    {t.adapter_errors.map((e, i) => (
                      <tr key={i}>
                        <td className="mono">{e.adapter}</td>
                        <td className="nowrap">{formatDate(e.at)}</td>
                        <td className="small">{e.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
