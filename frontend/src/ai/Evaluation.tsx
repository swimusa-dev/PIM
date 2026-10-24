// AI-07: Evaluation tab of the AI page. Eval cases list with "Build set from approved copy" (attribute picker and
// limit 50) and delete; eval runs table with composite score, delta versus the baseline, passed / blocked pill,
// "Run evaluation" dialog picking a template, and a run detail expander with the sample outputs versus references.

import { Fragment, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { aiApi } from "../api/client";
import { useAttributes, useGroups } from "../api/hooks";
import type { AttributeDefinition, EvalRun } from "../api/types";
import { Badge, Confirm, Dialog, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { formatDate } from "../lib/format";
import { EvalStatusPill, pct } from "./shared";

export function EvaluationTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const attrs = useAttributes();
  const groups = useGroups();
  const [attribute, setAttribute] = useState("");
  const [templateFilter, setTemplateFilter] = useState("");
  const [building, setBuilding] = useState(false);
  const [buildAttr, setBuildAttr] = useState("");
  const [buildLimit, setBuildLimit] = useState(50);
  const [running, setRunning] = useState(false);
  const [runTemplate, setRunTemplate] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const cases = useQuery({ queryKey: ["ai", "eval", "cases", attribute], queryFn: () => aiApi.evalCases(attribute || undefined) });
  const runs = useQuery({
    queryKey: ["ai", "eval", "runs", templateFilter],
    queryFn: () => aiApi.evalRuns(templateFilter || undefined),
    refetchInterval: (q) => ((q.state.data ?? []).some((r) => r.status === "running") ? 5000 : false),
  });
  const templates = useQuery({ queryKey: ["ai", "templates", {}], queryFn: () => aiApi.templates() });

  const attrByCode = useMemo(() => new Map((attrs.data ?? []).map((a) => [a.code, a])), [attrs.data]);
  // Text attributes grouped by attribute group: the eval set is built from approved, human-written copy.
  const textAttrs = useMemo(() => {
    const m = new Map<string, AttributeDefinition[]>();
    for (const a of attrs.data ?? []) {
      if (a.data_type !== "text" && a.data_type !== "rich_text") continue;
      m.set(a.group_code, [...(m.get(a.group_code) ?? []), a]);
    }
    return Array.from(m.entries());
  }, [attrs.data]);
  const groupLabel = (code: string) => groups.data?.find((g) => g.code === code)?.label ?? code;

  const build = useMutation({
    mutationFn: () => aiApi.buildEvalCases(buildAttr, buildLimit),
    onSuccess: (r) => {
      toast(`Built ${r.created} new case${r.created === 1 ? "" : "s"}; ${r.total} in the set.`, "ok");
      setBuilding(false);
      qc.invalidateQueries({ queryKey: ["ai", "eval", "cases"] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => aiApi.deleteEvalCase(id),
    onSuccess: () => {
      setDeleting(null);
      qc.invalidateQueries({ queryKey: ["ai", "eval", "cases"] });
    },
    onError: (e) => toast(`Delete failed: ${(e as Error).message}`, "error"),
  });
  const run = useMutation({
    mutationFn: () => aiApi.runEval(runTemplate),
    onSuccess: (r) => {
      toast(r.status === "running" ? "Evaluation started." : `Evaluation ${r.status}: composite ${pct(r.scores.composite)}.`, r.status === "blocked" ? "warn" : "ok");
      setRunning(false);
      qc.invalidateQueries({ queryKey: ["ai", "eval", "runs"] });
      qc.invalidateQueries({ queryKey: ["ai", "templates"] });
    },
  });

  return (
    <div className="stack gap16">
      <div className="panel">
        <div className="panel-header">
          <h3>Eval cases</h3>
          <div className="row">
            <select value={attribute} onChange={(e) => setAttribute(e.target.value)}>
              <option value="">All attributes</option>
              {textAttrs.map(([g, list]) => (
                <optgroup key={g} label={groupLabel(g)}>
                  {list.map((a) => (
                    <option key={a.code} value={a.code}>
                      {a.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <span className="muted small">{cases.data ? `${cases.data.length} cases` : ""}</span>
            <button className="primary small" onClick={() => { setBuildAttr(attribute); setBuilding(true); }}>
              Build set from approved copy
            </button>
          </div>
        </div>
        <div className="panel-body flush" style={{ maxHeight: 360, overflow: "auto" }}>
          {cases.isLoading && <Spinner label="Loading cases" />}
          {cases.isError && <ErrorBox error={cases.error} title="Could not load eval cases" />}
          {cases.data && cases.data.length === 0 && (
            <Empty title="No eval cases">Build a set from approved, human-written values to measure templates against.</Empty>
          )}
          {cases.data && cases.data.length > 0 && (
            <table className="data compact">
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Attribute</th>
                  <th>Reference text</th>
                  <th>Added</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {cases.data.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link to={`/products/${encodeURIComponent(c.entity_id)}`}>{c.label || c.entity_id}</Link>
                    </td>
                    <td>{attrByCode.get(c.attribute_code)?.label ?? c.attribute_code}</td>
                    <td className="small" style={{ maxWidth: 480 }} title={c.reference_text}>
                      <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.reference_text}</div>
                    </td>
                    <td className="nowrap small">{formatDate(c.created_at, false)}</td>
                    <td>
                      <button className="small danger" onClick={() => setDeleting(c.id)}>
                        Delete
                      </button>
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
          <h3>Eval runs</h3>
          <div className="row">
            <select value={templateFilter} onChange={(e) => setTemplateFilter(e.target.value)}>
              <option value="">All templates</option>
              {(templates.data ?? []).map((t) => (
                <option key={t.code} value={t.code}>
                  {t.label} ({t.code})
                </option>
              ))}
            </select>
            <button className="primary small" onClick={() => { setRunTemplate(templateFilter); setRunning(true); }}>
              Run evaluation
            </button>
          </div>
        </div>
        <div className="panel-body flush">
          {runs.isLoading && <Spinner label="Loading eval runs" />}
          {runs.isError && <ErrorBox error={runs.error} title="Could not load eval runs" />}
          {runs.data && runs.data.length === 0 && (
            <Empty title="No evaluation runs">Run a template against the eval set. A run is blocked when its composite drops more than the threshold below the last passed run.</Empty>
          )}
          {runs.data && runs.data.length > 0 && (
            <table className="data compact">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Template</th>
                  <th>Model</th>
                  <th className="right">Cases</th>
                  <th className="right">Composite</th>
                  <th className="right">Delta vs baseline</th>
                  <th>Result</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <Fragment key={r.id}>
                    <tr className={open === r.id ? "expanded" : ""}>
                      <td className="nowrap small">
                        {formatDate(r.created_at)} <span className="faint">{r.created_by}</span>
                      </td>
                      <td className="mono small">
                        {r.template_code} v{r.template_version}
                      </td>
                      <td className="small">{r.model}</td>
                      <td className="num">{r.cases}</td>
                      <td className="num">
                        <b>{pct(r.scores.composite)}</b>
                      </td>
                      <td className="num">
                        <Delta run={r} />
                      </td>
                      <td>
                        <EvalStatusPill status={r.status} />
                        {r.error && <div className="field-error small">{r.error}</div>}
                      </td>
                      <td>
                        <button className="small" onClick={() => setOpen(open === r.id ? null : r.id)}>
                          {open === r.id ? "Hide" : "Details"}
                        </button>
                      </td>
                    </tr>
                    {open === r.id && (
                      <tr className="expanded-row">
                        <td colSpan={8}>
                          <RunDetail run={r} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {building && (
        <Dialog
          title="Build eval set from approved copy"
          onClose={() => setBuilding(false)}
          footer={
            <>
              <button onClick={() => setBuilding(false)} disabled={build.isPending}>
                Cancel
              </button>
              <button className="primary" disabled={!buildAttr || build.isPending} onClick={() => build.mutate()}>
                {build.isPending ? "Building" : "Build"}
              </button>
            </>
          }
        >
          <p className="muted small">Approved values written by people (not AI, not imports) become reference texts. Existing cases are kept.</p>
          <label className="field">
            Attribute
            <select value={buildAttr} onChange={(e) => setBuildAttr(e.target.value)}>
              <option value="">Choose a text attribute</option>
              {textAttrs.map(([g, list]) => (
                <optgroup key={g} label={groupLabel(g)}>
                  {list.map((a) => (
                    <option key={a.code} value={a.code}>
                      {a.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="field">
            Limit
            <input type="number" min={1} max={50} value={buildLimit} onChange={(e) => setBuildLimit(Math.max(1, Math.min(50, Number(e.target.value) || 50)))} />
            <span className="help">At most 50 cases per build.</span>
          </label>
          {build.isError && <ErrorBox error={build.error} title="Build failed" />}
        </Dialog>
      )}
      {running && (
        <Dialog
          title="Run evaluation"
          onClose={() => setRunning(false)}
          footer={
            <>
              <button onClick={() => setRunning(false)} disabled={run.isPending}>
                Cancel
              </button>
              <button className="primary" disabled={!runTemplate || run.isPending} onClick={() => run.mutate()}>
                {run.isPending ? "Running" : "Run"}
              </button>
            </>
          }
        >
          <p className="muted small">The template runs on every eval case for its target attribute. The result gates activation of the template (AI-07).</p>
          <label className="field">
            Template
            <select value={runTemplate} onChange={(e) => setRunTemplate(e.target.value)}>
              <option value="">Choose a template</option>
              {(templates.data ?? []).map((t) => (
                <option key={t.code} value={t.code}>
                  {t.label} ({t.code} v{t.version}, {t.status})
                </option>
              ))}
            </select>
          </label>
          {run.isError && <ErrorBox error={run.error} title="Evaluation failed" />}
        </Dialog>
      )}
      {deleting && (
        <Confirm
          title="Delete this eval case?"
          message="The reference text is removed from the set. Past eval runs keep their scores."
          confirmLabel="Delete"
          busy={remove.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting)}
        />
      )}
    </div>
  );
}

function Delta({ run }: { run: EvalRun }) {
  if (run.delta === null || run.delta === undefined) return <span className="faint">no baseline</span>;
  const d = run.delta <= 1 && run.delta >= -1 ? run.delta * 100 : run.delta;
  const color = d < 0 ? "var(--red)" : d > 0 ? "var(--green)" : undefined;
  return (
    <span style={{ color }} title={run.baseline_composite !== null && run.baseline_composite !== undefined ? `Baseline ${pct(run.baseline_composite)}, threshold ${pct(run.threshold)}` : ""}>
      {d > 0 ? "+" : ""}
      {Math.round(d * 10) / 10} pts
    </span>
  );
}

function RunDetail({ run }: { run: EvalRun }) {
  return (
    <div className="stack">
      <div className="row gap16" style={{ flexWrap: "wrap" }}>
        <span>
          Overlap <b>{pct(run.scores.overlap)}</b>
        </span>
        <span>
          Length ok <b>{pct(run.scores.length_ok)}</b>
        </span>
        <span>
          Grounded <b>{pct(run.scores.grounded)}</b>
        </span>
        <span>
          Voice ok <b>{pct(run.scores.voice_ok)}</b>
        </span>
        <span>
          Threshold <b>{pct(run.threshold)}</b>
        </span>
        {run.baseline_run_id && <span className="faint small mono">baseline {run.baseline_run_id}</span>}
        {run.mlflow_run_id && <span className="faint small mono">mlflow {run.mlflow_run_id}</span>}
        {run.finished_at && <span className="faint small">finished {formatDate(run.finished_at)}</span>}
      </div>
      {run.sample.length === 0 ? (
        <span className="faint small">No sample outputs recorded for this run.</span>
      ) : (
        <table className="data compact">
          <thead>
            <tr>
              <th>Product</th>
              <th>Reference</th>
              <th>Output</th>
              <th className="right">Overlap</th>
            </tr>
          </thead>
          <tbody>
            {run.sample.map((s, i) => (
              <tr key={`${s.entity_id}-${i}`}>
                <td>
                  <Link to={`/products/${encodeURIComponent(s.entity_id)}`}>{s.label || s.entity_id}</Link>
                </td>
                <td className="pre small" style={{ maxWidth: 360 }}>
                  {s.reference}
                </td>
                <td className="pre small" style={{ maxWidth: 360 }}>
                  {s.output}
                </td>
                <td className="num">
                  <Badge color={s.overlap >= 0.7 ? "green" : s.overlap >= 0.4 ? "amber" : "red"}>{pct(s.overlap)}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
