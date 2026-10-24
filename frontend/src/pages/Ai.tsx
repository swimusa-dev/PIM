// AI-04, AI-07: AI page. Runs (table with status filter and paging, link to the run page), Outputs (table with
// status and template filters, link to the product), Metrics (AiMetrics per template: acceptance rate, edited,
// rejected, mean edit distance, rejection reason bars, tokens) and Evaluation (eval cases and eval runs).

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { aiApi } from "../api/client";
import { useAttributes } from "../api/hooks";
import type { AiMetrics, AiOutputStatus, AiRunStatus } from "../api/types";
import { Badge, Empty, ErrorBox, PercentPill, Spinner, Tabs } from "../components/Common";
import { EvaluationTab } from "../ai/Evaluation";
import { OutputStatusPill, RunStatusPill, TaskBadge, shortId } from "../ai/shared";
import { formatDate } from "../lib/format";

const TABS = [
  { key: "runs", label: "Runs" },
  { key: "outputs", label: "Outputs" },
  { key: "metrics", label: "Metrics" },
  { key: "evaluation", label: "Evaluation" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

const RUN_STATUSES: AiRunStatus[] = ["sample_pending", "sample_approved", "running", "completed", "failed", "cancelled"];
const OUTPUT_STATUSES: AiOutputStatus[] = ["proposed", "accepted", "edited", "rejected", "failed", "needs_input", "info"];
// Assumption: list endpoints page 50 rows; the Next button appears while a page is full.
const PAGE_SIZE = 50;

export function AiPage() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const active: TabKey = (TABS.find((t) => t.key === tab)?.key ?? "runs") as TabKey;
  return (
    <div>
      <div className="page-header">
        <h1>AI</h1>
        <span className="muted small">Every AI result is a suggestion until a person accepts it. Templates and brand voice live under Admin, AI.</span>
      </div>
      <Tabs<TabKey> tabs={[...TABS]} value={active} onChange={(k) => navigate(`/ai/${k}`)} />
      {active === "runs" && <RunsTab />}
      {active === "outputs" && <OutputsTab />}
      {active === "metrics" && <MetricsTab />}
      {active === "evaluation" && <EvaluationTab />}
    </div>
  );
}

function Pager({ page, count, onPage }: { page: number; count: number; onPage: (p: number) => void }) {
  if (page <= 1 && count < PAGE_SIZE) return null;
  return (
    <div className="panel-body row" style={{ justifyContent: "flex-end" }}>
      <button className="small" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span className="muted small">Page {page}</span>
      <button className="small" disabled={count < PAGE_SIZE} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </div>
  );
}

function RunsTab() {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ["ai", "runs", { status, page }], queryFn: () => aiApi.runs({ status: status || undefined, page }), refetchInterval: 15_000 });
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Runs</h3>
        <div className="row">
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            {RUN_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          <span className="muted small">{q.data ? `${q.data.total} total` : ""}</span>
        </div>
      </div>
      <div className="panel-body flush">
        {q.isLoading && <Spinner label="Loading runs" />}
        {q.isError && <ErrorBox error={q.error} title="Could not load runs" />}
        {q.data && q.data.rows.length === 0 && (
          <Empty title="No runs yet">Start one from the product grid: select rows, open Bulk actions and choose Run AI.</Empty>
        )}
        {q.data && q.data.rows.length > 0 && (
          <table className="data compact">
            <thead>
              <tr>
                <th>Run</th>
                <th>Kind</th>
                <th>Template</th>
                <th>Task</th>
                <th>Channel</th>
                <th>Status</th>
                <th className="right">Total</th>
                <th className="right">Done</th>
                <th className="right">Proposed</th>
                <th className="right">Failed</th>
                <th className="right">Needs input</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/ai/runs/${encodeURIComponent(r.id)}`} className="mono">
                      {shortId(r.id)}
                    </Link>
                  </td>
                  <td>{r.kind}</td>
                  <td className="mono small">
                    {r.template_code} v{r.template_version}
                  </td>
                  <td>
                    <TaskBadge task={r.task_type} />
                  </td>
                  <td>{r.channel_code || <span className="faint">global</span>}</td>
                  <td>
                    <RunStatusPill status={r.status} />
                  </td>
                  <td className="num">{r.total}</td>
                  <td className="num">{r.done}</td>
                  <td className="num">{r.proposed}</td>
                  <td className="num" style={{ color: r.failed ? "var(--red)" : undefined }}>
                    {r.failed}
                  </td>
                  <td className="num">{r.needs_input}</td>
                  <td className="nowrap small">
                    {formatDate(r.created_at)} <span className="faint">{r.created_by}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {q.data && <Pager page={page} count={q.data.rows.length} onPage={setPage} />}
    </div>
  );
}

function OutputsTab() {
  const [status, setStatus] = useState("");
  const [template, setTemplate] = useState("");
  const [page, setPage] = useState(1);
  const attrs = useAttributes();
  const templates = useQuery({ queryKey: ["ai", "templates", {}], queryFn: () => aiApi.templates() });
  const q = useQuery({
    queryKey: ["ai", "outputs", { status, template_code: template, page }],
    queryFn: () => aiApi.outputs({ status: status || undefined, template_code: template || undefined, page }),
  });
  const attrByCode = useMemo(() => new Map((attrs.data ?? []).map((a) => [a.code, a])), [attrs.data]);
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Outputs</h3>
        <div className="row">
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            {OUTPUT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          <select value={template} onChange={(e) => { setTemplate(e.target.value); setPage(1); }}>
            <option value="">All templates</option>
            {(templates.data ?? []).map((t) => (
              <option key={t.code} value={t.code}>
                {t.label} ({t.code})
              </option>
            ))}
          </select>
          <span className="muted small">{q.data ? `${q.data.total} total` : ""}</span>
        </div>
      </div>
      <div className="panel-body flush">
        {q.isLoading && <Spinner label="Loading outputs" />}
        {q.isError && <ErrorBox error={q.error} title="Could not load outputs" />}
        {q.data && q.data.rows.length === 0 && <Empty title="No outputs">Nothing matches these filters.</Empty>}
        {q.data && q.data.rows.length > 0 && (
          <table className="data compact">
            <thead>
              <tr>
                <th>When</th>
                <th>Product</th>
                <th>Attribute</th>
                <th>Task</th>
                <th>Template</th>
                <th>Status</th>
                <th>Proposed</th>
                <th>Run</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((o) => {
                const text = typeof o.proposed_value === "string" ? o.proposed_value : JSON.stringify(o.proposed_value ?? null);
                return (
                  <tr key={o.id}>
                    <td className="nowrap small">{formatDate(o.created_at)}</td>
                    <td>
                      <Link to={`/products/${encodeURIComponent(o.entity_id)}?attr=${encodeURIComponent(o.attribute_code)}`}>{o.label || o.entity_id}</Link>
                    </td>
                    <td>
                      {attrByCode.get(o.attribute_code)?.label ?? o.attribute_code}
                      {o.channel_code && <Badge>{o.channel_code}</Badge>}
                    </td>
                    <td>
                      <TaskBadge task={o.task_type} />
                    </td>
                    <td className="mono small">
                      {o.template_code} v{o.template_version}
                    </td>
                    <td>
                      <OutputStatusPill status={o.status} />
                      {o.rejection_reason && <div className="faint small">{o.rejection_reason}</div>}
                    </td>
                    <td className="small" style={{ maxWidth: 320 }} title={text}>
                      <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{text}</div>
                    </td>
                    <td>
                      {o.run_id ? (
                        <Link to={`/ai/runs/${encodeURIComponent(o.run_id)}`} className="mono small">
                          {shortId(o.run_id)}
                        </Link>
                      ) : (
                        <span className="faint small">single</span>
                      )}
                    </td>
                    <td className="small">{o.created_by}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {q.data && <Pager page={page} count={q.data.rows.length} onPage={setPage} />}
    </div>
  );
}

function MetricsTab() {
  const [template, setTemplate] = useState("");
  const templates = useQuery({ queryKey: ["ai", "templates", {}], queryFn: () => aiApi.templates() });
  const q = useQuery({ queryKey: ["ai", "metrics", template], queryFn: () => aiApi.metrics(template || undefined) });
  const rows = q.data ?? [];
  return (
    <div className="stack gap16">
      <div className="row">
        <select value={template} onChange={(e) => setTemplate(e.target.value)} title="Show one template per version">
          <option value="">All templates</option>
          {(templates.data ?? []).map((t) => (
            <option key={t.code} value={t.code}>
              {t.label} ({t.code})
            </option>
          ))}
        </select>
        <span className="muted small">Acceptance rate counts accepted and edited outputs over every decided output. Edit distance is characters changed before accepting.</span>
      </div>
      {q.isLoading && <Spinner label="Loading metrics" />}
      {q.isError && <ErrorBox error={q.error} title="Could not load metrics" />}
      {q.data && rows.length === 0 && <Empty title="No metrics yet">Metrics appear once outputs have been accepted, edited or rejected.</Empty>}
      <div className="metrics-grid">
        {rows.map((m) => (
          <MetricsCard key={`${m.template_code}-${m.template_version ?? "all"}`} m={m} label={templates.data?.find((t) => t.code === m.template_code)?.label} />
        ))}
      </div>
    </div>
  );
}

function MetricsCard({ m, label }: { m: AiMetrics; label?: string }) {
  const rate = m.acceptance_rate === null ? null : m.acceptance_rate <= 1 ? m.acceptance_rate * 100 : m.acceptance_rate;
  const maxReason = Math.max(1, ...m.rejection_reasons.map((r) => r.count));
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>
          {label ?? m.template_code}{" "}
          <span className="faint small mono">
            {m.template_code}
            {m.template_version ? ` v${m.template_version}` : ""}
          </span>
        </h3>
        <span title="Acceptance rate">
          <PercentPill value={rate} />
        </span>
      </div>
      <div className="panel-body stack">
        <div className="row gap16" style={{ flexWrap: "wrap" }}>
          <span>
            Outputs <b>{m.outputs}</b>
          </span>
          <span>
            Accepted <b>{m.accepted}</b>
          </span>
          <span>
            Edited <b>{m.edited}</b>
          </span>
          <span>
            Rejected <b>{m.rejected}</b>
          </span>
          <span>
            Pending <b>{m.pending}</b>
          </span>
          <span title="Mean characters changed before accepting">
            Mean edit distance <b>{m.mean_edit_distance === null ? "n/a" : Math.round(m.mean_edit_distance * 10) / 10}</b>
          </span>
        </div>
        <div>
          <div className="muted small mb8">Rejection reasons</div>
          {m.rejection_reasons.length === 0 ? (
            <span className="faint small">No rejections.</span>
          ) : (
            <div className="stack" style={{ gap: 4 }}>
              {m.rejection_reasons
                .slice()
                .sort((a, b) => b.count - a.count)
                .map((r) => (
                  <div key={r.reason} className="reason-row">
                    <span className="small">{r.reason}</span>
                    <div className="bar" title={`${r.count}`}>
                      <div className="seg not-ready" style={{ width: `${(r.count / maxReason) * 100}%` }} />
                    </div>
                    <span className="num small">{r.count}</span>
                  </div>
                ))}
            </div>
          )}
        </div>
        <div className="faint small">
          Tokens: {m.tokens.prompt.toLocaleString()} prompt, {m.tokens.completion.toLocaleString()} completion
        </div>
      </div>
    </div>
  );
}
