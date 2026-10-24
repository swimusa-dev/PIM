// IMG-05: Image slots by shot type with thumbnails, candidate images with tier and confidence badges,
// Confirm (into a slot) and Reject.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Badge, Empty, ErrorBox, Spinner } from "../components/Common";
import { Thumb, TierBadge, useImageDecision } from "../pages/Images";

export function ImagesPanel({ entityId }: { entityId: string }) {
  const q = useQuery({ queryKey: ["product", entityId, "images"], queryFn: () => api.products.images(entityId) });
  const { confirm, reject } = useImageDecision([["product", entityId], ["images"]]);
  const [slotChoice, setSlotChoice] = useState<Record<string, string>>({});

  if (q.isLoading) return <Spinner label="Loading images" />;
  if (q.isError) return <ErrorBox error={q.error} title="Could not load images" />;
  const { slots, candidates } = q.data!;
  const shotTypes = slots.map((s) => s.shot_type);

  return (
    <div className="stack gap16">
      <div>
        <h4 className="mb8">Shot slots</h4>
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
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
