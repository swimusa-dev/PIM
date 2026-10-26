// DM-10, GOV-03: Home dashboard. Cards, products blocking launches, readiness by channel, recent ingest and packages,
// and the quality by family card.

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Empty, ErrorBox, Spinner, StatusBadge } from "../components/Common";
import { formatDate } from "../lib/format";
import { QualityDashboard } from "../admin/Quality";

export function HomePage() {
  const q = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 120_000 });

  if (q.isLoading) return <Spinner label="Loading dashboard" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load the dashboard" />;
  const d = q.data!;

  return (
    <div className="stack gap16">
      <div className="page-header hero">
        <div>
          <h1>The Fitting Room PIM</h1>
          <div className="hero-subtitle">{"Swim USA's Style Master"}</div>
          <div className="muted">Built for every brand</div>
        </div>
      </div>

      <div className="cards">
        <Card title="My open tasks" value={d.open_tasks} />
        <Card title="Overdue" value={d.overdue} alert={d.overdue > 0} />
        <Card title="AI suggestions pending" value={d.ai_pending} link="/approvals" />
        <Card title="Open conflicts" value={d.conflicts_open} alert={d.conflicts_open > 0} />
      </div>

      <div className="two-col">
        <div className="panel">
          <div className="panel-header">
            <h3>Products blocking upcoming launches</h3>
            <Link to="/products" className="small">
              Open product grid
            </Link>
          </div>
          <div className="panel-body flush">
            {d.blocking_launches.length === 0 ? (
              <Empty title="Nothing is blocking a launch">
                Products with a launch date and a channel that is not ready will appear here.
              </Empty>
            ) : (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>Launch</th>
                    <th className="right">Days left</th>
                    <th>Channels not ready</th>
                  </tr>
                </thead>
                <tbody>
                  {d.blocking_launches.map((b) => (
                    <tr key={b.entity_id}>
                      <td>
                        <Link to={`/products/${encodeURIComponent(b.entity_id)}`}>{b.label}</Link>
                      </td>
                      <td className="nowrap">{formatDate(b.launch_date, false)}</td>
                      <td className="num" style={{ color: b.days_left <= 7 ? "var(--red)" : undefined }}>
                        {b.days_left}
                      </td>
                      <td>
                        <div className="chips">
                          {b.channels_not_ready.map((c) => (
                            <span key={c} className="badge red">
                              {c}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Readiness by channel</h3>
            <div className="legend">
              <span>
                <i style={{ background: "var(--green)" }} />
                Ready
              </span>
              <span>
                <i style={{ background: "var(--amber)" }} />
                Not ready
              </span>
              <span>
                <i style={{ background: "var(--border-strong)" }} />
                Ineligible
              </span>
            </div>
          </div>
          <div className="panel-body stack">
            {d.readiness_by_channel.length === 0 && (
              <Empty title="No channels configured">Add a channel under Admin, Channels to see readiness here.</Empty>
            )}
            {d.readiness_by_channel.map((c) => {
              const total = c.ready + c.not_ready + c.ineligible || 1;
              const pct = (n: number) => `${(n / total) * 100}%`;
              return (
                <div key={c.channel_code}>
                  <div className="row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
                    <span>
                      <b>{c.label}</b> <span className="faint mono">{c.channel_code}</span>
                    </span>
                    <span className="muted small">
                      {c.ready} ready, {c.not_ready} not ready, {c.ineligible} ineligible
                    </span>
                  </div>
                  <div className="bar" title={`${c.ready} ready / ${c.not_ready} not ready / ${c.ineligible} ineligible`}>
                    <div className="seg ready" style={{ width: pct(c.ready) }} />
                    <div className="seg not-ready" style={{ width: pct(c.not_ready) }} />
                    <div className="seg ineligible" style={{ width: pct(c.ineligible) }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <QualityDashboard fixedBy="family" compact />

      <div className="two-col">
        <div className="panel">
          <div className="panel-header">
            <h3>Recent Style Master ingest runs</h3>
            <Link to="/admin/telemetry" className="small">
              Telemetry
            </Link>
          </div>
          <div className="panel-body flush">
            {d.recent_ingest.length === 0 ? (
              <Empty title="No ingest runs yet">Run the ingest from Admin, Telemetry to load the Style Master.</Empty>
            ) : (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Started</th>
                    <th>Status</th>
                    <th className="right">Read</th>
                    <th className="right">Created</th>
                    <th className="right">Updated</th>
                    <th className="right">Discontinued</th>
                    <th className="right">Placeholders removed</th>
                  </tr>
                </thead>
                <tbody>
                  {d.recent_ingest.map((r) => (
                    <tr key={r.id}>
                      <td className="nowrap">{formatDate(r.started_at)}</td>
                      <td>
                        <StatusBadge status={r.status} />
                      </td>
                      <td className="num">{r.rows_read}</td>
                      <td className="num">{r.created}</td>
                      <td className="num">{r.updated}</td>
                      <td className="num">{r.discontinued}</td>
                      <td className="num">{r.placeholders_removed}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Recent update packages</h3>
            <Link to="/packages" className="small">
              All packages
            </Link>
          </div>
          <div className="panel-body flush">
            {d.recent_packages.length === 0 ? (
              <Empty title="No packages yet">Create a Shopify update package from the Packages page.</Empty>
            ) : (
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Package</th>
                    <th>Channel</th>
                    <th>Created</th>
                    <th>Status</th>
                    <th className="right">Products</th>
                    <th className="right">Changes</th>
                  </tr>
                </thead>
                <tbody>
                  {d.recent_packages.map((p) => (
                    <tr key={p.id}>
                      <td>
                        <Link to={`/packages/${encodeURIComponent(p.id)}`} className="mono">
                          {p.id}
                        </Link>
                      </td>
                      <td>{p.channel_code}</td>
                      <td className="nowrap">{formatDate(p.created_at)}</td>
                      <td>
                        <StatusBadge status={p.status} />
                      </td>
                      <td className="num">{p.products}</td>
                      <td className="num">{p.changes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Card({ title, value, alert, link }: { title: string; value: number; alert?: boolean; link?: string }) {
  const inner = (
    <div className="card">
      <div className="card-title">{title}</div>
      <div className={`card-value${alert ? " alert" : ""}`}>{value}</div>
    </div>
  );
  return link ? (
    <Link to={link} style={{ textDecoration: "none", color: "inherit" }}>
      {inner}
    </Link>
  ) : (
    inner
  );
}
