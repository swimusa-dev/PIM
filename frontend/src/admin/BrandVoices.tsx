// AI-02: Brand voice editor (Admin > AI). One card per brand: tone, do rules, don't rules, blocked terms,
// trademark terms as key / value rows, punctuation rules and 5 to 10 example descriptions. PUT bumps the version.

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { aiApi } from "../api/client";
import { isAdmin, useBrandVoices, useMe } from "../api/hooks";
import type { BrandVoice } from "../api/types";
import { Badge, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { formatDate } from "../lib/format";

type Draft = Omit<BrandVoice, "version" | "updated_at" | "updated_by">;

const EMPTY: Omit<Draft, "brand_code" | "label"> = {
  tone: "",
  do_rules: [],
  dont_rules: [],
  blocked_terms: [],
  trademark_terms: {},
  punctuation_rules: [],
  examples: [],
};

const lines = (v: string[]) => v.join("\n");
const parseLines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

export function BrandVoicesTab() {
  const me = useMe();
  const voices = useBrandVoices();
  const admin = isAdmin(me.data);
  const [newCode, setNewCode] = useState("");
  const [creating, setCreating] = useState<string | null>(null);

  return (
    <div className="stack gap16">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="muted small">
          The brand voice is injected into every prompt for the brand. Blocked terms fail a check, trademark terms are rewritten to their
          approved form, and the examples anchor the tone. Saving creates a new version.
        </span>
        {admin && (
          <span className="row">
            <input value={newCode} placeholder="brand code, e.g. vitamin_a" onChange={(e) => setNewCode(e.target.value)} style={{ width: 200 }} />
            <button className="small" disabled={!newCode.trim()} onClick={() => { setCreating(newCode.trim()); setNewCode(""); }}>
              Add brand voice
            </button>
          </span>
        )}
      </div>
      {voices.isLoading && <Spinner label="Loading brand voices" />}
      {voices.isError && <ErrorBox error={voices.error} title="Could not load brand voices" />}
      {voices.data && voices.data.length === 0 && !creating && (
        <Empty title="No brand voice yet">Add one for each brand (Vitamin A first) so AI copy follows its tone and rules.</Empty>
      )}
      {creating && !voices.data?.some((v) => v.brand_code === creating) && (
        <VoiceCard
          key={`new-${creating}`}
          voice={{ brand_code: creating, label: creating, version: 0, updated_at: "", ...EMPTY }}
          editable={admin}
          isNew
          onDone={() => setCreating(null)}
        />
      )}
      {(voices.data ?? []).map((v) => (
        <VoiceCard key={`${v.brand_code}-${v.version}`} voice={v} editable={admin} />
      ))}
    </div>
  );
}

function VoiceCard({ voice, editable, isNew, onDone }: { voice: BrandVoice; editable: boolean; isNew?: boolean; onDone?: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [d, setD] = useState<Draft>({
    brand_code: voice.brand_code,
    label: voice.label,
    tone: voice.tone,
    do_rules: voice.do_rules,
    dont_rules: voice.dont_rules,
    blocked_terms: voice.blocked_terms,
    trademark_terms: voice.trademark_terms,
    punctuation_rules: voice.punctuation_rules,
    examples: voice.examples,
  });
  const [tm, setTm] = useState<{ k: string; v: string }[]>(Object.entries(voice.trademark_terms).map(([k, v]) => ({ k, v })));
  const [open, setOpen] = useState(!!isNew);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));

  const save = useMutation({
    mutationFn: () => {
      const trademark_terms: Record<string, string> = {};
      for (const r of tm) if (r.k.trim()) trademark_terms[r.k.trim()] = r.v.trim();
      return aiApi.saveBrandVoice(voice.brand_code, { ...d, trademark_terms, examples: d.examples.filter((e) => e.trim()) });
    },
    onSuccess: (v) => {
      toast(`Brand voice ${v.label} saved as version ${v.version}.`, "ok");
      qc.invalidateQueries({ queryKey: ["ai", "brand-voices"] });
      onDone?.();
    },
  });

  const exampleCount = d.examples.filter((e) => e.trim()).length;
  const exampleWarn = exampleCount < 5 ? `Add ${5 - exampleCount} more example${5 - exampleCount === 1 ? "" : "s"} (5 to 10 recommended).` : exampleCount > 10 ? "More than 10 examples; the prompt only uses the first 10." : "";

  return (
    <div className="panel">
      <div className="panel-header" style={{ cursor: "pointer" }} onClick={() => setOpen((o) => !o)}>
        <h3 className="row">
          {open ? "▾" : "▸"} {d.label || voice.brand_code} <span className="faint small mono">{voice.brand_code}</span>
          {isNew ? <Badge color="amber">new</Badge> : <Badge>v{voice.version}</Badge>}
        </h3>
        <span className="muted small">
          {voice.updated_at ? `Updated ${formatDate(voice.updated_at)}${voice.updated_by ? ` by ${voice.updated_by}` : ""}` : "Not saved yet"}
        </span>
      </div>
      {open && (
        <div className="panel-body stack">
          <div className="form-grid">
            <label className="field">
              Label
              <input value={d.label} disabled={!editable} onChange={(e) => set("label", e.target.value)} />
            </label>
            <label className="field">
              Tone
              <textarea value={d.tone} disabled={!editable} rows={3} onChange={(e) => set("tone", e.target.value)} placeholder="e.g. Warm, confident, sun-soaked; speaks to a woman who knows what she wants" />
            </label>
            <label className="field">
              Do rules (one per line)
              <textarea value={lines(d.do_rules)} disabled={!editable} rows={5} onChange={(e) => set("do_rules", parseLines(e.target.value))} />
            </label>
            <label className="field">
              Don't rules (one per line)
              <textarea value={lines(d.dont_rules)} disabled={!editable} rows={5} onChange={(e) => set("dont_rules", parseLines(e.target.value))} />
            </label>
            <label className="field">
              Blocked terms (one per line)
              <textarea value={lines(d.blocked_terms)} disabled={!editable} rows={4} onChange={(e) => set("blocked_terms", parseLines(e.target.value))} placeholder="Words the copy must never use" />
            </label>
            <label className="field">
              Punctuation rules (one per line)
              <textarea value={lines(d.punctuation_rules)} disabled={!editable} rows={4} onChange={(e) => set("punctuation_rules", parseLines(e.target.value))} placeholder="e.g. No em dashes; use a comma or a period" />
            </label>
          </div>

          <div>
            <div className="muted small mb8">Trademark terms (written form on the left, approved form on the right)</div>
            <div className="stack" style={{ gap: 4 }}>
              {tm.map((r, i) => (
                <div key={i} className="row">
                  <input value={r.k} disabled={!editable} placeholder="term" onChange={(e) => setTm((t) => t.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)))} />
                  <span className="faint">becomes</span>
                  <input value={r.v} disabled={!editable} placeholder="approved form" onChange={(e) => setTm((t) => t.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)))} />
                  {editable && (
                    <button className="icon small" onClick={() => setTm((t) => t.filter((_, j) => j !== i))} aria-label="Remove">
                      &times;
                    </button>
                  )}
                </div>
              ))}
              {editable && (
                <div>
                  <button className="small" onClick={() => setTm((t) => [...t, { k: "", v: "" }])}>
                    + Add term
                  </button>
                </div>
              )}
              {tm.length === 0 && <span className="faint small">None.</span>}
            </div>
          </div>

          <div>
            <div className="row mb8" style={{ justifyContent: "space-between" }}>
              <span className="muted small">Example descriptions ({exampleCount})</span>
              {exampleWarn && <span className={exampleCount < 5 ? "field-error small" : "muted small"}>{exampleWarn}</span>}
            </div>
            <div className="stack">
              {d.examples.map((ex, i) => (
                <div key={i} className="row" style={{ alignItems: "flex-start" }}>
                  <span className="faint small" style={{ width: 20, paddingTop: 6 }}>
                    {i + 1}
                  </span>
                  <textarea className="grow" value={ex} disabled={!editable} rows={3} onChange={(e) => set("examples", d.examples.map((x, j) => (j === i ? e.target.value : x)))} />
                  {editable && (
                    <button className="icon small" onClick={() => set("examples", d.examples.filter((_, j) => j !== i))} aria-label="Remove example">
                      &times;
                    </button>
                  )}
                </div>
              ))}
              {editable && d.examples.length < 10 && (
                <div>
                  <button className="small" onClick={() => set("examples", [...d.examples, ""])}>
                    + Add example
                  </button>
                </div>
              )}
            </div>
          </div>

          {save.isError && <ErrorBox error={save.error} title="Save failed" />}
          {editable && (
            <div className="row" style={{ justifyContent: "flex-end" }}>
              {onDone && (
                <button onClick={onDone} disabled={save.isPending}>
                  Discard
                </button>
              )}
              <button className="primary" disabled={save.isPending || !d.label.trim()} onClick={() => save.mutate()}>
                {save.isPending ? "Saving" : isNew ? "Create brand voice" : `Save as version ${voice.version + 1}`}
              </button>
            </div>
          )}
          {!editable && <div className="faint small">Read only: editing brand voices needs the admin_metadata permission.</div>}
        </div>
      )}
    </div>
  );
}
