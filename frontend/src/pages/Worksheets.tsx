// IMP-12: Keyed worksheet export. Pick a saved view or paste entity ids, level, attribute groups,
// ERP context; generate; list of generated worksheets with downloads.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useGroups } from "../api/hooks";
import type { Level, WorksheetCreate } from "../api/types";
import { Badge, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { formatDate, LEVEL_LABEL } from "../lib/format";

export function WorksheetsPage() {
  const groups = useGroups();
  const views = useQuery({ queryKey: ["views", "all"], queryFn: () => api.views.list() });
  const list = useQuery({ queryKey: ["worksheets"], queryFn: api.worksheets.list });
  const qc = useQueryClient();
  const toast = useToast();

  const [mode, setMode] = useState<"view" | "ids">("view");
  const [viewId, setViewId] = useState("");
  const [ids, setIds] = useState("");
  const [level, setLevel] = useState<Level>("style_color");
  const [groupCodes, setGroupCodes] = useState<string[]>([]);
  const [erp, setErp] = useState(false);

  const selectedView = views.data?.find((v) => v.id === viewId);
  const effectiveLevel = mode === "view" && selectedView ? selectedView.level : level;
  const sortedGroups = useMemo(() => (groups.data ?? []).slice().sort((a, b) => a.sort_order - b.sort_order), [groups.data]);

  const generate = useMutation({
    mutationFn: () => {
      const body: WorksheetCreate = {
        selection:
          mode === "view"
            ? { view_id: viewId, level: effectiveLevel }
            : { entity_ids: ids.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean), level: effectiveLevel },
        group_codes: groupCodes,
        include_erp_context: erp,
      };
      return api.worksheets.create(body);
    },
    onSuccess: (w) => {
      toast(`Worksheet ${w.file_name} generated with ${w.rows} rows.`, "ok");
      qc.invalidateQueries({ queryKey: ["worksheets"] });
    },
  });

  const toggleGroup = (code: string) => setGroupCodes((g) => (g.includes(code) ? g.filter((x) => x !== code) : [...g, code]));
  const valid = (mode === "view" ? !!viewId : ids.trim().length > 0) && groupCodes.length > 0;

  return (
    <div>
      <div className="page-header">
        <h1>Worksheet export</h1>
        <Link to="/imports" className="btn">
          Imports
        </Link>
      </div>
      <p className="muted small">
        A keyed worksheet is an XLSX with the products you choose and the attribute groups you want filled in. Each row carries a
        hidden key, so when it comes back the import maps and matches automatically and locked columns are protected.
      </p>
      <div className="two-col">
        <div className="panel">
          <div className="panel-header">
            <h3>New worksheet</h3>
          </div>
          <div className="panel-body stack gap16">
            <div>
              <div className="muted small mb8">Products</div>
              <div className="row">
                <label className="inline">
                  <input type="radio" checked={mode === "view"} onChange={() => setMode("view")} /> Saved view
                </label>
                <label className="inline">
                  <input type="radio" checked={mode === "ids"} onChange={() => setMode("ids")} /> Pasted entity ids
                </label>
              </div>
              <div className="mt8">
                {mode === "view" && (
                  <>
                    {views.isLoading && <Spinner />}
                    {views.isError && <ErrorBox error={views.error} title="Could not load saved views" />}
                    <select value={viewId} onChange={(e) => setViewId(e.target.value)} style={{ width: "100%" }}>
                      <option value="">Choose a saved view</option>
                      {(views.data ?? []).map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.name} ({LEVEL_LABEL[v.level]}, {v.owner_email})
                        </option>
                      ))}
                    </select>
                  </>
                )}
                {mode === "ids" && (
                  <textarea value={ids} onChange={(e) => setIds(e.target.value)} placeholder="One entity id per line, or separated by commas" style={{ width: "100%" }} />
                )}
              </div>
            </div>
            <label className="field">
              Level
              <select value={effectiveLevel} disabled={mode === "view" && !!selectedView} onChange={(e) => setLevel(e.target.value as Level)}>
                {(["style", "style_color", "sku"] as Level[]).map((l) => (
                  <option key={l} value={l}>
                    {LEVEL_LABEL[l]}
                  </option>
                ))}
              </select>
            </label>
            <div>
              <div className="muted small mb8">Attribute groups to include</div>
              {groups.isLoading && <Spinner />}
              {groups.isError && <ErrorBox error={groups.error} title="Could not load attribute groups" />}
              <div className="row">
                {sortedGroups.map((g) => (
                  <label key={g.code} className="inline">
                    <input type="checkbox" checked={groupCodes.includes(g.code)} onChange={() => toggleGroup(g.code)} />
                    {g.label}
                    {g.read_only && <Badge title="Read-only group: columns are exported locked">locked</Badge>}
                  </label>
                ))}
              </div>
              {sortedGroups.length > 0 && (
                <div className="row mt8">
                  <button className="link small" onClick={() => setGroupCodes(sortedGroups.map((g) => g.code))}>
                    Select all
                  </button>
                  <button className="link small" onClick={() => setGroupCodes([])}>
                    Clear
                  </button>
                </div>
              )}
            </div>
            <label className="inline">
              <input type="checkbox" checked={erp} onChange={(e) => setErp(e.target.checked)} />
              Include ERP context columns (read-only identifiers and Style Master fields)
            </label>
            {generate.isError && <ErrorBox error={generate.error} title="Could not generate the worksheet" />}
            <div className="row">
              <button className="primary" disabled={!valid || generate.isPending} onClick={() => generate.mutate()}>
                {generate.isPending ? "Generating" : "Generate"}
              </button>
              {generate.data && (
                <a className="btn" href={generate.data.url} download>
                  Download {generate.data.file_name}
                </a>
              )}
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Generated worksheets</h3>
          </div>
          <div className="banner info" style={{ margin: 12 }}>
            Return the file through Imports with source <b>Keyed worksheet</b>.
          </div>
          {list.isLoading && (
            <div className="panel-body">
              <Spinner />
            </div>
          )}
          {list.isError && (
            <div className="panel-body">
              <ErrorBox error={list.error} title="Could not load worksheets" />
            </div>
          )}
          {list.data && list.data.length === 0 && <Empty title="No worksheets yet" />}
          {list.data && list.data.length > 0 && (
            <table className="data compact">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Created</th>
                  <th>By</th>
                  <th className="right">Rows</th>
                  <th>Groups</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.data.map((w) => (
                  <tr key={w.id}>
                    <td className="mono">{w.file_name}</td>
                    <td className="nowrap">{formatDate(w.created_at)}</td>
                    <td>{w.created_by}</td>
                    <td className="num">{w.rows}</td>
                    <td className="small">{w.group_codes.map((c) => groups.data?.find((g) => g.code === c)?.label ?? c).join(", ")}</td>
                    <td>
                      <a className="btn small" href={api.worksheets.fileUrl(w.id)} download>
                        Download
                      </a>
                    </td>
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
