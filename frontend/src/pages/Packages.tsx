// EXP-13: Shopify update packages. List and "New package" dialog.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useChannels } from "../api/hooks";
import { Dialog, Empty, ErrorBox, Spinner, StatusBadge, useToast } from "../components/Common";
import { formatDate } from "../lib/format";
import type { PackageCreate, SavedView } from "../api/types";

export function PackagesPage() {
  const [channel, setChannel] = useState("");
  const [showNew, setShowNew] = useState(false);
  const channels = useChannels();
  const q = useQuery({ queryKey: ["packages", channel], queryFn: () => api.packages.list(channel || undefined), refetchInterval: 30_000 });

  return (
    <div>
      <div className="page-header">
        <h1>Update packages</h1>
        <div className="actions">
          <select value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="">All channels</option>
            {(channels.data ?? []).map((c) => (
              <option key={c.code} value={c.code}>
                {c.label}
              </option>
            ))}
          </select>
          <button className="primary" onClick={() => setShowNew(true)}>
            New package
          </button>
        </div>
      </div>
      <p className="muted small">
        The PIM never writes to Shopify directly in Phase 1. A package is a reviewable workbook plus import-ready CSVs
        that the Shopify team decides whether to import.
      </p>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} title="Could not load packages" />}
      {q.data && q.data.length === 0 && (
        <Empty title="No packages yet">Click New package to compute a field-level diff between the PIM and Shopify.</Empty>
      )}
      {q.data && q.data.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Package</th>
                <th>Channel</th>
                <th>Status</th>
                <th>Created</th>
                <th>By</th>
                <th>Snapshot</th>
                <th className="right">Products</th>
                <th className="right">Changes</th>
                <th className="right">Files</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link to={`/packages/${encodeURIComponent(p.id)}`} className="mono">
                      {p.id}
                    </Link>
                  </td>
                  <td>{p.channel_code}</td>
                  <td>
                    <StatusBadge status={p.status} />
                  </td>
                  <td className="nowrap">{formatDate(p.created_at)}</td>
                  <td>{p.created_by}</td>
                  <td className="nowrap">{p.snapshot_at ? formatDate(p.snapshot_at) : <span className="faint">pending</span>}</td>
                  <td className="num">{p.products}</td>
                  <td className="num">{p.changes}</td>
                  <td className="num">{p.files.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {showNew && <NewPackageDialog onClose={() => setShowNew(false)} />}
    </div>
  );
}

function NewPackageDialog({ onClose }: { onClose: () => void }) {
  const channels = useChannels();
  const views = useQuery({ queryKey: ["views", "all"], queryFn: () => api.views.list() });
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();

  const [channel, setChannel] = useState("");
  const [selMode, setSelMode] = useState<"view" | "ids" | "changed">("view");
  const [viewId, setViewId] = useState("");
  const [ids, setIds] = useState("");
  const [changedSince, setChangedSince] = useState("");
  const [snapshot, setSnapshot] = useState<"api" | "csv_upload">("api");
  const [csv, setCsv] = useState<File | null>(null);

  const effectiveChannel = channel || channels.data?.find((c) => c.enabled && c.kind === "dtc")?.code || channels.data?.[0]?.code || "";

  const create = useMutation({
    mutationFn: async () => {
      const body: PackageCreate = {
        channel_code: effectiveChannel,
        selection:
          selMode === "view"
            ? { view_id: viewId }
            : selMode === "ids"
              ? { entity_ids: ids.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean) }
              : { changed_since: new Date(changedSince).toISOString() },
        snapshot: { mode: snapshot },
      };
      const pkg = await api.packages.create(body);
      if (snapshot === "csv_upload" && csv) {
        await api.packages.snapshotUpload(pkg.id, csv);
      }
      return pkg;
    },
    onSuccess: (pkg) => {
      toast("Package created. It will build in the background.", "ok");
      qc.invalidateQueries({ queryKey: ["packages"] });
      onClose();
      navigate(`/packages/${encodeURIComponent(pkg.id)}`);
    },
  });

  const valid =
    !!effectiveChannel &&
    (selMode === "view" ? !!viewId : selMode === "ids" ? ids.trim().length > 0 : !!changedSince) &&
    (snapshot === "api" || !!csv);

  return (
    <Dialog
      title="New update package"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={!valid || create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? "Creating" : "Create package"}
          </button>
        </>
      }
    >
      <div className="stack gap16">
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
                {(views.data ?? []).map((v: SavedView) => (
                  <option key={v.id} value={v.id}>
                    {v.name} ({v.level}, {v.owner_email})
                  </option>
                ))}
              </select>
            )}
            {selMode === "ids" && (
              <textarea
                value={ids}
                onChange={(e) => setIds(e.target.value)}
                placeholder="One entity id, SKU, or style-color per line, or separated by commas"
                style={{ width: "100%" }}
              />
            )}
            {selMode === "changed" && (
              <input type="datetime-local" value={changedSince} onChange={(e) => setChangedSince(e.target.value)} />
            )}
          </div>
        </div>

        <div>
          <div className="muted small mb8">Current Shopify state (snapshot)</div>
          <div className="row">
            <label className="inline">
              <input type="radio" checked={snapshot === "api"} onChange={() => setSnapshot("api")} /> Read from Shopify Admin API (read_products)
            </label>
            <label className="inline">
              <input type="radio" checked={snapshot === "csv_upload"} onChange={() => setSnapshot("csv_upload")} /> Upload Shopify product CSV export
            </label>
          </div>
          {snapshot === "csv_upload" && (
            <input className="mt8" type="file" accept=".csv,text/csv" onChange={(e) => setCsv(e.target.files?.[0] ?? null)} />
          )}
        </div>
        {create.isError && <ErrorBox error={create.error} title="Could not create the package" />}
      </div>
    </Dialog>
  );
}
