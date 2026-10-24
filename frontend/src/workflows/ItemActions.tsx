// DM-07: Advance, Reject and Assign dialogs for a workflow item. Shared by My Work and the product detail panel.

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAttributes, useWorkflows } from "../api/hooks";
import type { WorkflowItem } from "../api/types";
import { Badge, Dialog, ErrorBox, useToast } from "../components/Common";
import { formatDate } from "../lib/format";

type Mode = "advance" | "reject" | "assign" | "cancel" | null;

export function DueTag({ item }: { item: WorkflowItem }) {
  if (!item.due_at) return <span className="faint">no due date</span>;
  return (
    <span className="row" style={{ gap: 4 }}>
      {formatDate(item.due_at, false)}
      {item.overdue && item.state === "open" && <Badge color="red">overdue</Badge>}
    </span>
  );
}

export function StepProgress({ item }: { item: WorkflowItem }) {
  const pos = item.step?.position ?? item.steps_total;
  return (
    <span className="step-progress" title={item.step ? `Step ${pos} of ${item.steps_total}: ${item.step.label}` : "Complete"}>
      {Array.from({ length: Math.max(item.steps_total, 1) }).map((_, i) => (
        <i key={i} className={i + 1 < pos ? "done" : i + 1 === pos && item.state === "open" ? "current" : i + 1 <= pos ? "done" : ""} />
      ))}
    </span>
  );
}

