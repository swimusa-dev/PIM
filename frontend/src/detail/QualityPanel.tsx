// GOV-03: Quality section of the product detail readiness panel. One block per QualityScore (overall plus each
// channel) with the grade pill, the score and the checks list (passed or failed with details).

import { useQuery } from "@tanstack/react-query";
import { qualityApi } from "../api/client";
import { ErrorBox, GradePill, Spinner } from "../components/Common";
import { formatDate } from "../lib/format";

export function QualityPanel({ entityId, channelLabel }: { entityId: string; channelLabel: (code: string) => string }) {
  const q = useQuery({ queryKey: ["product", entityId, "quality"], queryFn: () => qualityApi.product(entityId) });
  if (q.isLoading) return <Spinner label="Loading quality" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load the quality score" />;
  const scores = (q.data?.scores ?? []).slice().sort((a, b) => (a.channel_code === "" ? -1 : b.channel_code === "" ? 1 : a.channel_code.localeCompare(b.channel_code)));
  if (scores.length === 0) return <div className="faint small">No quality score yet. An administrator can run Recompute now under Admin, Quality.</div>;
  return (
    <div className="stack">
      {scores.map((s) => {
        const failed = s.checks.filter((c) => !c.passed);
        const passed = s.checks.filter((c) => c.passed);
        return (
          <details key={s.channel_code || "overall"} className="quality-block" open={s.channel_code === ""}>
            <summary className="row" style={{ justifyContent: "space-between" }}>
              <b>{s.channel_code ? channelLabel(s.channel_code) : "Overall"}</b>
              <span className="row" style={{ gap: 6 }}>
                <span className="muted small">{failed.length} of {s.checks.length} failed</span>
                <GradePill grade={s.grade} score={s.score} />
              </span>
            </summary>
            <ul className="checks">
              {failed.map((c) => (
                <li key={c.code} className="failed">
                  <span className="mark">x</span>
                  <span>
                    {c.label} <span className="faint small">weight {c.weight}</span>
                    {c.details.length > 0 && <div className="faint small pre">{c.details.join("\n")}</div>}
                  </span>
                </li>
              ))}
              {passed.map((c) => (
                <li key={c.code} className="passed">
                  <span className="mark">ok</span>
                  <span>
                    {c.label} <span className="faint small">weight {c.weight}</span>
                  </span>
                </li>
              ))}
            </ul>
            <div className="faint small">Computed {formatDate(s.computed_at)}</div>
          </details>
        );
      })}
    </div>
  );
}
