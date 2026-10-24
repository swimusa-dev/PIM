// AI-03, AI-04, AI-05, AI-07: small pieces shared by the Ask AI panel, the run page, the AI page and the
// approvals queue: task type labels, status pills for outputs, runs, templates and evals, the word-level diff
// view and the "AI endpoint not configured" banner (409 from POST /api/ai/ask and POST /api/ai/runs).

import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import type { AiOutputStatus, AiRunStatus, DiffPart, EvalRunStatus, TaskType, TemplateStatus } from "../api/types";
import { Badge, ErrorBox } from "../components/Common";

export const TASK_TYPES: { v: TaskType; label: string; help: string }[] = [
  { v: "generate", label: "Generate", help: "Write a new value from the product's attributes and images." },
  { v: "adapt", label: "Adapt", help: "Rewrite an existing value for a channel's length and tone." },
  { v: "extract", label: "Extract", help: "Pull attribute values out of pasted text, a document or images." },
  { v: "classify", label: "Classify", help: "Pick an option for a select attribute, with a confidence." },
  { v: "check", label: "Check", help: "Review a value against the brand voice and the facts; findings only." },
  { v: "restructure", label: "Restructure", help: "Split one value into several structured attributes." },
  { v: "expand", label: "Expand", help: "Lengthen a short value with grounded detail." },
];

export const TASK_ORDER: TaskType[] = TASK_TYPES.map((t) => t.v);

export function taskLabel(t: TaskType | string): string {
  return TASK_TYPES.find((x) => x.v === t)?.label ?? t;
}

export function TaskBadge({ task }: { task: TaskType | string }) {
  return (
    <Badge color="teal" title={TASK_TYPES.find((x) => x.v === task)?.help}>
      {taskLabel(task)}
    </Badge>
  );
}

export function outputStatusColor(s: AiOutputStatus | string): string | undefined {
  switch (s) {
    case "accepted":
      return "green";
    case "edited":
      return "teal";
    case "proposed":
      return "amber";
    case "rejected":
    case "failed":
      return "red";
    case "needs_input":
      return "purple";
    case "info":
      return "blue";
    default:
      return undefined;
  }
}

export function OutputStatusPill({ status }: { status: AiOutputStatus | string }) {
  return <Badge color={outputStatusColor(status)}>{status.replace(/_/g, " ")}</Badge>;
}

export function runStatusColor(s: AiRunStatus | string): string | undefined {
  switch (s) {
    case "completed":
      return "green";
    case "running":
    case "sample_pending":
      return "amber";
    case "sample_approved":
      return "blue";
    case "failed":
      return "red";
    default:
      return undefined;
  }
}

export function RunStatusPill({ status }: { status: AiRunStatus | string }) {
  return <Badge color={runStatusColor(status)}>{status.replace(/_/g, " ")}</Badge>;
}

export function EvalStatusPill({ status }: { status: EvalRunStatus | string }) {
  const color = status === "passed" ? "green" : status === "blocked" || status === "failed" ? "red" : "amber";
  return <Badge color={color}>{status}</Badge>;
}

export function TemplateStatusPill({ status }: { status: TemplateStatus | string }) {
  const color = status === "active" ? "green" : status === "retired" ? undefined : "amber";
  return <Badge color={color}>{status}</Badge>;
}

export function EvalGatePill({ gate }: { gate: { last_score?: number | null; blocked: boolean } | undefined | null }) {
  if (!gate) return <span className="faint">no eval</span>;
  const score = gate.last_score === null || gate.last_score === undefined ? "" : ` ${Math.round(gate.last_score * 100) / 100}`;
  return gate.blocked ? <Badge color="red">blocked{score}</Badge> : <Badge color="green">ok{score}</Badge>;
}

export function ConfidencePill({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return null;
  const pct = value <= 1 ? value * 100 : value;
  const cls = pct >= 85 ? "hi" : pct >= 60 ? "mid" : "lo";
  return (
    <span className={`confidence ${cls}`} title="Model confidence">
      {Math.round(pct)}% confident
    </span>
  );
}

/** Word-level diff from the contract's `diff` parts: insert green, delete red strikethrough. */
export function DiffView({ parts, empty }: { parts: DiffPart[] | undefined | null; empty?: ReactNode }) {
  if (!parts || parts.length === 0) return <span className="faint">{empty ?? "No diff"}</span>;
  return (
    <span className="ai-diff pre">
      {parts.map((p, i) =>
        p.op === "insert" ? (
          <ins key={i}>{p.text}</ins>
        ) : p.op === "delete" ? (
          <del key={i}>{p.text}</del>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </span>
  );
}

export function isNotConfigured(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409;
}

/** Shows the 409 "AI endpoint not configured" case as a banner, every other error as an ErrorBox. */
export function AiError({ error, title }: { error: unknown; title?: string }) {
  if (!error) return null;
  if (isNotConfigured(error)) {
    return (
      <div className="banner warn boxed" role="status">
        <b>AI is not configured.</b> The model endpoint for this task is not set up on the backend (AI-01), so nothing can be
        generated right now. Ask an administrator to configure the copy and classify endpoints, then try again.
        <div className="faint small">{(error as ApiError).message}</div>
      </div>
    );
  }
  return <ErrorBox error={error} title={title} />;
}

export const QUICK_REJECT_REASONS = ["Wrong facts", "Off brand voice", "Too long", "Not useful", "Other"];

export function shortId(id: string | null | undefined, n = 8): string {
  if (!id) return "";
  return id.length > n ? id.slice(0, n) : id;
}

export function pct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "n/a";
  const v = n <= 1 ? n * 100 : n;
  return `${Math.round(v)}%`;
}
