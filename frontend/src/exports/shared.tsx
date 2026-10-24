// EXP-04, EXP-05: pieces shared by the Exports page and the publish detail page: status pills, the
// Dry run / Publish dialog, and the delta preview dialog.

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, channelApi } from "../api/client";
import { channelRight, useChannels, useMe } from "../api/hooks";
import type { Channel, PublishItemStatus, PublishKind, PublishMode, PublishRequest, PublishStatus } from "../api/types";
import { Badge, Dialog, Empty, ErrorBox, Spinner } from "../components/Common";

export function PublishStatusBadge({ status }: { status: PublishStatus | PublishItemStatus | string }) {
  const s = status.toLowerCase();
  const color =
    s === "completed" || s === "accepted" || s === "valid"
      ? "green"
      : s === "failed" || s === "rejected" || s === "invalid"
        ? "red"
        : s === "running" || s === "submitted" || s === "pending" || s === "in_review" || s === "partial"
          ? "amber"
          : undefined;
  return <Badge color={color}>{s.replace(/_/g, " ")}</Badge>;
}

export const KIND_LABEL: Record<PublishKind, string> = { dry_run: "Dry run", package: "Package", publish: "Publish", scheduled: "Scheduled" };

export function KindBadge({ kind }: { kind: PublishKind }) {
  const color = kind === "dry_run" ? "blue" : kind === "package" ? "teal" : kind === "scheduled" ? "purple" : "green";
  return <Badge color={color}>{KIND_LABEL[kind] ?? kind}</Badge>;
}

/** True when the channel delivers through an EXP-13 package rather than an API adapter. */
export function isPackageTransport(channel: Channel | undefined): boolean {
  if (!channel) return false;
  const t = String(channel.config?.transport ?? "").toLowerCase();
  return t === "package" || (t === "" && channel.adapter.toLowerCase().includes("shopify"));
}

export function RunDialog({ kind, initialChannel, onClose }: { kind: "dry_run" | "publish"; initialChannel: string; onClose: () => void }) {
  const channels = useChannels();
  const me = useMe();
  const views = useQuery({ queryKey: ["views", "all"], queryFn: () => api.views.list() });
  const navigate = useNavigate();

  const [channel, setChannel] = useState(initialChannel);
  const [selMode, setSelMode] = useState<"view" | "ids" | "changed">("view");
  const [viewId, setViewId] = useState("");
  const [ids, setIds] = useState("");
  const [changedSince, setChangedSince] = useState("");
  const [mode, setMode] = useState<PublishMode>("delta");
  const [preview, setPreview] = useState(5);

  const effectiveChannel = channel || channels.data?.find((c) => c.enabled)?.code || "";
  const ch = channels.data?.find((c) => c.code === effectiveChannel);
  const canRun = kind === "dry_run" || channelRight(me.data, effectiveChannel, "run");

  const run = useMutation({
    mutationFn: () => {
      const body: PublishRequest = {
        selection:
          selMode === "view"
            ? { view_id: viewId }
            : selMode === "ids"
              ? { entity_ids: ids.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean) }
              : { changed_since: new Date(changedSince).toISOString() },
        mode,
        preview,
      };
      return kind === "dry_run" ? channelApi.dryRun(effectiveChannel, body) : channelApi.publish(effectiveChannel, body);
    },
    onSuccess: (p) => {
      onClose();
      navigate(`/exports/${encodeURIComponent(p.id)}`);
    },
  });

  const valid = !!effectiveChannel && (selMode === "view" ? !!viewId : selMode === "ids" ? ids.trim().length > 0 : !!changedSince) && preview >= 0;

  return (
    <Dialog
      title={kind === "dry_run" ? "Dry run" : "Publish"}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose} disabled={run.isPending}>
            Cancel
          </button>
          <button className="primary" disabled={!valid || !canRun || run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? "Running" : kind === "dry_run" ? "Run dry run" : isPackageTransport(ch) ? "Create package" : "Publish"}
          </button>
        </>
      }
    >
      <div className="stack gap16">
        <p className="muted small" style={{ margin: 0 }}>
          {kind === "dry_run"
            ? "A dry run validates the selection against the channel's target schema and writes the payload and a validation report without sending anything."
            : isPackageTransport(ch)
              ? "This channel delivers through an update package (EXP-13): publishing creates the package for the Shopify team to review."
              : "Publishing validates the selection, writes the payload and sends it through the channel adapter."}
        </p>
        <label className="field">
          Channel
          <select value={effectiveChannel} onChange={(e) => setChannel(e.target.value)}>
            {(channels.data ?? []).map((c) => (
              <option key={c.code} value={c.code} disabled={!c.enabled}>
                {c.label}
                {c.enabled ? "" : " (disabled)"}
              </option>
            ))}
          </select>
        </label>
        {!canRun && <div className="banner warn">You do not have the run right for this channel. Ask a PIM Admin.</div>}

        <div>
          <div className="muted small mb8">Selection</div>
          <div className="row">
            <label className="inline">
              <input type="radio" checked={selMode === "view"} onChange={() => setSelMode("view")} /> Saved view
            </label>
            <label className="inline">
              <input type="radio" checked={selMode === "ids"} onChange={() => setSelMode("ids")} /> Pasted entity ids
            </label>
            <label className="inline">
              <input type="radio" checked={selMode === "changed"} onChange={() => setSelMode("changed")} /> Changed since
            </label>
          </div>
          <div className="mt8">
            {selMode === "view" && (
              <select value={viewId} onChange={(e) => setViewId(e.target.value)} style={{ width: "100%" }}>
                <option value="">Choose a saved view</option>
                {(views.data ?? []).map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name} ({v.level}, {v.owner_email})
                  </option>
                ))}
              </select>
            )}
            {selMode === "ids" && (
              <textarea value={ids} onChange={(e) => setIds(e.target.value)} placeholder="One entity id per line, or separated by commas" style={{ width: "100%" }} />
            )}
            {selMode === "changed" && <input type="datetime-local" value={changedSince} onChange={(e) => setChangedSince(e.target.value)} />}
          </div>
        </div>

        <div className="form-grid">
          <label className="field">
            Mode
            <select value={mode} onChange={(e) => setMode(e.target.value as PublishMode)}>
              <option value="delta">Delta (changed since the last successful publish)</option>
              <option value="full">Full (every product in the selection)</option>
            </select>
          </label>
          <label className="field">
            Preview count (payloads shown on the result)
            <input type="number" min={0} max={100} value={preview} onChange={(e) => setPreview(Number(e.target.value))} />
          </label>
        </div>
        {run.isError && <ErrorBox error={run.error} title={kind === "dry_run" ? "Dry run failed" : "Publish failed"} />}
      </div>
    </Dialog>
  );
}

