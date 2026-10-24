// EXP-06: Scheduled exports. ExportSchedule form (enabled, delta or full, every N hours or at a time of day,
// timezone, saved view), "Run now" with the skipped reason, and the last run result.

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, channelApi } from "../../api/client";
import type { Channel, ExportSchedule } from "../../api/types";
import { Badge, ErrorBox, Spinner, StatusBadge, useToast } from "../../components/Common";
import { formatDate } from "../../lib/format";

const EMPTY: ExportSchedule = { enabled: false, mode: "delta", every_hours: 24, at_hour: null, at_minute: 0, timezone: "America/New_York", view_id: null };

export function ScheduleTab({ channel, canEdit }: { channel: Channel; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["channel", channel.code, "schedule"], queryFn: () => channelApi.schedule(channel.code) });
  const views = useQuery({ queryKey: ["views", "all"], queryFn: () => api.views.list() });
  const [s, setS] = useState<ExportSchedule>(EMPTY);
  const [cadence, setCadence] = useState<"every" | "at">("every");

  useEffect(() => {
    if (q.data) {
      setS({ ...EMPTY, ...q.data });
      setCadence(q.data.at_hour !== null && q.data.at_hour !== undefined ? "at" : "every");
    }
  }, [q.data]);

  const save = useMutation({
    mutationFn: () =>
      channelApi.saveSchedule(channel.code, {
        ...s,
        every_hours: cadence === "every" ? (s.every_hours ?? 24) : null,
        at_hour: cadence === "at" ? (s.at_hour ?? 0) : null,
        at_minute: cadence === "at" ? (s.at_minute ?? 0) : 0,
        view_id: s.view_id || null,
      }),
    onSuccess: () => {
      toast("Schedule saved.", "ok");
      qc.invalidateQueries({ queryKey: ["channel", channel.code, "schedule"] });
    },
    onError: (e) => toast(`Save failed: ${(e as Error).message}`, "error"),
  });
  const runNow = useMutation({
    mutationFn: () => channelApi.runNow(channel.code),
    onSuccess: (r) => {
      if (r.status === "started") toast("Scheduled export started. Check the Exports page for the result.", "ok");
      else toast(`Run skipped${r.reason ? `: ${r.reason}` : " (a run is already in progress)"}`, "warn");
      qc.invalidateQueries({ queryKey: ["channel", channel.code, "schedule"] });
      qc.invalidateQueries({ queryKey: ["publishes"] });
    },
    onError: (e) => toast(`Run failed: ${(e as Error).message}`, "error"),
  });

  if (q.isLoading) return <Spinner label="Loading schedule" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load the schedule" />;

  const valid = s.timezone.trim().length > 0 && (cadence === "every" ? (s.every_hours ?? 0) > 0 : (s.at_hour ?? -1) >= 0 && (s.at_hour ?? 99) <= 23);

  return (
    <div className="stack gap16">
      {!canEdit && <div className="banner warn">You can view this schedule but editing it needs the edit_profile right for {channel.label}.</div>}
      <div className="panel">
        <div className="panel-header">
          <h3>Schedule</h3>
          <div className="row">
            <button className="small" disabled={runNow.isPending} onClick={() => runNow.mutate()} title="Run the scheduled export once now">
              {runNow.isPending ? "Starting" : "Run now"}
            </button>
            <button className="primary small" disabled={!canEdit || !valid || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? "Saving" : "Save schedule"}
            </button>
          </div>
        </div>
        <div className="panel-body">
          <fieldset disabled={!canEdit} style={{ border: "none", padding: 0, margin: 0 }}>
            <div className="form-grid">
              <label className="inline" style={{ alignSelf: "end" }}>
                <input type="checkbox" checked={s.enabled} onChange={(e) => setS({ ...s, enabled: e.target.checked })} /> Enabled
              </label>
              <label className="field">
                Mode
                <select value={s.mode} onChange={(e) => setS({ ...s, mode: e.target.value as ExportSchedule["mode"] })}>
                  <option value="delta">Delta (only products changed since the last successful publish)</option>
                  <option value="full">Full (every eligible product)</option>
                </select>
              </label>
              <label className="field">
                Cadence
                <select value={cadence} onChange={(e) => setCadence(e.target.value as "every" | "at")}>
                  <option value="every">Every N hours</option>
                  <option value="at">Daily at a time</option>
                </select>
              </label>
              {cadence === "every" ? (
                <label className="field">
                  Every (hours)
                  <input type="number" min={1} value={s.every_hours ?? ""} onChange={(e) => setS({ ...s, every_hours: e.target.value === "" ? null : Number(e.target.value) })} />
                </label>
              ) : (
                <div className="row" style={{ alignItems: "end" }}>
                  <label className="field">
                    Hour (0 to 23)
                    <input type="number" min={0} max={23} value={s.at_hour ?? ""} onChange={(e) => setS({ ...s, at_hour: e.target.value === "" ? null : Number(e.target.value) })} />
                  </label>
                  <label className="field">
                    Minute
                    <input type="number" min={0} max={59} value={s.at_minute ?? 0} onChange={(e) => setS({ ...s, at_minute: Number(e.target.value) })} />
                  </label>
                </div>
              )}
              <label className="field">
                Timezone (IANA name)
                <input value={s.timezone} placeholder="America/New_York" onChange={(e) => setS({ ...s, timezone: e.target.value })} />
              </label>
              <label className="field">
                Saved view (optional, limits the selection)
                <select value={s.view_id ?? ""} onChange={(e) => setS({ ...s, view_id: e.target.value || null })}>
                  <option value="">All eligible products</option>
                  {(views.data ?? []).map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name} ({v.level}, {v.owner_email})
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </fieldset>
          {save.isError && <ErrorBox error={save.error} title="Save failed" />}
        </div>
      </div>
      <div className="panel">
        <div className="panel-header">
          <h3>Last run</h3>
        </div>
        <div className="panel-body">
          {q.data?.last_run_at ? (
            <dl className="kv">
              <dt>Ran at</dt>
              <dd>{formatDate(q.data.last_run_at)}</dd>
              <dt>Result</dt>
              <dd>{q.data.last_result ? <StatusBadge status={q.data.last_result} /> : <Badge>unknown</Badge>}</dd>
            </dl>
          ) : (
            <span className="muted">This schedule has not run yet.</span>
          )}
          {runNow.data?.status === "skipped" && (
            <div className="banner warn mt8">Run skipped{runNow.data.reason ? `: ${runNow.data.reason}` : ", a run is already in progress"}.</div>
          )}
        </div>
      </div>
    </div>
  );
}
