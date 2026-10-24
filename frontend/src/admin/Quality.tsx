// GOV-03: Admin > Quality. Settings form (excluded groups, enabled checks, weights, grade bands), "Recompute now",
// and the dashboard table by family, season or channel with grade counts as a stacked bar and the average score.

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { qualityApi } from "../api/client";
import { isAdmin, useGroups, useMe } from "../api/hooks";
import type { QualityDashboardBy, QualitySettings } from "../api/types";
import { Empty, ErrorBox, GradeBar, Spinner, useToast } from "../components/Common";

const GRADES = ["A", "B", "C", "D", "E"] as const;

export function QualityTab() {
  const me = useMe();
  const admin = isAdmin(me.data);
  const qc = useQueryClient();
  const toast = useToast();
  const groups = useGroups();
  const settings = useQuery({ queryKey: ["quality", "settings"], queryFn: qualityApi.settings });
  const [d, setD] = useState<QualitySettings | null>(null);
  const [newCheck, setNewCheck] = useState("");
  useEffect(() => {
    if (settings.data && !d) setD(settings.data);
  }, [settings.data, d]);

  const checkCodes = useMemo(() => {
    const s = new Set<string>([...Object.keys(d?.weights ?? {}), ...(d?.enabled_checks ?? [])]);
    return Array.from(s).sort();
  }, [d]);

  const save = useMutation({
    mutationFn: () => qualityApi.saveSettings(d!),
    onSuccess: (s) => {
      toast("Quality settings saved. Recompute to apply them to existing scores.", "ok");
      setD(s);
      qc.invalidateQueries({ queryKey: ["quality"] });
    },
  });
  const recompute = useMutation({
    mutationFn: () => qualityApi.recompute(),
    onSuccess: (r) => {
      toast(`Recomputed ${r.computed} score${r.computed === 1 ? "" : "s"}.`, "ok");
      qc.invalidateQueries({ queryKey: ["quality"] });
      qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
      qc.invalidateQueries({ queryKey: ["product"], refetchType: "none" });
    },
    onError: (e) => toast(`Recompute failed: ${(e as Error).message}`, "error"),
  });

  const bandsValid = !!d && d.grade_bands.A > d.grade_bands.B && d.grade_bands.B > d.grade_bands.C && d.grade_bands.C > d.grade_bands.D;

  return (
    <div className="stack gap16">
      <div className="panel">
        <div className="panel-header">
          <h3>Settings</h3>
          <div className="row">
            <button className="small" disabled={recompute.isPending} onClick={() => recompute.mutate()} title="Recompute every style-color (a job when large)">
              {recompute.isPending ? "Recomputing" : "Recompute now"}
            </button>
            {admin && d && (
              <button className="primary small" disabled={save.isPending || !bandsValid} onClick={() => save.mutate()}>
                {save.isPending ? "Saving" : "Save settings"}
              </button>
            )}
          </div>
        </div>
        <div className="panel-body stack">
          {settings.isLoading && <Spinner label="Loading settings" />}
          {settings.isError && <ErrorBox error={settings.error} title="Could not load quality settings" />}
          {d && (
            <fieldset disabled={!admin} style={{ border: 0, padding: 0, margin: 0 }}>
              <div className="form-grid">
                <div className="field">
                  Excluded attribute groups (not counted in completeness checks)
                  <div className="row" style={{ flexWrap: "wrap" }}>
                    {(groups.data ?? []).map((g) => (
                      <label key={g.code} className="inline">
                        <input
                          type="checkbox"
                          checked={d.excluded_groups.includes(g.code)}
                          onChange={() =>
                            setD({ ...d, excluded_groups: d.excluded_groups.includes(g.code) ? d.excluded_groups.filter((c) => c !== g.code) : [...d.excluded_groups, g.code] })
                          }
                        />{" "}
                        {g.label}
                      </label>
                    ))}
                    {groups.data && groups.data.length === 0 && <span className="faint small">No groups defined.</span>}
                  </div>
                </div>
                <div className="field">
                  Grade bands (minimum score, E below D)
                  <div className="row" style={{ flexWrap: "wrap" }}>
                    {(["A", "B", "C", "D"] as const).map((g) => (
                      <label key={g} className="inline">
                        <span className={`grade g${g}`}>{g}</span>
                        <input
                          type="number"
                          min={0}
                          max={100}
                          style={{ width: 70 }}
                          value={d.grade_bands[g]}
                          onChange={(e) => setD({ ...d, grade_bands: { ...d.grade_bands, [g]: Number(e.target.value) } })}
                        />
                      </label>
                    ))}
                  </div>
                  {!bandsValid && <span className="field-error">Bands must decrease from A to D.</span>}
                </div>
              </div>
              <div className="mt16">
                <div className="muted small mb8">Checks: enabled and weight</div>
                {checkCodes.length === 0 && <span className="faint small">No checks configured yet. Add a check code below.</span>}
                <table className="data compact" style={{ maxWidth: 520 }}>
                  <tbody>
                    {checkCodes.map((c) => (
                      <tr key={c}>
                        <td>
                          <label className="inline">
                            <input
                              type="checkbox"
                              checked={d.enabled_checks.includes(c)}
                              onChange={() =>
                                setD({ ...d, enabled_checks: d.enabled_checks.includes(c) ? d.enabled_checks.filter((x) => x !== c) : [...d.enabled_checks, c] })
                              }
                            />
                            <span className="mono">{c}</span>
                          </label>
                        </td>
                        <td className="num">
                          <input
                            type="number"
                            min={0}
                            step={0.5}
                            style={{ width: 80 }}
                            value={d.weights[c] ?? 1}
                            onChange={(e) => setD({ ...d, weights: { ...d.weights, [c]: Number(e.target.value) } })}
                          />
                        </td>
                        <td>
                          <button
                            className="link small"
                            onClick={() => {
                              const w = { ...d.weights };
                              delete w[c];
                              setD({ ...d, weights: w, enabled_checks: d.enabled_checks.filter((x) => x !== c) });
                            }}
                          >
                            remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {admin && (
                  <div className="row mt8">
                    <input value={newCheck} placeholder="check code, e.g. required_filled" onChange={(e) => setNewCheck(e.target.value)} style={{ width: 240 }} />
                    <button
                      className="small"
                      disabled={!newCheck.trim()}
                      onClick={() => {
                        const c = newCheck.trim();
                        setD({ ...d, weights: { ...d.weights, [c]: d.weights[c] ?? 1 }, enabled_checks: d.enabled_checks.includes(c) ? d.enabled_checks : [...d.enabled_checks, c] });
                        setNewCheck("");
                      }}
                    >
                      Add check
                    </button>
                  </div>
                )}
              </div>
            </fieldset>
          )}
          {save.isError && <ErrorBox error={save.error} title="Save failed" />}
          {!admin && d && <div className="faint small">Read only: changing quality settings needs the admin_metadata permission.</div>}
        </div>
      </div>

      <QualityDashboard />
    </div>
  );
}

export function QualityDashboard({ fixedBy, compact }: { fixedBy?: QualityDashboardBy; compact?: boolean }) {
  const [by, setBy] = useState<QualityDashboardBy>(fixedBy ?? "family");
  const q = useQuery({ queryKey: ["quality", "dashboard", by], queryFn: () => qualityApi.dashboard(by) });
  const rows = q.data?.rows ?? [];
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>{compact ? "Quality by family" : "Quality dashboard"}</h3>
        {!fixedBy && (
          <div className="row">
            <span className="muted small">By</span>
            <select value={by} onChange={(e) => setBy(e.target.value as QualityDashboardBy)}>
              <option value="family">Family</option>
              <option value="season">Season</option>
              <option value="channel">Channel</option>
            </select>
            <div className="legend">
              {GRADES.map((g) => (
                <span key={g}>
                  <i className={`g${g}`} />
                  {g}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="panel-body flush">
        {q.isLoading && <Spinner label="Loading dashboard" />}
        {q.isError && <ErrorBox error={q.error} title="Could not load the quality dashboard" />}
        {q.data && rows.length === 0 && <Empty title="No quality scores yet">Run Recompute now to score every style-color.</Empty>}
        {rows.length > 0 && (
          <table className="data compact">
            <thead>
              <tr>
                <th>{by === "family" ? "Family" : by === "season" ? "Season" : "Channel"}</th>
                <th style={{ width: compact ? 160 : 320 }}>Grades</th>
                {!compact && GRADES.map((g) => <th key={g} className="right">{g}</th>)}
                <th className="right">Avg score</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td>
                    {r.label || r.key || <span className="faint">none</span>}
                    {!compact && r.key !== r.label && <span className="faint small mono"> {r.key}</span>}
                  </td>
                  <td>
                    <GradeBar counts={r} />
                  </td>
                  {!compact && GRADES.map((g) => <td key={g} className="num">{r[g]}</td>)}
                  <td className="num">{Math.round(r.avg_score * 10) / 10}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
