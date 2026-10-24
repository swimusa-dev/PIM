// DM-09: Notification bell in the top bar. Polls the unread count every 60 seconds; clicking an
// item marks it read and navigates to its link.

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Notification } from "../api/types";
import { formatDate } from "../lib/format";
import { Badge, ErrorBox, Spinner } from "./Common";

const KIND_COLOR: Record<string, string> = {
  mention: "purple",
  workflow: "teal",
  approval: "amber",
  import: "blue",
  bulk: "blue",
  conflict: "red",
};

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const hostRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.notifications.list(),
    refetchInterval: 60_000,
  });
  const markRead = useMutation({
    mutationFn: (ids?: string[]) => api.notifications.markRead(ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (hostRef.current && !hostRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const unread = q.data?.unread ?? 0;
  const rows = q.data?.rows ?? [];

  const openItem = (n: Notification) => {
    if (!n.read_at) markRead.mutate([n.id]);
    setOpen(false);
    if (n.link) {
      if (/^https?:/i.test(n.link)) window.open(n.link, "_blank", "noopener");
      else navigate(n.link);
    }
  };

  return (
    <div className="popover-host" ref={hostRef}>
      <button
        className="bell"
        onClick={() => setOpen((o) => !o)}
        aria-label={unread > 0 ? `${unread} unread notifications` : "Notifications"}
        title="Notifications"
      >
        <span aria-hidden="true">&#128276;</span>
        {unread > 0 && <span className="bell-count">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="popover notif-popover" role="menu">
          <div className="row" style={{ justifyContent: "space-between", padding: "2px 4px 6px" }}>
            <b>Notifications</b>
            <button className="link small" disabled={unread === 0 || markRead.isPending} onClick={() => markRead.mutate(undefined)}>
              Mark all read
            </button>
          </div>
          {q.isLoading && <Spinner />}
          {q.isError && <ErrorBox error={q.error} title="Could not load notifications" />}
          {q.data && rows.length === 0 && <div className="empty">No notifications yet.</div>}
          {rows.map((n) => (
            <div
              key={n.id}
              className={`notif${n.read_at ? "" : " unread"}`}
              role="menuitem"
              tabIndex={0}
              onClick={() => openItem(n)}
              onKeyDown={(e) => e.key === "Enter" && openItem(n)}
            >
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className="notif-title">{n.title}</span>
                <Badge color={KIND_COLOR[n.kind]}>{n.kind}</Badge>
              </div>
              {n.body && <div className="small muted">{n.body}</div>}
              <div className="faint small">{formatDate(n.created_at)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
