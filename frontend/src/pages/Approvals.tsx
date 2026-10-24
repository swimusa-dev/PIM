// DM-08, AI-04: Approval queue grouped by submitter, field-level current vs proposed, approve or reject with comment.
// Phase 4 adds a Run filter (AI runs with drafts in the queue), run and template chips on items, and "Accept all in
// run" (POST /api/ai/runs/{id}/accept-all) for approvers.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { aiApi, api } from "../api/client";
import { canApprove, useAttributes, useGroups, useMe, useOptionLists } from "../api/hooks";
import { Badge, Confirm, Dialog, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { shortId } from "../ai/shared";
import { displayValue, formatDate } from "../lib/format";
import type { OptionList } from "../api/types";

export function ApprovalsPage() {
  const [group, setGroup] = useState("");
  const [runId, setRunId] = useState("");
  const [confirmAcceptAll, setConfirmAcceptAll] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);
  const [comment, setComment] = useState("");
  const qc = useQueryClient();
  const toast = useToast();
  const me = useMe();

  const q = useQuery({ queryKey: ["approvals", group, runId], queryFn: () => api.approvals.queue(group || undefined, runId || undefined) });
  const attrs = useAttributes();
  const groups = useGroups();
  const optionLists = useOptionLists();

  const attrByCode = useMemo(() => new Map((attrs.data ?? []).map((a) => [a.code, a])), [attrs.data]);
  const listByCode = useMemo(() => {
    const m: Record<string, OptionList> = {};
    for (const l of optionLists.data ?? []) m[l.code] = l;
    return m;
  }, [optionLists.data]);

  // Only groups where the user has approve rights are decidable; the list filter shows those first.
  const approvableGroups = useMemo(
    () => (groups.data ?? []).filter((g) => me.data?.data_rights[g.code] === "approve"),
    [groups.data, me.data],
  );

  const decide = useMutation({
    mutationFn: () => api.approvals.decide(Array.from(selected), decision!, comment),
    onSuccess: () => {
      toast(`${selected.size} change${selected.size === 1 ? "" : "s"} ${decision === "approve" ? "approved" : "rejected"}`, "ok");
      setSelected(new Set());
      setDecision(null);
      setComment("");
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (e) => toast(`Decision failed: ${String((e as Error).message)}`, "error"),
  });

  const allIds = useMemo(() => (q.data?.groups ?? []).flatMap((g) => g.items.map((i) => i.draft_id)), [q.data]);

  // AI-04: runs come with the response; keep the last non-empty list so the filter does not vanish while filtered.
  const runs = useMemo(() => q.data?.runs ?? [], [q.data]);
  const runById = useMemo(() => new Map(runs.map((r) => [r.run_id, r])), [runs]);
  const selectedRun = runById.get(runId);
  // Accept all needs approve rights on every group the run writes; the server checks again.
  const runItems = useMemo(() => (q.data?.groups ?? []).flatMap((g) => g.items).filter((i) => !runId || i.run_id === runId), [q.data, runId]);
  const canAcceptAll =
    !!runId && runItems.length > 0 && runItems.every((i) => canApprove(me.data, attrByCode.get(i.attribute_code)));
  const acceptAll = useMutation({
    mutationFn: () => aiApi.acceptAll(runId),
    onSuccess: (r) => {
      toast(`Accepted ${r.accepted} suggestion${r.accepted === 1 ? "" : "s"}${r.skipped ? `, skipped ${r.skipped}` : ""}.`, "ok");
      setConfirmAcceptAll(false);
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["ai"] });
      qc.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (e) => toast(`Accept all failed: ${String((e as Error).message)}`, "error"),
  });
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const toggleGroup = (ids: string[]) =>
    setSelected((s) => {
      const n = new Set(s);
      const all = ids.every((i) => n.has(i));
      ids.forEach((i) => (all ? n.delete(i) : n.add(i)));
      return n;
    });

  return (
    <div>
      <div className="page-header">
        <h1>Approvals</h1>
        <div className="actions">
          <select value={group} onChange={(e) => setGroup(e.target.value)} title="Filter by attribute group">
            <option value="">All attribute groups</option>
            {(groups.data ?? []).map((g) => (
              <option key={g.code} value={g.code}>
                {g.label}
                {approvableGroups.some((a) => a.code === g.code) ? "" : " (view only)"}
              </option>
            ))}
          </select>
          <select value={runId} onChange={(e) => { setRunId(e.target.value); setSelected(new Set()); }} title="Filter by AI run" disabled={runs.length === 0 && !runId}>
            <option value="">All sources{runs.length ? "" : " (no AI runs in the queue)"}</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                Run {shortId(r.run_id)}: {r.template_code} ({r.count})
              </option>
            ))}
            {runId && !runById.has(runId) && <option value={runId}>Run {shortId(runId)}</option>}
          </select>
          {runId && (
            <button
              className="primary"
              disabled={!canAcceptAll || acceptAll.isPending}
              title={canAcceptAll ? "Approve every proposed draft of this run" : "Needs approve rights on every attribute group the run writes"}
              onClick={() => setConfirmAcceptAll(true)}
            >
              Accept all in run
            </button>
          )}
          <button onClick={() => setSelected(new Set(allIds))} disabled={allIds.length === 0}>
            Select all
          </button>
          <button onClick={() => setSelected(new Set())} disabled={selected.size === 0}>
            Clear
          </button>
          <button className="primary" disabled={selected.size === 0} onClick={() => setDecision("approve")}>
            Approve {selected.size > 0 ? `(${selected.size})` : ""}
          </button>
          <button className="danger" disabled={selected.size === 0} onClick={() => setDecision("reject")}>
            Reject {selected.size > 0 ? `(${selected.size})` : ""}
          </button>
        </div>
      </div>

      {q.isLoading && <Spinner label="Loading approval queue" />}
      {q.isError && <ErrorBox error={q.error} title="Could not load approvals" />}
      {q.data && q.data.groups.length === 0 && (
        <Empty title="The approval queue is empty">
          Drafts submitted by users with edit rights but not approve rights will appear here grouped by submitter.
        </Empty>
      )}

      <div className="stack gap16">
        {(q.data?.groups ?? []).map((g) => {
          const ids = g.items.map((i) => i.draft_id);
          const allSel = ids.length > 0 && ids.every((i) => selected.has(i));
          return (
            <div className="panel" key={g.submitter}>
              <div className="panel-header">
                <label className="inline">
                  <input type="checkbox" checked={allSel} onChange={() => toggleGroup(ids)} />
                  <h3>{g.submitter}</h3>
                  <span className="badge">{g.items.length}</span>
                </label>
              </div>
              <div className="panel-body flush">
                <table className="data compact">
                  <thead>
                    <tr>
                      <th style={{ width: 32 }} />
                      <th>Product</th>
                      <th>Attribute</th>
                      <th>Current</th>
                      <th>Proposed</th>
                      <th>Submitted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.items.map((it) => {
                      const attr = attrByCode.get(it.attribute_code);
                      return (
                        <tr key={it.draft_id} className={selected.has(it.draft_id) ? "selected" : ""}>
                          <td>
                            <input type="checkbox" checked={selected.has(it.draft_id)} onChange={() => toggle(it.draft_id)} />
                          </td>
                          <td>
                            <Link to={`/products/${encodeURIComponent(it.entity_id)}`}>{it.label}</Link>
                            {it.run_id && (
                              <div className="chips" style={{ marginTop: 2 }}>
                                <Link to={`/ai/runs/${encodeURIComponent(it.run_id)}`} className="badge purple" title="Open the AI run">
                                  run {shortId(it.run_id)}
                                </Link>
                                {runById.get(it.run_id)?.template_code && <Badge title="Prompt template">{runById.get(it.run_id)!.template_code}</Badge>}
                              </div>
                            )}
                          </td>
                          <td>
                            {attr?.label ?? it.attribute_code}
                            <div className="faint mono small">{it.attribute_code}</div>
                          </td>
                          <td className="pre">
                            <span className="diff-old">{displayValue(it.current, attr, listByCode) || "(empty)"}</span>
                          </td>
                          <td className="pre">
                            <span className="diff-new">{displayValue(it.proposed, attr, listByCode) || "(cleared)"}</span>
                          </td>
                          <td className="nowrap muted">{formatDate(it.set_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })}
      </div>

      {confirmAcceptAll && (
        <Confirm
          title="Accept all suggestions in this run?"
          message={`Every proposed draft of run ${shortId(runId)}${selectedRun ? ` (${selectedRun.template_code}, ${selectedRun.count} in the queue)` : ""} is approved and replaces the current values. Drafts already decided are skipped.`}
          confirmLabel="Accept all"
          busy={acceptAll.isPending}
          onCancel={() => setConfirmAcceptAll(false)}
          onConfirm={() => acceptAll.mutate()}
        />
      )}
      {decision && (
        <Dialog
          title={decision === "approve" ? "Approve changes" : "Reject changes"}
          onClose={() => setDecision(null)}
          footer={
            <>
              <button onClick={() => setDecision(null)}>Cancel</button>
              <button
                className={decision === "approve" ? "primary" : "danger"}
                disabled={decide.isPending || (decision === "reject" && comment.trim() === "")}
                onClick={() => decide.mutate()}
              >
                {decide.isPending ? "Saving" : decision === "approve" ? `Approve ${selected.size}` : `Reject ${selected.size}`}
              </button>
            </>
          }
        >
          <p>
            {decision === "approve"
              ? `The ${selected.size} selected proposed value${selected.size === 1 ? "" : "s"} will replace the current value${selected.size === 1 ? "" : "s"}. Draft history is kept.`
              : `The ${selected.size} selected draft${selected.size === 1 ? "" : "s"} will be rejected and the submitter notified. A comment is required.`}
          </p>
          <label className="field">
            Comment {decision === "reject" ? "(required)" : "(optional)"}
            <textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Why this decision was made" />
          </label>
          {decide.isError && <ErrorBox error={decide.error} />}
        </Dialog>
      )}
    </div>
  );
}
