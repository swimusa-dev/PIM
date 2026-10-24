// EXP-04, EXP-05, EXP-06: Exports page. Channel picker, Dry run and Publish dialogs, delta preview, and the
// publish history (/api/publishes) with channel and kind filters and status pills.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { publishApi } from "../api/client";
import { channelRight, useChannels, useMe } from "../api/hooks";
import type { PublishKind } from "../api/types";
import { Empty, ErrorBox, Spinner } from "../components/Common";
import { formatDate } from "../lib/format";
import { DeltaDialog, KindBadge, KIND_LABEL, PublishStatusBadge, RunDialog } from "../exports/shared";

const PAGE_SIZE_GUESS = 50;

export function ExportsPage() {
  const channels = useChannels();
  const me = useMe();
  const [channel, setChannel] = useState("");
  const [kind, setKind] = useState<PublishKind | "">("");
  const [page, setPage] = useState(1);
  const [dialog, setDialog] = useState<"dry_run" | "publish" | "delta" | null>(null);

  const q = useQuery({
    queryKey: ["publishes", channel, kind, page],
    queryFn: () => publishApi.list({ channel: channel || undefined, kind: kind || undefined, page }),
    refetchInterval: 30_000,
  });
  const runChannel = channel || channels.data?.find((c) => c.enabled)?.code || "";
  const canPublish = !!runChannel && channelRight(me.data, runChannel, "run");
  const rows = q.data?.rows ?? [];
  const total = q.data?.total ?? 0;
  const hasMore = rows.length > 0 && page * Math.max(rows.length, PAGE_SIZE_GUESS) < total;

  return (
    <div>
      <div className="page-header">
        <h1>Exports</h1>
        <div className="actions">
          <select
            value={channel}
            onChange={(e) => {
              setChannel(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All channels</option>
            {(channels.data ?? []).map((c) => (
              <option key={c.code} value={c.code}>
                {c.label}
              </option>
            ))}
          </select>
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as PublishKind | "");
              setPage(1);
            }}
          >
            <option value="">All kinds</option>
            {(Object.keys(KIND_LABEL) as PublishKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </select>
          <button disabled={!runChannel} onClick={() => setDialog("delta")} title="Products that would go in a delta run for the selected channel">
            Delta preview
          </button>
          <button disabled={!runChannel} onClick={() => setDialog("dry_run")}>
            Dry run
          </button>
          <button className="primary" disabled={!canPublish} title={canPublish ? "" : "Needs the run right for the selected channel"} onClick={() => setDialog("publish")}>
            Publish
          </button>
        </div>
      </div>
      <p className="muted small">
        A dry run validates and writes the payload without sending. Publish sends through the channel adapter, or creates an update package for
        package-transport channels such as Shopify (EXP-13). Scheduled exports appear here as well (EXP-06).
      </p>
      {q.isLoading && <Spinner label="Loading publish history" />}
      {q.isError && <ErrorBox error={q.error} title="Could not load the publish history" />}
      {q.data && rows.length === 0 && (
        <Empty title="No publishes yet">
          {channel || kind ? "Nothing matches these filters." : "Run a dry run to validate a selection against a channel's target schema."}
        </Empty>
      )}
      {rows.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Publish</th>
                <th>Channel</th>
                <th>Kind</th>
                <th>Mode</th>
                <th>Status</th>
                <th>Created</th>
                <th>By</th>
                <th className="right">Products</th>
                <th className="right">Valid</th>
                <th className="right">Invalid</th>
                <th className="right">Files</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link to={`/exports/${encodeURIComponent(p.id)}`} className="mono">
                      {p.id}
                    </Link>
                  </td>
                  <td>
                    {channels.data?.find((c) => c.code === p.channel_code)?.label ?? p.channel_code}
                    <span className="faint small"> v{p.channel_version}</span>
                  </td>
                  <td>
                    <KindBadge kind={p.kind} />
                  </td>
                  <td>{p.mode}</td>
                  <td>
                    <PublishStatusBadge status={p.status} />
                    {p.error && (
                      <div className="issue" title={p.error}>
                        {p.error.length > 60 ? `${p.error.slice(0, 60)}...` : p.error}
                      </div>
                    )}
                  </td>
                  <td className="nowrap">{formatDate(p.created_at)}</td>
                  <td>{p.created_by}</td>
                  <td className="num">{p.product_count}</td>
                  <td className="num">{p.valid_count}</td>
                  <td className={`num${p.invalid_count > 0 ? " field-error" : ""}`}>{p.invalid_count}</td>
                  <td className="num">{p.files.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row panel-body" style={{ justifyContent: "space-between" }}>
            <span className="muted small">
              {total} publish{total === 1 ? "" : "es"}
            </span>
            <span className="row">
              <button className="small" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                Previous
              </button>
              <span className="muted small">Page {page}</span>
              <button className="small" disabled={!hasMore} onClick={() => setPage(page + 1)}>
                Next
              </button>
            </span>
          </div>
        </div>
      )}
      {(dialog === "dry_run" || dialog === "publish") && <RunDialog kind={dialog} initialChannel={runChannel} onClose={() => setDialog(null)} />}
      {dialog === "delta" && runChannel && <DeltaDialog channel={runChannel} onClose={() => setDialog(null)} />}
    </div>
  );
}
