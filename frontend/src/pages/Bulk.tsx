// DM-04: Bulk action history with reports and per-action rollback.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { rowsOf } from "../api/hooks";
import type { BulkAction } from "../api/types";
import { Badge, Confirm, Dialog, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { BULK_KINDS, BulkReport, bulkStatusColor } from "../grid/BulkActionsDialog";
import { formatDate, LEVEL_LABEL } from "../lib/format";

export function BulkPage() {
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<BulkAction | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["bulk", "list", page],
    queryFn: () => api.bulk.list(page),
    refetchInterval: (query) => (rowsOf(query.state.data).some((a) => a.status === "queued" || a.status === "running") ? 5000 : false),
  });
  const rows = rowsOf(q.data);
  const total = q.data && !Array.isArray(q.data) ? q.data.total : rows.length;

  const rollback = useMutation({
    mutationFn: (id: string) => api.bulk.rollback(id),
    onSuccess: () => {
      toast("Bulk action rolled back.", "ok");
      setConfirmId(null);
      qc.invalidateQueries({ queryKey: ["bulk"] });
      qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
    },
    onError: (e) => toast(`Rollback failed: ${(e as Error).message}`, "error"),
  });

  const kindLabel = (k: string) => BULK_KINDS.find((x) => x.kind === k)?.label ?? k;
  const describeParams = (a: BulkAction) =>
    Object.entries(a.params ?? {})
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v)}`)
      .join("; ");

  return (
    <div>
      <div className="page-header">
        <h1>Bulk actions</h1>
        <Link to="/products" className="btn">
          Select products in the grid
        </Link>
      </div>
      <p className="muted small">Every bulk action is previewed before it runs and keeps a change set so it can be rolled back.</p>
      {q.isLoading && <Spinner label="Loading bulk actions" />}
      {q.isError && <ErrorBox error={q.error} title="Could not load bulk actions" />}
      {q.data && rows.length === 0 && <Empty title="No bulk actions yet">Select rows in the product grid and click Bulk actions.</Empty>}
      {rows.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Action</th>
                <th>Selection</th>
                <th>Parameters</th>
                <th>Status</th>
                <th>Created</th>
                <th>By</th>
                <th className="right">Total</th>
                <th className="right">Changed</th>
                <th className="right">Failed</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td>
                    <b>{kindLabel(a.kind)}</b>
                    <div className="faint small mono">{a.id}</div>
                  </td>
                  <td className="small">
                    {LEVEL_LABEL[a.selection.level] ?? a.selection.level}
                    {a.selection.view_id ? `, view ${a.selection.view_id}` : a.selection.entity_ids ? `, ${a.selection.entity_ids.length} products` : ""}
                  </td>
                  <td className="small" style={{ maxWidth: 320 }}>
                    {describeParams(a)}
                  </td>
                  <td>
                    <Badge color={bulkStatusColor(a.status)}>{a.status.replace(/_/g, " ")}</Badge>
                  </td>
                  <td className="nowrap">{formatDate(a.created_at)}</td>
                  <td>{a.created_by}</td>
                  <td className="num">{a.preview?.total ?? ""}</td>
                  <td className="num">{a.report?.changed ?? ""}</td>
                  <td className="num">{a.report?.failed ?? ""}</td>
                  <td className="nowrap">
                    <button className="small" onClick={() => setOpen(a)}>
                      Report
                    </button>{" "}
                    {a.status === "succeeded" && (
                      <button className="small danger" onClick={() => setConfirmId(a.id)}>
                        Rollback
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row" style={{ justifyContent: "flex-end", padding: 8 }}>
            <button className="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </button>
            <span className="muted small">
              Page {page} ({total} actions)
            </span>
            <button className="small" disabled={rows.length === 0 || (total !== undefined && page * Math.max(rows.length, 1) >= total)} onClick={() => setPage((p) => p + 1)}>
              Next
            </button>
          </div>
        </div>
      )}
      {open && (
        <Dialog
          title={`${kindLabel(open.kind)} report`}
          onClose={() => setOpen(null)}
          wide
          footer={
            <button className="primary" onClick={() => setOpen(null)}>
              Close
            </button>
          }
        >
          <div className="stack">
            <div className="row">
              <Badge color={bulkStatusColor(open.status)}>{open.status.replace(/_/g, " ")}</Badge>
              <span className="muted small">{describeParams(open)}</span>
            </div>
            <BulkReport action={open} />
          </div>
        </Dialog>
      )}
      {confirmId && (
        <Confirm
          title="Roll back this bulk action?"
          message="The action's change set is reverted. Values edited again afterwards are reported, not overwritten."
          confirmLabel="Roll back"
          busy={rollback.isPending}
          onCancel={() => setConfirmId(null)}
          onConfirm={() => rollback.mutate(confirmId)}
        />
      )}
    </div>
  );
}
