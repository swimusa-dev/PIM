// D-15: which products a channel admits. EligibilityDialog edits a channel's rules with a live impact preview, and
// RecomputeButton applies a change to the products already loaded (a job when large).

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Channel, ChannelEligibility, EligibilityImpact } from "../api/types";
import { Dialog, ErrorBox, Spinner, useToast } from "../components/Common";

const n = (v: number) => v.toLocaleString();

export function RecomputeButton({ primary, onDone }: { primary?: boolean; onDone?: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const run = useMutation({
    mutationFn: () => api.metadata.recomputeEligibility(),
    onSuccess: (r) => {
      toast(
        r.status === "started"
          ? "Started as a background job. Readiness updates when it finishes (a few minutes)."
          : `Applied: ${n(r.scopes_changed)} brand scope changes, ${n(r.style_colors_recomputed)} style-colors recomputed.`,
        "ok",
      );
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
      qc.invalidateQueries({ queryKey: ["product"], refetchType: "none" });
      onDone?.();
    },
    onError: (e) => toast(`Could not apply: ${(e as Error).message}`, "error"),
  });
  return (
    <button
      className={primary ? "primary small" : "small"}
      disabled={run.isPending}
      onClick={() => run.mutate()}
      title="Re-derive every product's brand scopes and recompute channel readiness for the products already loaded"
    >
      {run.isPending ? "Applying" : "Apply to loaded products"}
    </button>
  );
}

function toggle(list: string[] | undefined, value: string): string[] {
  const l = list ?? [];
  return l.includes(value) ? l.filter((x) => x !== value) : [...l, value];
}

export function EligibilityDialog({ channel, onClose, onSaved }: { channel: Channel; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const options = useQuery({ queryKey: ["metadata", "eligibility-options"], queryFn: api.metadata.eligibilityOptions });
  const [e, setE] = useState<ChannelEligibility>(() => ({ ...(channel.eligibility ?? {}) }));
  const [impact, setImpact] = useState<EligibilityImpact | null>(null);
  const openToAll = !e.brand_scopes || e.brand_scopes.length === 0;
  const change = (next: ChannelEligibility) => {
    setE(next);
    setImpact(null); // a preview is only valid for the rules it was computed from
  };

  const preview = useMutation({ mutationFn: () => api.metadata.previewEligibility(channel.code, e), onSuccess: setImpact });
  const save = useMutation({
    mutationFn: () => api.metadata.saveEligibility(channel.code, e),
    onSuccess: () => {
      toast(`Saved ${channel.label}. Apply it to the loaded products to update readiness.`, "ok");
      qc.invalidateQueries({ queryKey: ["metadata"] });
      onSaved();
    },
  });

  const o = options.data;
  const noScopeChosen = !openToAll && (e.brand_scopes ?? []).length === 0;
  return (
    <Dialog
      title={`Eligibility for ${channel.label}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button onClick={onClose} disabled={save.isPending}>
            Cancel
          </button>
          <button onClick={() => preview.mutate()} disabled={preview.isPending || !o}>
            {preview.isPending ? "Calculating" : "Preview impact"}
          </button>
          <button className="primary" onClick={() => save.mutate()} disabled={save.isPending || !o || noScopeChosen}>
            {save.isPending ? "Saving" : "Save"}
          </button>
        </>
      }
    >
      {options.isLoading && <Spinner label="Loading options" />}
      {options.isError && <ErrorBox error={options.error} title="Could not load eligibility options" />}
      {o && (
        <div className="stack">
          <p className="muted small">
            A style-color can go to this channel only when it passes every rule below. Changes apply to the products already loaded after you
            use Apply to loaded products.
          </p>

          <fieldset className="stack">
            <legend>Brands</legend>
            <label className="inline">
              <input
                type="radio"
                name="brands"
                checked={openToAll}
                onChange={() => change({ ...e, brand_scopes: [] })}
              />{" "}
              Every brand
            </label>
            <label className="inline">
              <input
                type="radio"
                name="brands"
                checked={!openToAll}
                onChange={() => change({ ...e, brand_scopes: o.brand_scopes.filter((s) => s.enabled).slice(0, 1).map((s) => s.code) })}
              />{" "}
              Only these brand scopes (a scope is a rule over division, brand and more, edited in the Brand scopes tab)
            </label>
            {!openToAll && (
              <div className="chips" style={{ marginLeft: 24 }}>
                {o.brand_scopes.map((s) => (
                  <label key={s.code} className="inline" title={s.enabled ? undefined : "Disabled scopes match nothing"}>
                    <input
                      type="checkbox"
                      checked={(e.brand_scopes ?? []).includes(s.code)}
                      onChange={() => change({ ...e, brand_scopes: toggle(e.brand_scopes, s.code) })}
                    />{" "}
                    {s.label}
                    {!s.enabled && <span className="faint"> (disabled)</span>}
                  </label>
                ))}
              </div>
            )}
            {noScopeChosen && <span className="field-error">Choose at least one brand scope, or pick Every brand.</span>}
          </fieldset>

          <fieldset className="stack">
            <legend>Never send these brand classifications</legend>
            <div className="chips">
              {o.classifications.map((c) => (
                <label key={c.code} className="inline">
                  <input
                    type="checkbox"
                    checked={(e.exclude_classifications ?? []).includes(c.code)}
                    onChange={() => change({ ...e, exclude_classifications: toggle(e.exclude_classifications, c.code) })}
                  />{" "}
                  {c.label}
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="stack">
            <legend>Never send products with this lifecycle status</legend>
            <div className="chips">
              {o.lifecycle.map((l) => (
                <label key={l} className="inline">
                  <input
                    type="checkbox"
                    checked={(e.exclude_lifecycle ?? []).includes(l)}
                    onChange={() => change({ ...e, exclude_lifecycle: toggle(e.exclude_lifecycle, l) })}
                  />{" "}
                  {l}
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="stack">
            <legend>Never send these product types</legend>
            <div className="chips">
              {o.entity_types.map((t) => (
                <label key={t} className="inline">
                  <input
                    type="checkbox"
                    checked={(e.exclude_entity_types ?? []).includes(t)}
                    onChange={() => change({ ...e, exclude_entity_types: toggle(e.exclude_entity_types, t) })}
                  />{" "}
                  {t === "prepack" ? "prepack (a pack, not a single item)" : t}
                </label>
              ))}
            </div>
          </fieldset>

          {e.allow_classifications_for_subdivision && Object.keys(e.allow_classifications_for_subdivision).length > 0 && (
            <p className="muted small">
              This channel also has retailer exceptions (a classification allowed only for matching sub-divisions):{" "}
              <span className="mono">{JSON.stringify(e.allow_classifications_for_subdivision)}</span>. They are kept as they are.
            </p>
          )}

          {preview.isError && <ErrorBox error={preview.error} title="Could not calculate the impact" />}
          {impact && <ImpactSummary impact={impact} />}
          {save.isError && <ErrorBox error={save.error} title="Save failed" />}
        </div>
      )}
    </Dialog>
  );
}

function ImpactSummary({ impact }: { impact: EligibilityImpact }) {
  return (
    <div className="panel">
      <div className="panel-body stack">
        <div>
          <strong>
            {n(impact.eligible_after)} of {n(impact.total)} style-colors would be eligible
          </strong>{" "}
          <span className="muted">(now {n(impact.eligible_now)})</span>
        </div>
        <div className="muted small">
          {n(impact.newly_eligible)} become eligible, {n(impact.newly_ineligible)} stop being eligible. This uses the brand scopes stored on the
          products now.
        </div>
        {impact.ineligible_reasons.length > 0 && (
          <div className="muted small">Why products are ineligible after the change (a product can have more than one reason):</div>
        )}
        {impact.ineligible_reasons.length > 0 && (
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {impact.ineligible_reasons.map((r) => (
              <li key={r.reason}>
                {r.reason}: {n(r.count)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
