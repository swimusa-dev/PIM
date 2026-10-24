// EXP-12: Eligibility per channel on the product detail readiness panel. Reasons from
// /api/products/{id}/eligibility; PIM Admins (admin_metadata) can override an ineligible channel with a
// required reason and an optional expiry; existing overrides are listed with a remove action.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { eligibilityApi } from "../api/client";
import { isAdmin, useMe } from "../api/hooks";
import type { EligibilityChannel } from "../api/types";
import { Badge, Dialog, ErrorBox, Spinner, useToast } from "../components/Common";
import { formatDate } from "../lib/format";

export function EligibilityPanel({ entityId, channelLabel }: { entityId: string; channelLabel: (code: string) => string }) {
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const admin = isAdmin(me.data) || (me.data?.permissions ?? []).includes("admin_metadata");
  const q = useQuery({ queryKey: ["product", entityId, "eligibility"], queryFn: () => eligibilityApi.get(entityId) });
  const [overriding, setOverriding] = useState<string | null>(null);

  const remove = useMutation({
    mutationFn: (id: string) => eligibilityApi.removeOverride(id),
    onSuccess: () => {
      toast("Eligibility override removed.", "ok");
      qc.invalidateQueries({ queryKey: ["product", entityId] });
      qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
    },
    onError: (e) => toast(`Could not remove the override: ${(e as Error).message}`, "error"),
  });

  if (q.isLoading) return <Spinner label="Loading eligibility" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load eligibility" />;
  const entries = Object.entries(q.data?.channels ?? {});
  if (entries.length === 0) return <span className="muted small">No channel eligibility computed.</span>;

  return (
    <div className="stack" style={{ gap: 8 }}>
      {entries.map(([code, e]: [string, EligibilityChannel]) => (
        <div key={code} className="eligibility-row">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="row" style={{ gap: 6 }}>
              <b>{channelLabel(code)}</b>
              {e.eligible ? <Badge color="green">eligible</Badge> : <Badge color="red">ineligible</Badge>}
              {e.override && (
                <Badge color="amber" title={`Overridden by ${e.override.approved_by}`}>
                  override
                </Badge>
              )}
            </span>
            {admin && !e.eligible && !e.override && (
              <button className="small" onClick={() => setOverriding(code)} title="Force this product into the channel (logged, EXP-12)">
                Override eligibility
              </button>
            )}
          </div>
          {e.reasons.length > 0 && (
            <ul className="reasons small">
              {e.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          {e.override && (
            <div className="small muted">
              Override: {e.override.reason} (by {e.override.approved_by} on {formatDate(e.override.created_at, false)}
              {e.override.expires_at ? `, expires ${formatDate(e.override.expires_at, false)}` : ""})
              {admin && (
                <>
                  {" "}
                  <button className="link small" disabled={remove.isPending} onClick={() => remove.mutate(e.override!.id)}>
                    Remove
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      ))}
      {overriding && <OverrideDialog entityId={entityId} channelCode={overriding} channelLabel={channelLabel(overriding)} onClose={() => setOverriding(null)} />}
    </div>
  );
}

function OverrideDialog({ entityId, channelCode, channelLabel, onClose }: { entityId: string; channelCode: string; channelLabel: string; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [expires, setExpires] = useState("");
  const save = useMutation({
    mutationFn: () =>
      eligibilityApi.override(entityId, {
        channel_code: channelCode,
        reason: reason.trim(),
        expires_at: expires ? new Date(expires).toISOString() : undefined,
      }),
    onSuccess: () => {
      toast(`Eligibility overridden for ${channelLabel}. The override is logged.`, "ok");
      qc.invalidateQueries({ queryKey: ["product", entityId] });
      qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
      onClose();
    },
  });
  return (
    <Dialog
      title={`Override eligibility for ${channelLabel}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose} disabled={save.isPending}>
            Cancel
          </button>
          <button className="primary" disabled={reason.trim().length < 3 || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving" : "Override"}
          </button>
        </>
      }
    >
      <div className="stack gap16">
        <p className="muted small" style={{ margin: 0 }}>
          The product will be treated as eligible for {channelLabel} even though the brand scope, classification, lifecycle or entity type rules say
          otherwise. The reason and your identity are recorded (EXP-12).
        </p>
        <label className="field">
          Reason (required)
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why this product must go to the channel" />
        </label>
        <label className="field">
          Expires (optional)
          <input type="datetime-local" value={expires} onChange={(e) => setExpires(e.target.value)} />
        </label>
        {save.isError && <ErrorBox error={save.error} title="Could not save the override" />}
      </div>
    </Dialog>
  );
}
