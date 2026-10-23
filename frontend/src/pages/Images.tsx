// IMG-05: Image review queues. Tabs for candidates awaiting review, style-colors missing required shots
// for a channel, and unparsed filenames. Confirm / Reject act on /api/images/links/{id}.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useChannels } from "../api/hooks";
import { Badge, Empty, ErrorBox, Spinner, Tabs, useToast } from "../components/Common";
import type { ImageQueueCandidate, ImageQueueKind, ImageQueueMissing, ImageQueueUnparsed } from "../api/types";

export function ImagesPage() {
  const [kind, setKind] = useState<ImageQueueKind>("candidates");
  const channels = useChannels();
  const [channel, setChannel] = useState("");
  const effectiveChannel = channel || channels.data?.find((c) => c.enabled)?.code || "";

  const q = useQuery({
    queryKey: ["images", "queue", kind, kind === "missing" ? effectiveChannel : ""],
    queryFn: () => api.images.queue(kind, kind === "missing" ? effectiveChannel || undefined : undefined),
    enabled: kind !== "missing" || !!effectiveChannel || channels.isSuccess,
  });

  return (
    <div>
      <div className="page-header">
        <h1>Images</h1>
        {kind === "missing" && (
          <label className="inline">
            Channel
            <select value={effectiveChannel} onChange={(e) => setChannel(e.target.value)}>
              {(channels.data ?? []).map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <Tabs
        value={kind}
        onChange={setKind}
        tabs={[
          { key: "candidates", label: "Candidates awaiting review" },
          { key: "missing", label: "Missing required shots" },
          { key: "unparsed", label: "Unparsed filenames" },
        ]}
      />
      {q.isLoading && <Spinner label="Loading queue" />}
      {q.isError && <ErrorBox error={q.error} title="Could not load the image queue" />}
      {q.data && kind === "candidates" && <CandidatesQueue rows={q.data.rows as ImageQueueCandidate[]} />}
      {q.data && kind === "missing" && <MissingQueue rows={q.data.rows as ImageQueueMissing[]} channel={effectiveChannel} />}
      {q.data && kind === "unparsed" && <UnparsedQueue rows={q.data.rows as ImageQueueUnparsed[]} />}
    </div>
  );
}

export function TierBadge({ tier, confidence }: { tier: number; confidence: number }) {
  const color = tier === 1 ? "green" : tier === 2 ? "blue" : "amber";
  const tierText = tier === 1 ? "Tier 1 deterministic" : tier === 2 ? "Tier 2 parsed" : "Tier 3 similarity";
  return (
    <span className="row" style={{ gap: 4 }}>
      <Badge color={color} title={tierText}>
        T{tier}
      </Badge>
      <Badge title="Match confidence">{Math.round(confidence * (confidence <= 1 ? 100 : 1))}%</Badge>
    </span>
  );
}

export function Thumb({ url, alt }: { url?: string; alt: string }) {
  return url ? (
    <img className="thumb" src={url} alt={alt} loading="lazy" />
  ) : (
    <div className="thumb placeholder" aria-label="No thumbnail">
      No preview
    </div>
  );
}

export function useImageDecision(invalidate: unknown[][] = [["images"]]) {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useMutation({
    mutationFn: ({ id, shotType }: { id: string; shotType?: string }) => api.images.confirm(id, shotType),
    onSuccess: () => {
      toast("Image confirmed", "ok");
      invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k }));
    },
    onError: (e) => toast(`Confirm failed: ${(e as Error).message}`, "error"),
  });
  const reject = useMutation({
    mutationFn: (id: string) => api.images.reject(id),
    onSuccess: () => {
      toast("Image rejected", "ok");
      invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k }));
    },
    onError: (e) => toast(`Reject failed: ${(e as Error).message}`, "error"),
  });
  return { confirm, reject };
}

function CandidatesQueue({ rows }: { rows: ImageQueueCandidate[] }) {
  const { confirm, reject } = useImageDecision([["images"], ["products"]]);
  if (rows.length === 0) {
    return (
      <Empty title="No candidates are waiting for review">
        Tier 2 and tier 3 image matches from Air appear here. Tier 1 matches are confirmed automatically.
      </Empty>
    );
  }
  return (
    <div className="cands">
      {rows.map((c) => (
        <div className="cand" key={c.id}>
          <Thumb url={c.thumbnail_url} alt={c.filename} />
          <div className="fn" title={c.filename}>
            {c.filename}
          </div>
          <div className="small">
            Proposed:{" "}
            <Link to={`/products/${encodeURIComponent(c.proposed_entity_id ?? c.entity_id)}`}>
              {c.proposed_label ?? c.entity_id}
            </Link>
            {c.shot_type && (
              <>
                {" "}
                as <b>{c.shot_type}</b>
              </>
            )}
          </div>
          <TierBadge tier={c.tier} confidence={c.confidence} />
          <div className="row">
            <button
              className="primary small"
              disabled={confirm.isPending}
              onClick={() => confirm.mutate({ id: c.id, shotType: c.shot_type ?? undefined })}
            >
              Confirm
            </button>
            <button className="small danger" disabled={reject.isPending} onClick={() => reject.mutate(c.id)}>
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function MissingQueue({ rows, channel }: { rows: ImageQueueMissing[]; channel: string }) {
  if (rows.length === 0) {
    return (
      <Empty title={`Every eligible style-color has its required shots for ${channel || "this channel"}`}>
        Required shot types come from the channel's requirement set (IMG-02).
      </Empty>
    );
  }
  return (
    <div className="panel">
      <table className="data">
        <thead>
          <tr>
            <th>Style-color</th>
            <th>Style</th>
            <th>Color</th>
            <th>Missing shots</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.entity_id}>
              <td>
                <Link to={`/products/${encodeURIComponent(r.entity_id)}`}>{r.label}</Link>
              </td>
              <td className="mono">{r.style_number}</td>
              <td className="mono">{r.color_code ?? ""}</td>
              <td>
                <div className="chips">
                  {r.missing_shots.map((s) => (
                    <span key={s} className="badge red">
                      {s}
                    </span>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UnparsedQueue({ rows }: { rows: ImageQueueUnparsed[] }) {
  if (rows.length === 0) {
    return (
      <Empty title="Every Air filename was parsed">
        Files whose name does not contain a recognizable style number, color code or shot type will appear here.
      </Empty>
    );
  }
  return (
    <div className="panel">
      <table className="data">
        <thead>
          <tr>
            <th style={{ width: 70 }}>Preview</th>
            <th>Filename</th>
            <th>Air asset</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.asset_id}>
              <td>
                {r.thumbnail_url ? (
                  <img src={r.thumbnail_url} alt={r.filename} style={{ width: 48, height: 64, objectFit: "cover", borderRadius: 4 }} />
                ) : (
                  <span className="faint">none</span>
                )}
              </td>
              <td className="mono">{r.filename}</td>
              <td className="mono faint">{r.asset_id}</td>
              <td>{r.reason ?? "No style number, color code or shot type recognized in the filename"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
