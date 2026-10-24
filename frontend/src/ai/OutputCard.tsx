// AI-03, AI-05, AI-06: one AiOutput as a review card. Current and proposed value side by side, the word-level
// diff, grounding errors, NEEDS_INPUT chips (linking to the attribute in the form), confidence for classify,
// check findings as a list (no accept for info outputs), and the actions Accept, Edit then accept (ValueEditor by
// data type where practical, else a textarea), Regenerate (optional note) and Reject (reason required, quick reasons).

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { aiApi } from "../api/client";
import type { AiOutput, AttributeDefinition, OptionList } from "../api/types";
import { AiBadge, Badge, Dialog, ErrorBox } from "../components/Common";
import { ValueEditor } from "../components/ValueEditor";
import { displayValue, formatDate } from "../lib/format";
import { ConfidencePill, DiffView, OutputStatusPill, QUICK_REJECT_REASONS, TaskBadge, shortId } from "./shared";

export function OutputCard({
  output,
  attrByCode,
  optionLists,
  onUpdated,
  onGoToAttribute,
  showProduct,
  readOnly,
}: {
  output: AiOutput;
  attrByCode: Map<string, AttributeDefinition>;
  optionLists: Record<string, OptionList>;
  /** Called with the output returned by the server; `replacedId` is set when a regenerate produced a new output. */
  onUpdated?: (next: AiOutput, replacedId?: string) => void;
  /** Focuses the attribute in the form (NEEDS_INPUT chips). When absent the chip links to the product page. */
  onGoToAttribute?: (code: string) => void;
  showProduct?: boolean;
  readOnly?: boolean;
}) {
  const qc = useQueryClient();
  const attr = attrByCode.get(output.attribute_code);
  const [mode, setMode] = useState<"idle" | "edit" | "reject" | "regenerate">("idle");
  const [editValue, setEditValue] = useState<unknown>(output.proposed_value);
  const [reason, setReason] = useState("");
  const [otherReason, setOtherReason] = useState("");
  const [note, setNote] = useState("");

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["ai"] });
    qc.invalidateQueries({ queryKey: ["product", output.entity_id] });
    qc.invalidateQueries({ queryKey: ["approvals"] });
    qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
  };
  const accept = useMutation({
    mutationFn: (value?: unknown) => aiApi.accept(output.id, value),
    onSuccess: (o) => {
      setMode("idle");
      onUpdated?.(o);
      invalidate();
    },
  });
  const reject = useMutation({
    mutationFn: (r: string) => aiApi.reject(output.id, r),
    onSuccess: (o) => {
      setMode("idle");
      setReason("");
      setOtherReason("");
      onUpdated?.(o);
      invalidate();
    },
  });
  const regenerate = useMutation({
    mutationFn: (n?: string) => aiApi.regenerate(output.id, n),
    onSuccess: (o) => {
      setMode("idle");
      setNote("");
      onUpdated?.(o, output.id);
      invalidate();
    },
  });
  const busy = accept.isPending || reject.isPending || regenerate.isPending;
  const error = accept.error ?? reject.error ?? regenerate.error;

  const isCheck = output.task_type === "check";
  const isInfo = output.status === "info";
  const canAccept = !readOnly && output.status === "proposed" && !isInfo;
  const canReject = !readOnly && (output.status === "proposed" || output.status === "needs_input");
  const canRegenerate = !readOnly && (output.status === "proposed" || output.status === "needs_input" || output.status === "failed" || output.status === "info");
  const isTextual = typeof output.proposed_value === "string" || output.proposed_value === null || output.proposed_value === undefined;
  const useTextarea = !attr || attr.data_type === "text" || attr.data_type === "rich_text" || (isTextual && String(output.proposed_value ?? "").length > 80);
  const finalReason = reason === "Other" ? otherReason.trim() : reason;

  const valueText = (v: unknown) => displayValue(v, attr, optionLists);

  return (
    <div className={`ai-card status-${output.status}`}>
      <div className="ai-card-head">
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          <b>{attr?.label ?? output.attribute_code}</b>
          <span className="faint mono small">{output.attribute_code}</span>
          {output.channel_code && <Badge title="Channel">{output.channel_code}</Badge>}
          <TaskBadge task={output.task_type} />
          <OutputStatusPill status={output.status} />
          {output.task_type === "classify" && <ConfidencePill value={output.confidence} />}
          {(output.status === "accepted" || output.status === "edited") && <AiBadge />}
        </div>
        <div className="faint small nowrap" title={`Model ${output.model}, ${output.prompt_tokens} prompt and ${output.completion_tokens} completion tokens, ${output.latency_ms} ms`}>
          {output.template_code} v{output.template_version}
          {output.run_id && (
            <>
              {" "}
              <Link to={`/ai/runs/${encodeURIComponent(output.run_id)}`} title="Open the run">
                run {shortId(output.run_id)}
              </Link>
            </>
          )}
          {" "}
          {formatDate(output.created_at)}
        </div>
      </div>
      {showProduct && (
        <div className="small">
          <Link to={`/products/${encodeURIComponent(output.entity_id)}`}>{output.label || output.entity_id}</Link>
        </div>
      )}

      {isCheck ? (
        <div className="stack" style={{ gap: 4 }}>
          <div className="muted small">Value checked</div>
          <div className="pre">{valueText(output.current_value) || <span className="faint">empty</span>}</div>
          <div className="muted small">Findings</div>
          {(output.check_findings ?? []).length === 0 ? (
            <div className="faint">No findings. The value passed every check.</div>
          ) : (
            <ul className="findings">
              {(output.check_findings ?? []).map((f, i) => (
                <li key={i} className={f.severity}>
                  <Badge color={f.severity === "error" ? "red" : "amber"}>{f.severity}</Badge> <span className="mono small">{f.kind}</span> {f.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="ai-values">
          <div>
            <div className="muted small">Current</div>
            <div className="pre">{valueText(output.current_value) || <span className="faint">empty</span>}</div>
          </div>
          <div>
            <div className="muted small">Proposed</div>
            {mode === "edit" ? (
              <div className="stack">
                {useTextarea ? (
                  <textarea
                    value={typeof editValue === "string" ? editValue : editValue === null || editValue === undefined ? "" : JSON.stringify(editValue)}
                    rows={6}
                    onChange={(e) => setEditValue(e.target.value)}
                    maxLength={attr?.validation?.max_length}
                  />
                ) : (
                  <ValueEditor
                    attr={attr!}
                    optionList={attr!.option_list_code ? optionLists[attr!.option_list_code] : undefined}
                    value={editValue}
                    onCommit={(v) => setEditValue(v)}
                  />
                )}
                {attr?.validation?.max_length && typeof editValue === "string" && (
                  <span className="help">
                    {editValue.length} / {attr.validation.max_length} characters
                  </span>
                )}
                <div className="row">
                  <button className="primary small" disabled={busy} onClick={() => accept.mutate(editValue)}>
                    {accept.isPending ? "Saving" : "Accept edited value"}
                  </button>
                  <button className="small" disabled={busy} onClick={() => { setMode("idle"); setEditValue(output.proposed_value); }}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="pre">{valueText(output.status === "accepted" || output.status === "edited" ? (output.final_value ?? output.proposed_value) : output.proposed_value) || <span className="faint">empty</span>}</div>
            )}
          </div>
        </div>
      )}

      {!isCheck && output.diff && output.diff.length > 0 && mode !== "edit" && (
        <details className="ai-diff-wrap" open={isTextual}>
          <summary className="muted small">Changes versus the current value</summary>
          <DiffView parts={output.diff} />
        </details>
      )}

      {output.grounding_errors.length > 0 && (
        <div className="ai-issues">
          <span className="muted small">Grounding errors:</span>
          {output.grounding_errors.map((g, i) => (
            <Badge key={i} color="red" title="Claim not supported by the product's data">
              {g}
            </Badge>
          ))}
        </div>
      )}
      {output.needs_input.length > 0 && (
        <div className="ai-issues">
          <span className="muted small">Needs input:</span>
          {output.needs_input.map((code) => {
            const a = attrByCode.get(code);
            const label = a?.label ?? code;
            return onGoToAttribute ? (
              <button key={code} className="chip-btn" onClick={() => onGoToAttribute(code)} title={`Fill ${label} in the form, then regenerate`}>
                {label}
              </button>
            ) : (
              <Link key={code} to={`/products/${encodeURIComponent(output.entity_id)}?attr=${encodeURIComponent(code)}`} className="badge purple">
                {label}
              </Link>
            );
          })}
        </div>
      )}
      {output.rejection_reason && (
        <div className="small">
          <span className="muted">Rejected:</span> {output.rejection_reason}
        </div>
      )}
      {(output.decided_by || output.decided_at) && (
        <div className="faint small">
          Decided {output.decided_by ? `by ${output.decided_by}` : ""} {output.decided_at ? formatDate(output.decided_at) : ""}
          {output.edit_distance !== null && output.edit_distance !== undefined ? `, edit distance ${output.edit_distance}` : ""}
        </div>
      )}

      {error && <ErrorBox error={error} title="Action failed" />}

      {(canAccept || canReject || canRegenerate) && mode !== "edit" && (
        <div className="row ai-actions">
          {canAccept && (
            <button className="primary small" disabled={busy} onClick={() => accept.mutate(undefined)}>
              {accept.isPending ? "Saving" : "Accept"}
            </button>
          )}
          {canAccept && (
            <button className="small" disabled={busy} onClick={() => { setEditValue(output.proposed_value); setMode("edit"); }}>
              Edit then accept
            </button>
          )}
          {canRegenerate && (
            <button className="small" disabled={busy} onClick={() => setMode("regenerate")}>
              Regenerate
            </button>
          )}
          {canReject && (
            <button className="small danger" disabled={busy} onClick={() => setMode("reject")}>
              Reject
            </button>
          )}
          {isInfo && <span className="faint small">Informational result; nothing to accept.</span>}
        </div>
      )}

      {mode === "reject" && (
        <Dialog
          title="Reject this suggestion"
          onClose={() => setMode("idle")}
          footer={
            <>
              <button onClick={() => setMode("idle")} disabled={busy}>
                Cancel
              </button>
              <button className="danger" disabled={busy || !finalReason} onClick={() => reject.mutate(finalReason)}>
                {reject.isPending ? "Rejecting" : "Reject"}
              </button>
            </>
          }
        >
          <p className="muted small">A reason is required. Rejections feed the template metrics (AI-07).</p>
          <div className="stack" style={{ gap: 4 }}>
            {QUICK_REJECT_REASONS.map((r) => (
              <label key={r} className="inline">
                <input type="radio" name={`reject-${output.id}`} checked={reason === r} onChange={() => setReason(r)} /> {r}
              </label>
            ))}
          </div>
          {reason === "Other" && (
            <label className="field mt8">
              Reason
              <textarea value={otherReason} onChange={(e) => setOtherReason(e.target.value)} placeholder="What is wrong with this suggestion" />
            </label>
          )}
        </Dialog>
      )}
      {mode === "regenerate" && (
        <Dialog
          title="Regenerate"
          onClose={() => setMode("idle")}
          footer={
            <>
              <button onClick={() => setMode("idle")} disabled={busy}>
                Cancel
              </button>
              <button className="primary" disabled={busy} onClick={() => regenerate.mutate(note.trim() || undefined)}>
                {regenerate.isPending ? "Generating" : "Regenerate"}
              </button>
            </>
          }
        >
          <p className="muted small">The current suggestion is rejected with the reason "regenerated" and a new one is produced.</p>
          <label className="field">
            Note for the model (optional)
            <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. mention the removable cups, keep it under 60 words" />
          </label>
        </Dialog>
      )}
    </div>
  );
}