export function DeltaDialog({ channel, onClose }: { channel: string; onClose: () => void }) {
  const views = useQuery({ queryKey: ["views", "all"], queryFn: () => api.views.list() });
  const [viewId, setViewId] = useState("");
  const q = useQuery({ queryKey: ["channel", channel, "delta", viewId], queryFn: () => channelApi.delta(channel, viewId || undefined) });
  return (
    <Dialog title={`Delta preview for ${channel}`} onClose={onClose} wide footer={<button onClick={onClose}>Close</button>}>
      <div className="stack gap16">
        <label className="field">
          Limit to a saved view (optional)
          <select value={viewId} onChange={(e) => setViewId(e.target.value)}>
            <option value="">All eligible products</option>
            {(views.data ?? []).map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} ({v.level})
              </option>
            ))}
          </select>
        </label>
        {q.isLoading && <Spinner label="Computing the delta" />}
        {q.isError && <ErrorBox error={q.error} title="Could not compute the delta" />}
        {q.data && (
          <>
            <div className="row">
              <b>{q.data.changed}</b>
              <span className="muted">product{q.data.changed === 1 ? "" : "s"} would go in a delta run (values, images or readiness changed since the last successful publish).</span>
            </div>
            {q.data.sample.length === 0 ? (
              <Empty title="Nothing changed">A delta run for this channel would send no products.</Empty>
            ) : (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>Reasons</th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.sample.map((s) => (
                    <tr key={s.entity_id}>
                      <td>
                        <a href={`/products/${encodeURIComponent(s.entity_id)}`}>{s.label}</a>
                      </td>
                      <td>
                        <div className="chips">
                          {s.reasons.map((r, i) => (
                            <Badge key={i}>{r}</Badge>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {q.data.sample.length < q.data.changed && <span className="faint small">Showing a sample of {q.data.sample.length}.</span>}
          </>
        )}
      </div>
    </Dialog>
  );
}
