// DM-08: Approval queue grouped by submitter, field-level current vs proposed, approve or reject with comment.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAttributes, useGroups, useMe, useOptionLists } from "../api/hooks";
import { Dialog, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { displayValue, formatDate } from "../lib/format";
import type { OptionList } from "../api/types";

export function ApprovalsPage() {
  const [group, setGroup] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);
  const [comment, setComment] = useState("");
  const qc = useQueryClient();
  const toast = useToast();
  const me = useMe();

  const q = useQuery({ queryKey: ["approvals", group], queryFn: () => api.approvals.queue(group || undefined) });
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
