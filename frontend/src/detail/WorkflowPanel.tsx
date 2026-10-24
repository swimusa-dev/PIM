// DM-07: Workflow panel on the product detail page. Open items with Advance / Reject / Assign, plus "Start workflow".

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { rowsOf, useWorkflows } from "../api/hooks";
import { Badge, ErrorBox, Spinner, useToast } from "../components/Common";
import { DueTag, ItemActionButtons, StepProgress } from "../workflows/ItemActions";
import { formatDate } from "../lib/format";

export function WorkflowPanel({ entityId }: { entityId: string }) {
  const q = useQuery({ queryKey: ["product", entityId, "workflow"], queryFn: () => api.workflows.forProduct(entityId) });
  const workflows = useWorkflows();
  const qc = useQueryClient();
  const toast = useToast();
  const [startCode, setStartCode] = useState("");
  const start = useMutation({
    mutationFn: () => api.workflows.start(startCode, [entityId]),
    onSuccess: () => {
      toast("Workflow started.", "ok");
      setStartCode("");
      qc.invalidateQueries({ queryKey: ["product", entityId, "workflow"] });
      qc.invalidateQueries({ queryKey: ["workflows"] });
    },
    onError: (e) => toast(`Could not start the workflow: ${(e as Error).message}`, "error"),
  });
  const items = rowsOf(q.data);
  const open = items.filter((i) => i.state === "open");

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Workflow</h3>
        <span className="muted small">{open.length} open</span>
      </div>
      <div className="panel-body stack">
        {q.isLoading && <Spinner />}
        {q.isError && <ErrorBox error={q.error} title="Could not load workflow items" />}
        {q.data && items.length === 0 && <div className="muted small">No workflow items for this product.</div>}
        {items.map((it) => (
          <div key={it.id} className="step-card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <b>{it.workflow_label}</b>
              <StepProgress item={it} />
            </div>
            <div className="row small" style={{ gap: 6 }}>
              {it.step ? (
                <>
                  <span>
                    {it.step.position}. {it.step.label}
                  </span>
                  <Badge>{it.step.kind}</Badge>
                  <span className="faint">role {it.step.role_code}</span>
                </>
              ) : (
                <Badge color={it.state === "done" ? "green" : undefined}>{it.state}</Badge>
              )}
            </div>
            <div className="row small" style={{ gap: 6 }}>
              <DueTag item={it} />
              <span className="faint">{it.assigned_email ?? it.assigned_role ?? "unassigned"}</span>
            </div>
            {it.history.length > 0 && (
              <div className="faint small mt8" title={it.history.map((h) => `${formatDate(h.at)} ${h.event}${h.step ? ` (${h.step})` : ""}${h.by ? ` by ${h.by}` : ""}${h.comment ? `: ${h.comment}` : ""}`).join("\n")}>
                Last: {it.history[it.history.length - 1].event}
                {it.history[it.history.length - 1].by ? ` by ${it.history[it.history.length - 1].by}` : ""} at {formatDate(it.history[it.history.length - 1].at)}
                {it.history[it.history.length - 1].comment ? ` "${it.history[it.history.length - 1].comment}"` : ""}
              </div>
            )}
            <div className="mt8">
              <ItemActionButtons item={it} compact />
            </div>
          </div>
        ))}
        {workflows.data && workflows.data.length > 0 && (
          <div className="row">
            <select value={startCode} onChange={(e) => setStartCode(e.target.value)}>
              <option value="">Start a workflow</option>
              {workflows.data
                .filter((w) => w.enabled)
                .map((w) => (
                  <option key={w.code} value={w.code}>
                    {w.label}
                  </option>
                ))}
            </select>
            <button className="small" disabled={!startCode || start.isPending} onClick={() => start.mutate()}>
              Start
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
