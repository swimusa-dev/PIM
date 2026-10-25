// EXP-04, EXP-05, Phase 5 EXP-08, EXP-09: Publish detail. Summary, payload preview (pretty JSON, or a table for
// flat CSV-type payloads), files to download, items with status filters and their issues and errors (internal /
// external pills, attribute chips linking to the product), retailer feedback upload or adapter poll, the link to
// the EXP-13 package for package-transport channels, the delivery card with "Deliver now" (summary.delivery),
// the Walmart feed card with "Poll now" (summary.walmart) and the Listing quality column on items.

import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { channelApi, publishApi } from "../api/client";
import { useAttributes, useChannels } from "../api/hooks";
import type { PayloadIssue, PublishItem, PublishItemError, PublishItemStatus } from "../api/types";
import { Badge, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { formatBytes, formatDate } from "../lib/format";
import { ErrorKindPill } from "../admin/channel/HealthTab";
import { KindBadge, PublishStatusBadge } from "../exports/shared";
import { DeliveryCard, ListingQualityPill, WalmartFeedCard, isDeliveryResult, isWalmartSummary, listingQualityMap } from "../exports/DeliveryCards";

// Summary keys rendered as cards rather than in the key / value list.
const CARD_SUMMARY_KEYS = new Set(["preview", "delivery", "walmart", "listing_quality"]);

const ITEM_STATUSES: PublishItemStatus[] = ["pending", "valid", "invalid", "submitted", "accepted", "rejected", "in_review"];

export function ExportDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const channels = useChannels();
  const attrs = useAttributes();
  const fileRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<PublishItemStatus | "">("");
  const [page, setPage] = useState(1);
  const [previewMode, setPreviewMode] = useState<"auto" | "json" | "table">("auto");

  const q = useQuery({
    queryKey: ["publishes", "detail", id],
    queryFn: () => publishApi.detail(id),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 5000 : false),
  });
  const items = useQuery({
    queryKey: ["publishes", "items", id, status, page],
    queryFn: () => publishApi.items(id, { status: status || undefined, page }),
    enabled: !!q.data && (status !== "" || page > 1 || q.data.items.length >= 500),
  });

  const feedback = useMutation({
    mutationFn: (file: File | null) => publishApi.feedback(id, file),
    onSuccess: (r) => {
      toast(`Feedback applied: ${r.updated} updated (${r.accepted} accepted, ${r.rejected} rejected, ${r.in_review} in review).`, "ok");
      qc.invalidateQueries({ queryKey: ["publishes"] });
      qc.invalidateQueries({ queryKey: ["channel"] });
    },
    onError: (e) => toast(`Feedback failed: ${(e as Error).message}`, "error"),
  });

  const attrLabel = (code: string) => attrs.data?.find((a) => a.code === code)?.label ?? code;
  const p = q.data;
  const channel = channels.data?.find((c) => c.code === p?.channel_code);
  // Phase 5: the channel transport decides whether "Deliver now" is offered (sftp or email).
  const transportQ = useQuery({
    queryKey: ["channel", p?.channel_code ?? "", "transport"],
    queryFn: () => channelApi.transport(p!.channel_code),
    enabled: !!p && p.kind !== "dry_run",
    retry: false,
  });
  const effectiveTransport = transportQ.data?.transport ?? (channel?.config?.transport ? String(channel.config.transport) : null);
  const delivery = isDeliveryResult(p?.summary?.delivery) ? p!.summary.delivery : null;
  const walmart = isWalmartSummary(p?.summary?.walmart) ? p!.summary.walmart : null;
  const qualityByExternalId = useMemo(() => listingQualityMap(p?.summary?.listing_quality), [p]);
  const preview = useMemo(() => {
    const pv = p?.summary?.preview;
    return Array.isArray(pv) ? (pv as Record<string, unknown>[]) : [];
  }, [p]);
  const flat = useMemo(() => preview.length > 0 && preview.every((r) => r && typeof r === "object" && Object.values(r).every((v) => v === null || typeof v !== "object")), [preview]);
  const csvType = p?.files.some((f) => /csv|xlsx/i.test(f.kind) || /\.(csv|xlsx)$/i.test(f.name)) ?? false;
  const showTable = previewMode === "table" || (previewMode === "auto" && flat && csvType);
  const previewColumns = useMemo(() => Array.from(new Set(preview.flatMap((r) => Object.keys(r)))), [preview]);
  const packageId = p?.summary?.package_id ? String(p.summary.package_id) : null;

  const shownItems: PublishItem[] = items.data?.rows ?? (status === "" && page === 1 ? (p?.items ?? []) : []);
  const itemTotal = items.data?.total ?? p?.items.length ?? 0;
  const qualityOf = (it: PublishItem): number | null | undefined =>
    it.listing_quality ?? (it.external_id && qualityByExternalId[it.external_id] !== undefined ? qualityByExternalId[it.external_id] : undefined);
  const showQuality = shownItems.some((it) => qualityOf(it) !== undefined && qualityOf(it) !== null);
  const statusCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const it of p?.items ?? []) m[it.status] = (m[it.status] ?? 0) + 1;
    return m;
  }, [p]);

  if (q.isLoading) return <Spinner label="Loading publish" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load the publish" />;
  if (!p) return null;

  return (
    <div className="stack gap16">
      <div className="page-header">
        <div>
          <div className="muted small">
            <Link to="/exports">Exports</Link> / {channel?.label ?? p.channel_code}
          </div>
          <h1 className="row">
            <span className="mono">{p.id}</span> <KindBadge kind={p.kind} /> <PublishStatusBadge status={p.status} />
          </h1>
          <div className="muted small">
            {p.mode} mode, channel version {p.channel_version}. Created {formatDate(p.created_at)} by {p.created_by}
            {p.finished_at ? `, finished ${formatDate(p.finished_at)}` : ""}.
            {p.external_batch_id && (
              <>
                {" "}
                External batch <span className="mono">{p.external_batch_id}</span>.
              </>
            )}
          </div>
        </div>
        <div className="actions">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.json,.xlsx,text/csv,application/json"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) feedback.mutate(f);
              e.target.value = "";
            }}
          />
          <button onClick={() => fileRef.current?.click()} disabled={feedback.isPending || p.kind === "dry_run"} title="Retailer error report (CSV, JSON or XLSX with a product id column and a message column)">
            {feedback.isPending ? "Applying" : "Upload retailer feedback"}
          </button>
          <button onClick={() => feedback.mutate(null)} disabled={feedback.isPending || p.kind === "dry_run"} title="Ask the channel adapter for the status of this batch">
            Poll adapter
          </button>
        </div>
      </div>

      {p.status === "running" && <div className="banner warn">The publish is still running. This page refreshes automatically.</div>}
      {p.error && <ErrorBox error={p.error} title="Publish error" />}
      {packageId && (
        <div className="banner" style={{ background: "var(--teal-light)", color: "var(--teal-dark)", borderRadius: "var(--radius)" }}>
          This channel delivers through an update package. Review it under{" "}
          <Link to={`/packages/${encodeURIComponent(packageId)}`} className="mono">
            Packages / {packageId}
          </Link>
          .
        </div>
      )}
      {feedback.data && (
        <div className="banner" style={{ background: "var(--green-bg)", color: "var(--green)", borderRadius: "var(--radius)" }}>
          Feedback applied: {feedback.data.updated} updated, {feedback.data.accepted} accepted, {feedback.data.rejected} rejected, {feedback.data.in_review} in review.
        </div>
      )}

      <div className="cards">
        <div className="card">
          <div className="card-title">Products</div>
          <div className="card-value">{p.product_count}</div>
        </div>
        <div className="card">
          <div className="card-title">Valid</div>
          <div className="card-value">{p.valid_count}</div>
        </div>
        <div className="card">
          <div className="card-title">Invalid</div>
          <div className={`card-value${p.invalid_count > 0 ? " alert" : ""}`}>{p.invalid_count}</div>
        </div>
        {ITEM_STATUSES.filter((s) => statusCounts[s] && s !== "valid" && s !== "invalid").map((s) => (
          <div className="card" key={s}>
            <div className="card-title">{s.replace(/_/g, " ")}</div>
            <div className={`card-value${s === "rejected" ? " alert" : ""}`}>{statusCounts[s]}</div>
          </div>
        ))}
      </div>

      <div className="two-col">
        <div className="panel">
          <div className="panel-header">
            <h3>Files</h3>
          </div>
          <div className="panel-body flush">
            {p.files.length === 0 ? (
              <Empty title="No files">The payload and the validation report appear here once the run finishes.</Empty>
            ) : (
              <table className="data compact">
                <tbody>
                  {p.files.map((f) => (
                    <tr key={f.name}>
                      <td>
                        <a href={publishApi.fileUrl(p.id, f.name)} download className="mono">
                          {f.name}
                        </a>
                      </td>
                      <td>
                        <Badge>{f.kind}</Badge>
                      </td>
                      <td className="num muted">{formatBytes(f.size)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
        <div className="panel">
          <div className="panel-header">
            <h3>Selection and summary</h3>
          </div>
          <div className="panel-body">
            <dl className="kv">
              {Object.entries(p.selection).map(([k, v]) => (
                <SummaryRow key={k} k={k} v={v} />
              ))}
              {Object.entries(p.summary)
                .filter(([k]) => !CARD_SUMMARY_KEYS.has(k))
                .map(([k, v]) => (
                  <SummaryRow key={k} k={k} v={v} />
                ))}
            </dl>
            {Object.keys(p.selection).length + Object.keys(p.summary).filter((k) => !CARD_SUMMARY_KEYS.has(k)).length === 0 && <span className="muted">No summary recorded.</span>}
          </div>
        </div>
      </div>

      {(p.kind !== "dry_run" || delivery) && (
        <div className={walmart ? "two-col" : undefined}>
          <DeliveryCard publishId={p.id} delivery={delivery} transport={effectiveTransport} canDeliver={p.kind !== "dry_run" && p.status !== "running"} />
          {walmart && <WalmartFeedCard walmart={walmart} polling={feedback.isPending} canPoll={p.kind !== "dry_run"} onPoll={() => feedback.mutate(null)} />}
        </div>
      )}

      <div className="panel">
        <div className="panel-header">
          <h3>
            Payload preview <span className="muted small">(first {preview.length})</span>
          </h3>
          <div className="row">
            <label className="inline">
              <input type="radio" checked={previewMode === "auto"} onChange={() => setPreviewMode("auto")} /> Auto
            </label>
            <label className="inline">
              <input type="radio" checked={previewMode === "json"} onChange={() => setPreviewMode("json")} /> JSON
            </label>
            <label className="inline">
              <input type="radio" checked={previewMode === "table"} disabled={!flat} onChange={() => setPreviewMode("table")} /> Table
            </label>
          </div>
        </div>
        <div className="panel-body flush" style={{ maxHeight: 420, overflow: "auto" }}>
          {preview.length === 0 ? (
            <div className="empty">No preview payloads. Set a preview count above zero when running the export.</div>
          ) : showTable ? (
            <table className="data compact">
              <thead>
                <tr>
                  {previewColumns.map((c) => (
                    <th key={c} className="mono">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.map((r, i) => (
                  <tr key={i}>
                    {previewColumns.map((c) => (
                      <td key={c}>{r[c] === null || r[c] === undefined ? <span className="faint">empty</span> : String(r[c])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <pre className="pre mono" style={{ margin: 0, padding: 12, fontSize: 12 }}>
              {JSON.stringify(preview, null, 2)}
            </pre>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>
            Items <span className="muted small">({itemTotal})</span>
          </h3>
          <div className="row">
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as PublishItemStatus | "");
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {ITEM_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, " ")}
                  {statusCounts[s] ? ` (${statusCounts[s]})` : ""}
                </option>
              ))}
            </select>
            <button className="small" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              Previous
            </button>
            <span className="muted small">Page {page}</span>
            <button className="small" disabled={shownItems.length === 0 || shownItems.length < 100} onClick={() => setPage(page + 1)}>
              Next
            </button>
          </div>
        </div>
        <div className="panel-body flush">
          {items.isLoading && <Spinner label="Loading items" />}
          {items.isError && <ErrorBox error={items.error} title="Could not load items" />}
          {!items.isLoading && shownItems.length === 0 && <div className="empty">No items{status ? ` with status ${status.replace(/_/g, " ")}` : ""}.</div>}
          {shownItems.length > 0 && (
            <table className="data compact">
              <thead>
                <tr>
                  <th>Product</th>
                  <th>External id</th>
                  <th>Status</th>
                  <th>Issues</th>
                  <th>Errors</th>
                  {showQuality && <th title="Walmart Listing Quality score (0 to 100)">Listing quality</th>}
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {shownItems.map((it) => (
                  <tr key={it.id}>
                    <td>
                      <Link to={`/products/${encodeURIComponent(it.entity_id)}`}>{it.label}</Link>
                      <div className="faint small mono">{it.entity_id}</div>
                    </td>
                    <td className="mono">{it.external_id ?? <span className="faint">none</span>}</td>
                    <td>
                      <PublishStatusBadge status={it.status} />
                    </td>
                    <td>
                      {it.issues.length === 0 ? (
                        <span className="faint">none</span>
                      ) : (
                        <div className="stack" style={{ gap: 2 }}>
                          {it.issues.map((iss, i) => (
                            <IssueLine key={i} issue={iss} attrLabel={attrLabel} />
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      {it.errors.length === 0 ? (
                        <span className="faint">none</span>
                      ) : (
                        <div className="stack" style={{ gap: 2 }}>
                          {it.errors.map((er, i) => (
                            <ErrorLine key={i} error={er} entityId={it.entity_id} attrLabel={attrLabel} />
                          ))}
                        </div>
                      )}
                    </td>
                    {showQuality && (
                      <td>
                        <ListingQualityPill value={qualityOf(it)} />
                      </td>
                    )}
                    <td className="nowrap small">{formatDate(it.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryRow({ k, v }: { k: string; v: unknown }) {
  const text = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
  return (
    <>
      <dt className="mono">{k}</dt>
      <dd className="pre">{text || <span className="faint">empty</span>}</dd>
    </>
  );
}

function AttributeChip({ entityId, code, label }: { entityId: string; code: string; label: string }) {
  return (
    <Link to={`/products/${encodeURIComponent(entityId)}`} className="chip" title={`Open ${label} (${code}) on the product`}>
      {label}
    </Link>
  );
}

function IssueLine({ issue, attrLabel }: { issue: PayloadIssue; attrLabel: (c: string) => string }) {
  return (
    <span className={`issue${issue.severity === "warning" ? " warn" : ""}`} style={{ display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}>
      <Badge color={issue.severity === "warning" ? "amber" : "red"}>{issue.kind.replace(/_/g, " ")}</Badge>
      {issue.field && <span className="mono">{issue.field}</span>}
      {issue.attribute_code && <AttributeChip entityId={issue.entity_id} code={issue.attribute_code} label={attrLabel(issue.attribute_code)} />}
      <span>{issue.message}</span>
    </span>
  );
}

function ErrorLine({ error, entityId, attrLabel }: { error: PublishItemError; entityId: string; attrLabel: (c: string) => string }) {
  return (
    <span className="issue" style={{ display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}>
      <ErrorKindPill kind={error.kind} />
      {error.field && <span className="mono">{error.field}</span>}
      {error.attribute_code && <AttributeChip entityId={entityId} code={error.attribute_code} label={attrLabel(error.attribute_code)} />}
      <span>{error.message}</span>
    </span>
  );
}
