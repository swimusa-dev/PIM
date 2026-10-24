// AI-04: Bulk AI run page. Header with template, status pill, counts and progress; the sample outputs as review
// cards; "Approve samples and run the rest" and "Cancel"; once running or completed, the outputs table with a
// status filter, per-output accept / reject and "Accept all" for users with approve rights on the target group.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { aiApi } from "../api/client";
import { canApprove, useAttributes, useMe, useOptionLists } from "../api/hooks";
import type { AiOutput, AiOutputStatus, OptionList } from "../api/types";
import { Badge, Confirm, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { OutputCard } from "../ai/OutputCard";
import { AiError, OutputStatusPill, RunStatusPill, TaskBadge, shortId } from "../ai/shared";
import { formatDate } from "../lib/format";

const OUTPUT_STATUSES: AiOutputStatus[] = ["proposed", "accepted", "edited", "rejected", "failed", "needs_input", "info"];
// Assumption: GET /api/ai/outputs pages 50 rows; the Next button appears while a page is full.
const OUTPUT_PAGE_SIZE = 50;

export function AiRunPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const me = useMe();
  const attrs = useAttributes();
  const optionLists = useOptionLists();
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [confirm, setConfirm] = useState<"accept_all" | "cancel" | null>(null);

  const run = useQuery({
    queryKey: ["ai", "run", id],
    queryFn: () => aiApi.run(id),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "running" || s === "sample_approved" ? 3000 : false;
    },
  });
  const r = run.data;
  const listMode = !!r && (r.status === "running" || r.status === "completed" || r.status === "sample_approved" || r.status === "failed" || r.status === "cancelled");
  const outputs = useQuery({
    queryKey: ["ai", "outputs", { run_id: id, status: statusFilter, page }],
    queryFn: () => aiApi.outputs({ run_id: id, status: statusFilter || undefined, page }),
    enabled: listMode,
    refetchInterval: r?.status === "running" ? 5000 : false,
  });

  const attrByCode = useMemo(() => new Map((attrs.data ?? []).map((a) => [a.code, a])), [attrs.data]);
  const listByCode = useMemo(() => {
    const m: Record<string, OptionList> = {};
    for (const l of optionLists.data ?? []) m[l.code] = l;
    return m;
  }, [optionLists.data]);

  const samples = useMemo(() => {
    if (!r) return [];
    const ids = new Set(r.sample_entity_ids);
    const all = r.outputs ?? [];
    const s = all.filter((o) => ids.has(o.entity_id));
    return s.length ? s : all.slice(0, 5);
  }, [r]);
  const targetCodes = useMemo(() => {
    const codes = new Set<string>();
    for (const o of r?.outputs ?? []) codes.add(o.attribute_code);
    for (const o of outputs.data?.rows ?? []) codes.add(o.attribute_code);
    return Array.from(codes);
  }, [r, outputs.data]);
  const canAcceptAll = targetCodes.length > 0 && targetCodes.every((c) => canApprove(me.data, attrByCode.get(c)));

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["ai"] });
    qc.invalidateQueries({ queryKey: ["approvals"] });
    qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
  };
  const approve = useMutation({
    mutationFn: () => aiApi.approveSamples(id),
    onSuccess: () => {
      toast("Samples approved. The rest of the selection is running.", "ok");
      invalidate();
    },
  });
  const cancel = useMutation({
    mutationFn: () => aiApi.cancelRun(id),
    onSuccess: () => {
      toast("Run cancelled.", "warn");
      setConfirm(null);
      invalidate();
    },
    onError: (e) => toast(`Cancel failed: ${(e as Error).message}`, "error"),
  });
  const acceptAll = useMutation({
    mutationFn: () => aiApi.acceptAll(id),
    onSuccess: (res) => {
      toast(`Accepted ${res.accepted}, skipped ${res.skipped}.`, "ok");
      setConfirm(null);
      invalidate();
    },
    onError: (e) => toast(`Accept all failed: ${(e as Error).message}`, "error"),
  });
  const decide = useMutation({
    mutationFn: ({ o, action }: { o: AiOutput; action: "accept" | "reject" }) =>
      action === "accept" ? aiApi.accept(o.id) : aiApi.reject(o.id, "Rejected from the run page"),
    onSuccess: invalidate,
    onError: (e) => toast(`Action failed: ${(e as Error).message}`, "error"),
  });

  const onSampleUpdated = (next: AiOutput, replacedId?: string) => {
    qc.setQueryData(["ai", "run", id], (prev: typeof r) => {
      if (!prev) return prev;
      const rid = replacedId ?? next.id;
      const ix = prev.outputs.findIndex((o) => o.id === rid);
      const copy = prev.outputs.slice();
      if (ix < 0) copy.unshift(next);
      else copy[ix] = next;
      return { ...prev, outputs: copy };
    });
  };

  if (run.isLoading) return <Spinner label="Loading run" />;
  if (run.isError) return <ErrorBox error={run.error} title="Could not load the run" />;
  if (!r) return null;

  const progress = r.total > 0 ? Math.min(100, Math.round((r.done / r.total) * 100)) : 0;
  const selection = r.selection ?? {};
  const selectionText =
    typeof selection.view_id === "string" ? `view ${selection.view_id}` : Array.isArray(selection.entity_ids) ? `${selection.entity_ids.length} selected products` : "selection";

  return (
    <div className="stack gap16">
      <div className="page-header">
        <div>
          <div className="muted small">
            <Link to="/ai">AI</Link> / Runs
          </div>
          <h1 className="row">
            Run {shortId(r.id)} <RunStatusPill status={r.status} /> <TaskBadge task={r.task_type} />
          </h1>
        </div>
        <div className="actions">
          {r.status === "sample_pending" && (
            <button className="primary" disabled={approve.isPending} onClick={() => approve.mutate()}>
              {approve.isPending ? "Starting" : "Approve samples and run the rest"}
            </button>
          )}
          {(r.status === "sample_pending" || r.status === "sample_approved" || r.status === "running") && (
            <button className="danger" disabled={cancel.isPending} onClick={() => setConfirm("cancel")}>
              Cancel
            </button>
          )}
          {listMode && (
            <button
              className="primary"
              disabled={!canAcceptAll || acceptAll.isPending || r.proposed === 0}
              title={canAcceptAll ? "Approve every proposed suggestion of this run" : "Needs approve rights on the target attribute group"}
              onClick={() => setConfirm("accept_all")}
            >
              Accept all ({r.proposed})
            </button>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-body">
          <dl className="kv run-kv">
            <dt>Template</dt>
            <dd>
              <span className="mono">
                {r.template_code} v{r.template_version}
              </span>{" "}
              <Link to="/admin/ai" className="small">
                manage
              </Link>
            </dd>
            <dt>Channel</dt>
            <dd>{r.channel_code || <span className="faint">global</span>}</dd>
            <dt>Selection</dt>
            <dd>{selectionText}</dd>
            <dt>Created</dt>
            <dd>
              {formatDate(r.created_at)} by {r.created_by}
              {r.finished_at ? `, finished ${formatDate(r.finished_at)}` : ""}
            </dd>
            <dt>Counts</dt>
            <dd className="row" style={{ gap: 10 }}>
              <span>
                Total <b>{r.total}</b>
              </span>
              <span>
                Done <b>{r.done}</b>
              </span>
              <span>
                Proposed <b>{r.proposed}</b>
              </span>
              <span style={{ color: r.failed ? "var(--red)" : undefined }}>
                Failed <b>{r.failed}</b>
              </span>
              <span>
                Needs input <b>{r.needs_input}</b>
              </span>
              {r.job_run_id && <span className="faint small mono">job {r.job_run_id}</span>}
            </dd>
            <dt>Progress</dt>
            <dd>
              <div className="bar" title={`${r.done} of ${r.total}`}>
                <div className="seg ready" style={{ width: `${progress}%` }} />
              </div>
              <span className="faint small">{progress}%</span>
            </dd>
          </dl>
          {r.error && <div className="banner error boxed mt8">{r.error}</div>}
          <AiError error={approve.error} title="Could not approve the samples" />
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Sample outputs</h3>
          <span className="muted small">
            {r.status === "sample_pending" ? "Review these before running the rest of the selection." : `${samples.length} samples`}
          </span>
        </div>
        <div className="panel-body stack">
          {samples.length === 0 && <Empty title="No sample outputs">The run produced no samples. Check the error above or the template inputs.</Empty>}
          {samples.map((o) => (
            <OutputCard key={o.id} output={o} attrByCode={attrByCode} optionLists={listByCode} onUpdated={onSampleUpdated} showProduct />
          ))}
        </div>
      </div>

      {listMode && (
        <div className="panel">
          <div className="panel-header">
            <h3>Outputs</h3>
            <div className="row">
              <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}>
                <option value="">All statuses</option>
                {OUTPUT_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
              <span className="muted small">{outputs.data ? `${outputs.data.total} total` : ""}</span>
            </div>
          </div>
          <div className="panel-body flush">
            {outputs.isLoading && <Spinner label="Loading outputs" />}
            {outputs.isError && <ErrorBox error={outputs.error} title="Could not load outputs" />}
            {outputs.data && outputs.data.rows.length === 0 && <div className="empty">No outputs{statusFilter ? " with this status" : " yet"}.</div>}
            {outputs.data && outputs.data.rows.length > 0 && (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>Attribute</th>
                    <th>Status</th>
                    <th>Proposed</th>
                    <th>Issues</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {outputs.data.rows.map((o) => {
                    const a = attrByCode.get(o.attribute_code);
                    const text = typeof o.proposed_value === "string" ? o.proposed_value : JSON.stringify(o.proposed_value ?? null);
                    return (
                      <tr key={o.id}>
                        <td>
                          <Link to={`/products/${encodeURIComponent(o.entity_id)}`}>{o.label || o.entity_id}</Link>
                        </td>
                        <td>
                          {a?.label ?? o.attribute_code}
                          {o.channel_code && <Badge>{o.channel_code}</Badge>}
                        </td>
                        <td>
                          <OutputStatusPill status={o.status} />
                        </td>
                        <td className="small" style={{ maxWidth: 360 }} title={text}>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{text}</div>
                        </td>
                        <td className="small">
                          {o.grounding_errors.length > 0 && <Badge color="red">{o.grounding_errors.length} grounding</Badge>}{" "}
                          {o.needs_input.length > 0 && <Badge color="purple">needs {o.needs_input.map((c) => attrByCode.get(c)?.label ?? c).join(", ")}</Badge>}
                        </td>
                        <td className="nowrap">
                          {o.status === "proposed" && (
                            <>
                              <button className="small primary" disabled={decide.isPending} onClick={() => decide.mutate({ o, action: "accept" })}>
                                Accept
                              </button>{" "}
                              <button className="small danger" disabled={decide.isPending} onClick={() => decide.mutate({ o, action: "reject" })}>
                                Reject
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
          {outputs.data && (page > 1 || outputs.data.rows.length >= OUTPUT_PAGE_SIZE) && (
            <div className="panel-body row" style={{ justifyContent: "flex-end" }}>
              <button className="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </button>
              <span className="muted small">Page {page}</span>
              <button className="small" disabled={outputs.data.rows.length < OUTPUT_PAGE_SIZE} onClick={() => setPage((p) => p + 1)}>
                Next
              </button>
            </div>
          )}
        </div>
      )}

      {confirm === "cancel" && (
        <Confirm
          title="Cancel this run?"
          message="Products not yet processed are skipped. Suggestions already produced stay in the queue."
          confirmLabel="Cancel run"
          busy={cancel.isPending}
          onCancel={() => setConfirm(null)}
          onConfirm={() => cancel.mutate()}
        />
      )}
      {confirm === "accept_all" && (
        <Confirm
          title={`Accept all ${r.proposed} proposed suggestions?`}
          message="Every proposed draft of this run is approved and replaces the current values. Outputs with grounding errors or missing inputs are not proposed, so they are not included."
          confirmLabel="Accept all"
          busy={acceptAll.isPending}
          onCancel={() => setConfirm(null)}
          onConfirm={() => acceptAll.mutate()}
        />
      )}
    </div>
  );
}
