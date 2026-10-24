// DM-12: Carryover for style-colors. Lists sibling colors with approved value counts, lets the user choose
// attributes, and copies the sibling's approved values as drafts.

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { AttributeDefinition } from "../api/types";
import { Badge, Dialog, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { formatDate } from "../lib/format";

export function CarryoverDialog({ entityId, attributes, onClose, onDone }: { entityId: string; attributes: AttributeDefinition[]; onClose: () => void; onDone?: () => void }) {
  const toast = useToast();
  const info = useQuery({ queryKey: ["product", entityId, "carryover"], queryFn: () => api.carryover.info(entityId) });
  const [from, setFrom] = useState("");
  const [all, setAll] = useState(true);
  const [codes, setCodes] = useState<string[]>([]);
  const [result, setResult] = useState<number | null>(null);

  // Only style-color owned attributes can be carried over (strict ownership, DM-01).
  const candidates = useMemo(() => attributes.filter((a) => a.level === "style_color" && a.source_of_truth !== "erp" && a.status !== "deprecated").sort((a, b) => a.label.localeCompare(b.label)), [attributes]);
  const run = useMutation({
    mutationFn: (fromId: string) => api.carryover.run(entityId, fromId, all ? undefined : codes),
    onSuccess: (r) => {
      setResult(r.drafts);
      toast(`${r.drafts} draft${r.drafts === 1 ? "" : "s"} created, review them in Approvals.`, "ok");
      onDone?.();
    },
  });
  const effectiveFrom = from || info.data?.siblings[0]?.entity_id || "";
  const valid = !!effectiveFrom && (all || codes.length > 0);

  return (
    <Dialog
      title="Carry over from a sibling color"
      onClose={onClose}
      footer={
        result !== null ? (
          <>
            <Link to="/approvals" className="btn">
              Open Approvals
            </Link>
            <button className="primary" onClick={onClose}>
              Close
            </button>
          </>
        ) : (
          <>
            <button onClick={onClose}>Cancel</button>
            <button className="primary" disabled={!valid || run.isPending} onClick={() => run.mutate(effectiveFrom)}>
              {run.isPending ? "Copying" : "Create drafts"}
            </button>
          </>
        )
      }
    >
      {result !== null ? (
        <div className="banner ok">
          {result} draft{result === 1 ? "" : "s"} created, review them in Approvals.
        </div>
      ) : (
        <div className="stack gap16">
          <div className="muted small">Approved style-color values from the chosen sibling are copied here as drafts. Nothing is approved automatically.</div>
          {info.isLoading && <Spinner label="Loading sibling colors" />}
          {info.isError && <ErrorBox error={info.error} title="Could not load sibling colors" />}
          {info.data && info.data.siblings.length === 0 && <Empty title="No sibling colors">This style has no other colors with approved values.</Empty>}
          {info.data && info.data.siblings.length > 0 && (
            <table className="data compact">
              <thead>
                <tr>
                  <th />
                  <th>Color</th>
                  <th className="right">Approved values</th>
                  <th>Last approved</th>
                </tr>
              </thead>
              <tbody>
                {info.data.siblings.map((s) => (
                  <tr key={s.entity_id} className={`clickable${s.entity_id === effectiveFrom ? " selected" : ""}`} onClick={() => setFrom(s.entity_id)}>
                    <td>
                      <input type="radio" checked={s.entity_id === effectiveFrom} onChange={() => setFrom(s.entity_id)} />
                    </td>
                    <td>
                      {s.label} <span className="faint mono">{s.color_code}</span>
                    </td>
                    <td className="num">{s.approved_values}</td>
                    <td className="nowrap">{s.last_approved_at ? formatDate(s.last_approved_at, false) : <span className="faint">never</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {info.data && info.data.steps_skippable.length > 0 && (
            <div className="row">
              <span className="muted small">Workflow steps that can be skipped after carryover:</span>
              {info.data.steps_skippable.map((s) => (
                <Badge key={s} color="teal">
                  {s}
                </Badge>
              ))}
            </div>
          )}
          <div>
            <div className="row mb8">
              <label className="inline">
                <input type="radio" checked={all} onChange={() => setAll(true)} /> All approved style-color attributes
              </label>
              <label className="inline">
                <input type="radio" checked={!all} onChange={() => setAll(false)} /> Only these attributes
              </label>
            </div>
            {!all && (
              <div className="row">
                {candidates.map((a) => (
                  <label key={a.code} className="inline">
                    <input type="checkbox" checked={codes.includes(a.code)} onChange={() => setCodes((c) => (c.includes(a.code) ? c.filter((x) => x !== a.code) : [...c, a.code]))} />
                    {a.label}
                  </label>
                ))}
                {candidates.length === 0 && <span className="faint small">No style-color attributes in metadata.</span>}
              </div>
            )}
          </div>
          {run.isError && <ErrorBox error={run.error} title="Carryover failed" />}
        </div>
      )}
    </Dialog>
  );
}
