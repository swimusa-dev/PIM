// IMG-05, IMG-03, IMG-06, IMG-07: Image slots by shot type with thumbnails; confirmed links in sort order with
// up / down reordering (PUT order, the first is the main image), rule failure badges per channel, the
// "AI generated" toggle per asset and a Renditions expander with "Create for channel"; candidate images with
// tier and confidence badges, Confirm (into a slot), Reject and "Ask AI for candidates" (tier 3 on demand).

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useChannels } from "../api/hooks";
import type { ImageLink } from "../api/types";
import { Badge, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { AiCandidatesDialog, Thumb, TierBadge, useImageDecision } from "../pages/Images";
import { formatDate } from "../lib/format";

export function ImagesPanel({ entityId }: { entityId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const channels = useChannels();
  const q = useQuery({ queryKey: ["product", entityId, "images"], queryFn: () => api.products.images(entityId) });
  const { confirm, reject } = useImageDecision([["product", entityId], ["images"]]);
  const [slotChoice, setSlotChoice] = useState<Record<string, string>>({});
  const [asking, setAsking] = useState<ImageLink | null>(null);
  const [showRules, setShowRules] = useState(false);

  const confirmed = useMemo(() => {
    // The links array carries every confirmed link (two links can share a shot type, or have none); slots only
    // keep one per shot type, so ordering is derived from links and falls back to slots for older responses.
    const source = q.data?.links ?? (q.data?.slots ?? []).map((s) => s.link);
    const links = source.filter((l): l is ImageLink => !!l && l.status === "confirmed");
    return [...links].sort((a, b) => a.sort_order - b.sort_order);
  }, [q.data]);

  const reorder = useMutation({
    mutationFn: (ids: string[]) => api.images.setOrder(entityId, ids),
    onSuccess: () => {
      toast("Image order saved. The first image is the main image.", "ok");
      qc.invalidateQueries({ queryKey: ["product", entityId] });
    },
    onError: (e) => toast(`Could not save the order: ${(e as Error).message}`, "error"),
  });
  const setAi = useMutation({
    mutationFn: ({ assetId, value }: { assetId: string; value: boolean }) => api.images.updateAsset(assetId, { ai_generated_image: value }),
    onSuccess: (_r, v) => {
      toast(v.value ? "Asset flagged as AI generated." : "AI generated flag removed.", "ok");
      qc.invalidateQueries({ queryKey: ["product", entityId] });
      qc.invalidateQueries({ queryKey: ["images"] });
    },
    onError: (e) => toast(`Could not update the asset: ${(e as Error).message}`, "error"),
  });

  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= confirmed.length) return;
    const ids = confirmed.map((l) => l.id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    reorder.mutate(ids);
  };
  const channelLabel = (code: string) => channels.data?.find((c) => c.code === code)?.label ?? code;

  if (q.isLoading) return <Spinner label="Loading images" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load images" />;
  const { slots, candidates, rules } = q.data!;
  const shotTypes = slots.map((s) => s.shot_type);

  return (
    <div className="stack gap16">
      <div>
        <div className="row mb8" style={{ justifyContent: "space-between" }}>
          <h4 style={{ margin: 0 }}>Shot slots</h4>
          {rules && Object.keys(rules).length > 0 && (
            <button className="link small" onClick={() => setShowRules(!showRules)}>
              {showRules ? "Hide" : "Show"} technical rules per channel
            </button>
          )}
        </div>
        {showRules && rules && (
          <div className="panel mb8">
            <div className="panel-body">
              <dl className="kv">
                {Object.entries(rules).map(([ch, r]) => (
                  <RulesRow key={ch} label={channelLabel(ch)} rules={r} />
                ))}
              </dl>
            </div>
          </div>
        )}
        {slots.length === 0 ? (
          <Empty title="No shot types required">Shot requirements come from the channel requirement sets (IMG-02).</Empty>
        ) : (
          <div className="slots">
            {slots.map((s) => (
              <div key={s.shot_type} className={`slot${s.link ? " filled" : ""}`} title={`Required by ${s.required_by.join(", ") || "no channel"}`}>
                <Thumb url={s.link?.thumbnail_url} alt={s.shot_type} />
                <div style={{ marginTop: 4 }}>
                  <b>{s.shot_type}</b>
                </div>
                <div className="faint" style={{ fontSize: 11 }}>
                  {s.required_by.length ? s.required_by.join(", ") : "optional"}
                </div>
                {s.link ? (
                  <div className="row" style={{ justifyContent: "center", marginTop: 4 }}>
                    <TierBadge tier={s.link.tier} confidence={s.link.confidence} />
                    <button className="small danger" onClick={() => reject.mutate(s.link!.id)} disabled={reject.isPending} title="Unlink this image">
                      Remove
                    </button>
                  </div>
                ) : (
                  <Badge color="red">missing</Badge>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <h4 className="mb8">Confirmed images ({confirmed.length})</h4>
        {confirmed.length === 0 ? (
          <Empty title="No confirmed images">Confirm a candidate below to fill a slot. The first confirmed image becomes the main image.</Empty>
        ) : (
          <div className="ordered-list">
            {confirmed.map((l, i) => {
              const failures = Object.entries(l.rule_failures ?? {}).filter(([, v]) => v && v.length > 0);
              return (
                <div className="item image-item" key={l.id}>
                  <span className="idx">{i + 1}</span>
                  <div className="row" style={{ flexDirection: "column", gap: 2 }}>
                    <button className="icon small" aria-label="Move up" disabled={i === 0 || reorder.isPending} onClick={() => move(i, -1)}>
                      &#9650;
                    </button>
                    <button className="icon small" aria-label="Move down" disabled={i === confirmed.length - 1 || reorder.isPending} onClick={() => move(i, 1)}>
                      &#9660;
                    </button>
                  </div>
                  {l.thumbnail_url ? (
                    <img src={l.thumbnail_url} alt={l.filename} style={{ width: 48, height: 64, objectFit: "cover", borderRadius: 4 }} />
                  ) : (
                    <div style={{ width: 48, height: 64, background: "#eef0f3", borderRadius: 4 }} />
                  )}
                  <div className="stack grow" style={{ gap: 4, minWidth: 0 }}>
                    <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                      {i === 0 && <Badge color="teal">Main</Badge>}
                      <span className="mono small" style={{ overflow: "hidden", textOverflow: "ellipsis" }} title={l.filename}>
                        {l.filename}
                      </span>
                      {l.shot_type && <Badge>{l.shot_type}</Badge>}
                      {l.width && l.height && (
                        <span className="faint small">
                          {l.width}x{l.height}
                        </span>
                      )}
                      <TierBadge tier={l.tier} confidence={l.confidence} />
                      {l.ai_generated_image && <Badge color="purple">AI generated</Badge>}
                    </div>
                    <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
                      {failures.length === 0 ? (
                        <Badge color="green" title="Passes every channel's technical image rules">
                          rules ok
                        </Badge>
                      ) : (
                        failures.map(([ch, reasons]) => (
                          <span key={ch} className="badge red tip" data-tip={reasons.join("\n")}>
                            {channelLabel(ch)}: {reasons.length} rule{reasons.length === 1 ? "" : "s"} failing
                          </span>
                        ))
                      )}
                    </div>
                    <RenditionsExpander assetId={l.asset_id} entityId={entityId} />
                  </div>
                  <label className="inline small" title="Mark the asset as generated by AI (IMG-06); channels that forbid AI imagery skip it">
                    <input
                      type="checkbox"
                      checked={!!l.ai_generated_image}
                      disabled={setAi.isPending}
                      onChange={(e) => setAi.mutate({ assetId: l.asset_id, value: e.target.checked })}
                    />
                    AI generated
                  </label>
                  <button className="small danger" onClick={() => reject.mutate(l.id)} disabled={reject.isPending} title="Unlink this image">
                    Remove
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div>
        <h4 className="mb8">Candidates ({candidates.length})</h4>
        {candidates.length === 0 ? (
          <Empty title="No candidate images">Air images that match this product's identifiers will appear here for review.</Empty>
        ) : (
          <div className="cands">
            {candidates.map((c) => {
              const chosen = slotChoice[c.id] ?? c.shot_type ?? shotTypes[0] ?? "";
              return (
                <div key={c.id} className="cand">
                  <Thumb url={c.thumbnail_url} alt={c.filename} />
                  <div className="fn" title={c.filename}>
                    {c.filename}
                  </div>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <TierBadge tier={c.tier} confidence={c.confidence} />
                    {c.width && c.height && (
                      <span className="faint small">
                        {c.width}x{c.height}
                      </span>
                    )}
                  </div>
                  <select value={chosen} onChange={(e) => setSlotChoice((s) => ({ ...s, [c.id]: e.target.value }))} title="Slot to confirm into">
                    {shotTypes.length === 0 && <option value="">(no slot)</option>}
                    {shotTypes.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                  <div className="row">
                    <button
                      className="primary small"
                      disabled={confirm.isPending}
                      onClick={() => confirm.mutate({ id: c.id, shotType: chosen || undefined })}
                    >
                      Confirm
                    </button>
                    <button className="small danger" disabled={reject.isPending} onClick={() => reject.mutate(c.id)}>
                      Reject
                    </button>
                  </div>
                  <button className="link small" onClick={() => setAsking(c)} title="Tier 3: ask the AI matcher which products this asset belongs to">
                    Ask AI for candidates
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
      {asking && <AiCandidatesDialog assetId={asking.asset_id} filename={asking.filename} invalidate={[["product", entityId]]} onClose={() => setAsking(null)} />}
    </div>
  );
}

function RulesRow({ label, rules }: { label: string; rules: Record<string, unknown> }) {
  const text = Object.entries(rules)
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(", ");
  return (
    <>
      <dt>{label}</dt>
      <dd>{text || <span className="faint">no rules</span>}</dd>
    </>
  );
}

/** IMG-07: renditions per channel for one asset, created on demand through the Air CDN or the resize job. */
function RenditionsExpander({ assetId, entityId }: { assetId: string; entityId: string }) {
  const [open, setOpen] = useState(false);
  const channels = useChannels();
  const [channel, setChannel] = useState("");
  const qc = useQueryClient();
  const toast = useToast();
  const effective = channel || channels.data?.find((c) => c.enabled)?.code || "";
  const q = useQuery({
    queryKey: ["images", "renditions", assetId, effective],
    queryFn: () => api.images.renditions(assetId, effective || undefined),
    enabled: open,
  });
  const create = useMutation({
    mutationFn: () => api.images.refreshRenditions(effective, [entityId]),
    onSuccess: (r) => {
      toast(`Renditions: ${r.created} created, ${r.queued} queued for the resize job.`, "ok");
      qc.invalidateQueries({ queryKey: ["images", "renditions", assetId] });
    },
    onError: (e) => toast(`Could not create renditions: ${(e as Error).message}`, "error"),
  });
  return (
    <div className="renditions">
      <button className="link small" onClick={() => setOpen(!open)}>
        {open ? "Hide renditions" : "Renditions"}
      </button>
      {open && (
        <div className="stack" style={{ gap: 6, marginTop: 4 }}>
          <div className="row">
            <select value={effective} onChange={(e) => setChannel(e.target.value)}>
              {(channels.data ?? []).map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </select>
            <button className="small" disabled={!effective || create.isPending} onClick={() => create.mutate()} title="Create renditions for this product using the channel's image profile">
              {create.isPending ? "Creating" : "Create for channel"}
            </button>
          </div>
          {q.isLoading && <Spinner label="Loading renditions" />}
          {q.isError && <ErrorBox error={q.error} title="Could not load renditions" />}
          {q.data && q.data.length === 0 && <span className="faint small">No renditions for this channel yet.</span>}
          {q.data && q.data.length > 0 && (
            <table className="data compact">
              <thead>
                <tr>
                  <th>URL</th>
                  <th>Size</th>
                  <th>Format</th>
                  <th>Source</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {q.data.map((r, i) => (
                  <tr key={`${r.url}-${i}`}>
                    <td>
                      <a href={r.url} target="_blank" rel="noreferrer" className="mono small" title={r.url}>
                        {r.url.length > 50 ? `${r.url.slice(0, 50)}...` : r.url}
                      </a>
                    </td>
                    <td className="nowrap">{r.width && r.height ? `${r.width}x${r.height}` : <span className="faint">n/a</span>}</td>
                    <td>{r.format}</td>
                    <td>
                      <Badge color={r.source === "air_cdn" ? "blue" : "amber"}>{r.source === "air_cdn" ? "Air CDN" : "resize job"}</Badge>
                    </td>
                    <td className="nowrap small">{formatDate(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
