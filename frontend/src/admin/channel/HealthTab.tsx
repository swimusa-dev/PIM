// EXP-05, Phase 5 EXP-08: Channel health tab. Health score pill, accepted / rejected / in review counts, last
// publish and open rejections, top errors with internal / external pills, and for Walmart the listing quality
// average pill and the feeds in progress count.

import { useQuery } from "@tanstack/react-query";
import { channelApi } from "../../api/client";
import type { Channel } from "../../api/types";
import { Badge, Empty, ErrorBox, PercentPill, Spinner } from "../../components/Common";
import { formatDate } from "../../lib/format";
import { ListingQualityPill } from "../../exports/DeliveryCards";

export function ErrorKindPill({ kind }: { kind: "internal" | "external" }) {
  return kind === "external" ? (
    <Badge color="purple" title="Reported by the retailer or marketplace">
      external
    </Badge>
  ) : (
    <Badge color="amber" title="Found by the PIM validation before sending">
      internal
    </Badge>
  );
}

export function HealthTab({ channel }: { channel: Channel }) {
  const q = useQuery({ queryKey: ["channel", channel.code, "health"], queryFn: () => channelApi.health(channel.code) });
  if (q.isLoading) return <Spinner label="Loading channel health" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load channel health" />;
  const h = q.data!;
  if (h.publishes === 0 && !(h.feeds_in_progress && h.feeds_in_progress > 0)) {
    return <Empty title="No publishes yet">Health is computed from publish results and retailer feedback once the channel has been published to.</Empty>;
  }
  return (
    <div className="stack gap16">
      <div className="cards">
        <div className="card">
          <div className="card-title">Health score</div>
          <div className="card-value">
            <PercentPill value={h.health_score === null ? null : h.health_score <= 1 ? h.health_score * 100 : h.health_score} />
          </div>
        </div>
        <div className="card">
          <div className="card-title">Publishes</div>
          <div className="card-value">{h.publishes}</div>
        </div>
        <div className="card">
          <div className="card-title">Products sent</div>
          <div className="card-value">{h.products_sent}</div>
        </div>
        <div className="card">
          <div className="card-title">Accepted</div>
          <div className="card-value">{h.accepted}</div>
        </div>
        <div className="card">
          <div className="card-title">Rejected</div>
          <div className={`card-value${h.rejected > 0 ? " alert" : ""}`}>{h.rejected}</div>
        </div>
        <div className="card">
          <div className="card-title">In review</div>
          <div className="card-value">{h.in_review}</div>
        </div>
        <div className="card">
          <div className="card-title">Open rejections</div>
          <div className={`card-value${h.open_rejections > 0 ? " alert" : ""}`}>{h.open_rejections}</div>
        </div>
        {h.listing_quality_avg !== undefined && (
          <div className="card">
            <div className="card-title">Listing quality avg</div>
            <div className="card-value">
              <ListingQualityPill value={h.listing_quality_avg} />
            </div>
            <div className="faint small">Walmart Listing Quality, 0 to 100</div>
          </div>
        )}
        {h.feeds_in_progress !== undefined && (
          <div className="card">
            <div className="card-title">Feeds in progress</div>
            <div className={`card-value${h.feeds_in_progress > 0 ? " alert" : ""}`}>{h.feeds_in_progress}</div>
            <div className="faint small">Submitted feeds still being polled</div>
          </div>
        )}
        <div className="card">
          <div className="card-title">Last publish</div>
          <div style={{ fontWeight: 600 }}>{h.last_publish_at ? formatDate(h.last_publish_at) : <span className="faint">never</span>}</div>
          <div className="faint small">Last success {h.last_success_at ? formatDate(h.last_success_at) : "never"}</div>
        </div>
      </div>
      <div className="panel">
        <div className="panel-header">
          <h3>Top errors</h3>
        </div>
        <div className="panel-body flush">
          {h.top_errors.length === 0 ? (
            <div className="empty">No errors recorded for this channel.</div>
          ) : (
            <table className="data compact">
              <thead>
                <tr>
                  <th>Message</th>
                  <th>Kind</th>
                  <th className="right">Count</th>
                </tr>
              </thead>
              <tbody>
                {h.top_errors.map((e, i) => (
                  <tr key={i}>
                    <td>{e.message}</td>
                    <td>
                      <ErrorKindPill kind={e.kind} />
                    </td>
                    <td className="num">{e.count}</td>
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