export function useWorkflowItemActions() {
  const qc = useQueryClient();
  const toast = useToast();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["workflows"] });
    qc.invalidateQueries({ queryKey: ["product"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const advance = useMutation({
    mutationFn: ({ id, comment }: { id: string; comment?: string }) => api.workflows.advance(id, comment),
    onSuccess: () => {
      toast("Step completed.", "ok");
      invalidate();
    },
  });
  const reject = useMutation({
    mutationFn: ({ id, toStepId, comment, attributeComments }: { id: string; toStepId: string; comment: string; attributeComments?: { attribute_code: string; comment: string }[] }) =>
      api.workflows.reject(id, { to_step_id: toStepId, comment, attribute_comments: attributeComments?.length ? attributeComments : undefined }),
    onSuccess: () => {
      toast("Sent back to the earlier step.", "ok");
      invalidate();
    },
  });
  const assign = useMutation({
    mutationFn: ({ id, email }: { id: string; email: string }) => api.workflows.assign(id, email),
    onSuccess: () => {
      toast("Assigned.", "ok");
      invalidate();
    },
  });
  const cancel = useMutation({
    mutationFn: (id: string) => api.workflows.cancel(id),
    onSuccess: () => {
      toast("Workflow item cancelled.", "ok");
      invalidate();
    },
  });
  return { advance, reject, assign, cancel };
}

export function ItemActionButtons({ item, compact }: { item: WorkflowItem; compact?: boolean }) {
  const [mode, setMode] = useState<Mode>(null);
  const actions = useWorkflowItemActions();
  if (item.state !== "open") return <span className="faint small">{item.state}</span>;
  const cls = compact ? "small" : "";
  return (
    <>
      <span className="row" style={{ gap: 4 }}>
        <button className={`primary ${cls}`} onClick={() => setMode("advance")}>
          Advance
        </button>
        <button className={cls} onClick={() => setMode("reject")} disabled={!item.step || item.step.position <= 1}>
          Reject
        </button>
        <button className={cls} onClick={() => setMode("assign")}>
          Assign
        </button>
      </span>
      {mode === "advance" && (
        <AdvanceDialog
          item={item}
          busy={actions.advance.isPending}
          error={actions.advance.error}
          onClose={() => setMode(null)}
          onSubmit={(comment) => actions.advance.mutateAsync({ id: item.id, comment }).then(() => setMode(null)).catch(() => undefined)}
        />
      )}
      {mode === "reject" && (
        <RejectDialog
          item={item}
          busy={actions.reject.isPending}
          error={actions.reject.error}
          onClose={() => setMode(null)}
          onSubmit={(toStepId, comment, attributeComments) =>
            actions.reject.mutateAsync({ id: item.id, toStepId, comment, attributeComments }).then(() => setMode(null)).catch(() => undefined)
          }
        />
      )}
      {mode === "assign" && (
        <AssignDialog
          item={item}
          busy={actions.assign.isPending}
          error={actions.assign.error}
          onClose={() => setMode(null)}
          onSubmit={(email) => actions.assign.mutateAsync({ id: item.id, email }).then(() => setMode(null)).catch(() => undefined)}
        />
      )}
    </>
  );
}

function AdvanceDialog({ item, busy, error, onClose, onSubmit }: { item: WorkflowItem; busy: boolean; error: unknown; onClose: () => void; onSubmit: (comment: string) => void }) {
  const [comment, setComment] = useState("");
  const last = !item.step || item.step.position >= item.steps_total;
  return (
    <Dialog
      title={`Complete step: ${item.step?.label ?? "current"}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="primary" disabled={busy} onClick={() => onSubmit(comment)}>
            {busy ? "Working" : last ? "Complete workflow" : "Advance to next step"}
          </button>
        </>
      }
    >
      <div className="stack">
        <div className="muted small">
          {item.entity_label}, {item.workflow_label}, step {item.step?.position ?? item.steps_total} of {item.steps_total}
          {item.step?.kind ? ` (${item.step.kind})` : ""}.
        </div>
        <label className="field">
          Comment (optional)
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} autoFocus />
        </label>
        {!!error && <ErrorBox error={error} title="Could not advance" />}
      </div>
    </Dialog>
  );
}

function RejectDialog({
  item,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  item: WorkflowItem;
  busy: boolean;
  error: unknown;
  onClose: () => void;
  onSubmit: (toStepId: string, comment: string, attributeComments: { attribute_code: string; comment: string }[]) => void;
}) {
  const workflows = useWorkflows();
  const attrs = useAttributes();
  const [toStep, setToStep] = useState("");
  const [comment, setComment] = useState("");
  const [attrComments, setAttrComments] = useState<{ attribute_code: string; comment: string }[]>([]);
  const def = workflows.data?.find((w) => w.code === item.workflow_code);
  const earlier = useMemo(
    () => (def?.steps ?? []).filter((s) => s.position < (item.step?.position ?? Infinity)).sort((a, b) => a.position - b.position),
    [def, item.step],
  );
  // Attributes the current step covers come first (its groups), then every other attribute.
  const stepGroups = new Set(item.step?.group_codes ?? []);
  const attrOptions = (attrs.data ?? []).slice().sort((a, b) => Number(stepGroups.has(b.group_code)) - Number(stepGroups.has(a.group_code)) || a.label.localeCompare(b.label));
  const effectiveStep = toStep || (earlier.length ? String(earlier[earlier.length - 1].id ?? earlier[earlier.length - 1].position) : "");
  return (
    <Dialog
      title="Send back to an earlier step"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="primary" disabled={busy || !effectiveStep || !comment.trim()} onClick={() => onSubmit(effectiveStep, comment.trim(), attrComments.filter((c) => c.attribute_code && c.comment.trim()))}>
            {busy ? "Working" : "Reject"}
          </button>
        </>
      }
    >
      <div className="stack">
        <label className="field">
          Back to step
          {workflows.isError && <ErrorBox error={workflows.error} title="Could not load the workflow definition" />}
          <select value={effectiveStep} onChange={(e) => setToStep(e.target.value)}>
            {earlier.length === 0 && <option value="">No earlier step</option>}
            {earlier.map((s) => (
              <option key={s.id ?? s.position} value={String(s.id ?? s.position)}>
                {s.position}. {s.label} ({s.role_code})
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Comment (required)
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} autoFocus placeholder="What needs to change" />
        </label>
        <div>
          <div className="muted small mb8">Per-attribute comments (optional)</div>
          <div className="stack" style={{ gap: 4 }}>
            {attrComments.map((c, i) => (
              <div className="row nowrap" key={i}>
                <select value={c.attribute_code} onChange={(e) => setAttrComments((a) => a.map((x, j) => (j === i ? { ...x, attribute_code: e.target.value } : x)))}>
                  <option value="">Attribute</option>
                  {attrOptions.map((a) => (
                    <option key={a.code} value={a.code}>
                      {a.label}
                    </option>
                  ))}
                </select>
                <input className="grow" value={c.comment} placeholder="Comment" onChange={(e) => setAttrComments((a) => a.map((x, j) => (j === i ? { ...x, comment: e.target.value } : x)))} />
                <button className="icon small" onClick={() => setAttrComments((a) => a.filter((_, j) => j !== i))} aria-label="Remove">
                  &times;
                </button>
              </div>
            ))}
            <div>
              <button className="small" onClick={() => setAttrComments((a) => [...a, { attribute_code: "", comment: "" }])}>
                + Add attribute comment
              </button>
            </div>
          </div>
        </div>
        {!!error && <ErrorBox error={error} title="Could not reject" />}
      </div>
    </Dialog>
  );
}

function AssignDialog({ item, busy, error, onClose, onSubmit }: { item: WorkflowItem; busy: boolean; error: unknown; onClose: () => void; onSubmit: (email: string) => void }) {
  const [email, setEmail] = useState(item.assigned_email ?? "");
  const valid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  return (
    <Dialog
      title="Assign this step"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="primary" disabled={busy || !valid} onClick={() => onSubmit(email.trim())}>
            {busy ? "Working" : "Assign"}
          </button>
        </>
      }
    >
      <div className="stack">
        <div className="muted small">
          {item.entity_label}, {item.step?.label ?? "current step"}, role {item.step?.role_code ?? item.assigned_role ?? "any"}.
        </div>
        <label className="field">
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus placeholder="first.last@swimusa.com" />
        </label>
        {!!error && <ErrorBox error={error} title="Could not assign" />}
      </div>
    </Dialog>
  );
}
