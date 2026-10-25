// EXP-08, EXP-09: pieces for the publish detail page and the channel Health tab. DeliveryCard renders
// Publish.summary.delivery (DeliveryResult) with "Deliver now" (POST /api/publishes/{id}/deliver, 409 shown as a
// clear message); WalmartFeedCard renders Publish.summary.walmart with "Poll now" (the feedback endpoint without
// a file); ListingQualityPill colors a Walmart Listing Quality score; the type guards read the untyped summary.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, publishApi } from "../api/client";
import type { DeliveryResult, WalmartFeedSummary } from "../api/types";
import { Badge, ErrorBox, useToast } from "../components/Common";
import { formatDate } from "../lib/format";

export function isDeliveryResult(v: unknown): v is DeliveryResult {
  return !!v && typeof v === "object" && typeof (v as DeliveryResult).status === "string" && typeof (v as DeliveryResult).transport === "string";
}

export function isWalmartSummary(v: unknown): v is WalmartFeedSummary {
  return !!v && typeof v === "object" && Array.isArray((v as WalmartFeedSummary).feed_ids);
}

export function listingQualityMap(v: unknown): Record<string, number> {
  if (!v || typeof v !== "object" || Array.isArray(v)) return {};
  const out: Record<string, number> = {};
  for (const [k, n] of Object.entries(v as Record<string, unknown>)) if (typeof n === "number") out[k] = n;
  return out;
}

/** Walmart Listing Quality score (0 to 100): green at 80 and above, amber at 50 and above, red below. */
export function ListingQualityPill({ value }: { value: number | undefined | null }) {
  if (value === undefined || value === null) return <span className="faint">n/a</span>;
  const cls = value >= 80 ? "p-high" : value >= 50 ? "p-mid" : "p-low";
  return (
    <span className={`pill ${cls}`} title={`Listing quality ${Math.round(value * 10) / 10}`}>
      {Math.round(value)}
    </span>
  );
}

export function DeliveryStatusBadge({ status }: { status: DeliveryResult["status"] | string }) {
  const color = status === "delivered" ? "green" : status === "failed" ? "red" : status === "skipped" ? "amber" : undefined;
  return <Badge color={color}>{status.replace(/_/g, " ")}</Badge>;
}

export function DeliveryCard({
  publishId,
  delivery,
  transport,
  canDeliver,
}: {
  publishId: string;
  delivery: DeliveryResult | null;
  /** Effective channel transport (download, sftp, email, api) when known. */
  transport: string | null;
  /** False for dry runs and running publishes. */
  canDeliver: boolean;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const deliver = useMutation({
    mutationFn: () => publishApi.deliver(publishId),
    onSuccess: (r) => {
      toast(r.status === "delivered" ? `Delivered through ${r.transport}: ${r.detail}` : `Delivery ${r.status}: ${r.detail}`, r.status === "delivered" ? "ok" : "warn");
      qc.invalidateQueries({ queryKey: ["publishes"] });
      qc.invalidateQueries({ queryKey: ["channel"] });
    },
  });
  const sendable = transport === "sftp" || transport === "email" || (delivery !== null && (delivery.transport === "sftp" || delivery.transport === "email"));
  const conflict = deliver.error instanceof ApiError && deliver.error.status === 409;
  const shown = deliver.data ?? delivery;

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Delivery</h3>
        <div className="row">
          {transport && <Badge title="Channel transport">{transport}</Badge>}
          {sendable && (
            <button className="primary small" disabled={!canDeliver || deliver.isPending} title={canDeliver ? "Send the files of this publish through the channel transport again" : "Only finished publishes can be delivered"} onClick={() => deliver.mutate()}>
              {deliver.isPending ? "Delivering" : shown ? "Deliver again" : "Deliver now"}
            </button>
          )}
        </div>
      </div>
      <div className="panel-body">
        {conflict && (
          <div className="banner warn mb8" style={{ borderRadius: "var(--radius)" }}>
            Delivery is not available for this channel: the transport is download, or the SFTP / email settings are not configured. Set it under Admin, Channels, Transport.
          </div>
        )}
        {deliver.isError && !conflict && <ErrorBox error={deliver.error} title="Delivery failed" />}
        {shown ? (
          <dl className="kv">
            <dt>Transport</dt>
            <dd>{shown.transport}</dd>
            <dt>Status</dt>
            <dd>
              <DeliveryStatusBadge status={shown.status} />
            </dd>
            <dt>Detail</dt>
            <dd className="pre">{shown.detail || <span className="faint">none</span>}</dd>
            <dt>Files</dt>
            <dd>
              {shown.files.length === 0 ? (
                <span className="faint">none</span>
              ) : (
                <div className="chips">
                  {shown.files.map((f) => (
                    <Badge key={f} title={f}>
                      <span className="mono">{f}</span>
                    </Badge>
                  ))}
                </div>
              )}
            </dd>
            <dt>Time</dt>
            <dd>{formatDate(shown.at)}</dd>
          </dl>
        ) : (
          <span className="muted">
            {sendable
              ? "Not delivered yet. Deliver now sends the files through the channel transport."
              : transport === "api"
                ? "This channel submits items through its adapter; there is no file delivery."
                : "This channel's files are downloaded from the Files panel; no delivery is recorded."}
          </span>
        )}
      </div>
    </div>
  );
}

export function WalmartFeedCard({ walmart, polling, onPoll, canPoll }: { walmart: WalmartFeedSummary; polling: boolean; onPoll: () => void; canPoll: boolean }) {
  const s = walmart.status.toLowerCase();
  const color = /process|accept|complete|done|success/.test(s) ? "green" : /error|fail|reject/.test(s) ? "red" : "amber";
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Walmart feeds</h3>
        <button className="small" disabled={!canPoll || polling} title="Poll the status of each feed now instead of waiting for the next scheduled poll" onClick={onPoll}>
          {polling ? "Polling" : "Poll now"}
        </button>
      </div>
      <div className="panel-body">
        <dl className="kv">
          <dt>Feed ids</dt>
          <dd>
            {walmart.feed_ids.length === 0 ? (
              <span className="faint">no feeds submitted</span>
            ) : (
              <div className="chips">
                {walmart.feed_ids.map((id) => (
                  <Badge key={id} color="teal">
                    <span className="mono">{id}</span>
                  </Badge>
                ))}
              </div>
            )}
          </dd>
          <dt>Status</dt>
          <dd>
            <Badge color={color}>{walmart.status.replace(/_/g, " ")}</Badge>
          </dd>
          <dt>Next poll</dt>
          <dd>{walmart.next_poll_at ? formatDate(walmart.next_poll_at) : <span className="faint">not scheduled</span>}</dd>
          <dt>Polls so far</dt>
          <dd>{walmart.polls}</dd>
        </dl>
        <span className="help">Feeds are polled 15 minutes, 1 hour and 2 hours after submission, then every 4 hours. Each poll stores ingestion errors per item and the Listing Quality score.</span>
      </div>
    </div>
  );
}
