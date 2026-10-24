// App shell: left nav, top bar with signed-in email and notification bell (DM-09), ERP staleness banner (IMP-09).

import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useHealth, useMe } from "../api/hooks";
import { formatDate, hoursSince } from "../lib/format";
import { NotificationBell } from "./NotificationBell";

const NAV: { to: string; label: string; end?: boolean; sub?: boolean }[] = [
  { to: "/", label: "Home", end: true },
  { to: "/products", label: "Products" },
  { to: "/workflows", label: "My Work" },
  { to: "/approvals", label: "Approvals" },
  { to: "/imports", label: "Imports" },
  { to: "/worksheets", label: "Worksheets" },
  { to: "/bulk", label: "Bulk actions" },
  { to: "/exports", label: "Exports" },
  { to: "/packages", label: "Packages" },
  { to: "/images", label: "Images" },
  { to: "/reference", label: "Reference data" },
  { to: "/admin", label: "Admin", end: true },
  { to: "/admin/rules", label: "Rules", sub: true },
];

export function AppShell() {
  const me = useMe();
  const health = useHealth();
  const loc = useLocation();
  const flush = loc.pathname === "/products";

  const h = health.data;
  const stale = h?.erp_stale;
  const age = hoursSince(h?.erp_last_load_at);

  return (
    <div className="shell">
      <aside className="shell-nav">
        <div className="shell-brand">
          <span className="dot" />
          Swim USA PIM
        </div>
        <nav>
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) => `${isActive ? "active" : ""}${n.sub ? " sub" : ""}`}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div style={{ marginTop: "auto", padding: 12 }} className="faint small">
          {h ? `Version ${h.version}` : ""}
          {h?.erp_last_load_at && (
            <div title="Last successful Style Master load">ERP load {formatDate(h.erp_last_load_at)}</div>
          )}
        </div>
      </aside>
      <header className="shell-topbar">
        <span className="app-name">Swim USA PIM</span>
        <span className="user">
          <NotificationBell />
          {me.isLoading && <span>Signing in</span>}
          {me.isError && <span style={{ color: "var(--red)" }}>Could not load /api/me</span>}
          {me.data && (
            <>
              <span>{me.data.email}</span>
              {me.data.roles.length > 0 && <span className="badge teal">{me.data.roles.join(", ")}</span>}
            </>
          )}
        </span>
      </header>
      <div className="shell-banner">
        {stale && (
          <div className="banner warn" role="status">
            Style Master data is older than {h?.erp_stale_threshold_hours} hours
            {age !== null ? ` (${age} hours old)` : ""}, last load at{" "}
            {h?.erp_last_load_at ? formatDate(h.erp_last_load_at) : "unknown"}. Check the ingest job under Admin, Telemetry.
          </div>
        )}
        {health.isError && (
          <div className="banner error" role="status">
            The API is not responding. Data on this page may be unavailable.
          </div>
        )}
      </div>
      <main className={`shell-main${flush ? " flush" : ""}`}>
        <Outlet />
      </main>
    </div>
  );
}
