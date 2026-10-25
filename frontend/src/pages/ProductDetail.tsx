// DM-05, DM-01, DM-06, DM-07, DM-09, DM-11, DM-12, DM-13, IMG-05, GOV-02, GOV-03, EXP-03, EXP-12, AI-03, AI-05, AI-06:
// Product detail page. Header with identifiers, hierarchy tree, completeness per channel with "show only missing
// required", attribute groups, channel override compare, images panel, history tab, comments tab, Relationships tab
// (Phase 6), Ask AI tab (hidden without run_ai), workflow panel, carryover, compare link, eligibility reasons and
// overrides per channel, readiness warnings, and the quality score checks per channel.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, relationshipApi } from "../api/client";
import { canRunAi, useChannels, useMe, useOptionLists } from "../api/hooks";
import type { OptionList } from "../api/types";
import { Badge, ErrorBox, LifecycleBadge, PercentPill, ReadinessPill, Spinner, Tabs } from "../components/Common";
import { TreePanel } from "../detail/TreePanel";
import { AttributeForm } from "../detail/AttributeForm";
import { ImagesPanel } from "../detail/ImagesPanel";
import { HistoryTab } from "../detail/HistoryTab";
import { CommentsTab } from "../detail/CommentsTab";
import { RelationshipsTab } from "../detail/RelationshipsTab";
import { WorkflowPanel } from "../detail/WorkflowPanel";
import { CarryoverDialog } from "../detail/CarryoverDialog";
import { EligibilityPanel } from "../detail/EligibilityPanel";
import { AskAiPanel } from "../detail/AskAiPanel";
import { QualityPanel } from "../detail/QualityPanel";
import { LEVEL_LABEL } from "../lib/format";

type Tab = "attributes" | "images" | "history" | "comments" | "relationships" | "ai";

export function ProductDetailPage() {
  const { id = "" } = useParams();
  const [searchParams] = useSearchParams();
  const channels = useChannels();
  const optionLists = useOptionLists();
  const me = useMe();
  const [tab, setTab] = useState<Tab>("attributes");
  const [focusAttr, setFocusAttr] = useState<string | null>(searchParams.get("attr"));
  const [missingChannel, setMissingChannel] = useState("");
  const [onlyMissing, setOnlyMissing] = useState(false);
  const [compareChannel, setCompareChannel] = useState("");
  const [showCarryover, setShowCarryover] = useState(false);

  const detail = useQuery({ queryKey: ["product", id, "detail", null], queryFn: () => api.products.detail(id) });
  const channelDetail = useQuery({
    queryKey: ["product", id, "detail", compareChannel],
    queryFn: () => api.products.detail(id, compareChannel),
    enabled: !!compareChannel,
  });
  const tree = useQuery({ queryKey: ["product", id, "tree"], queryFn: () => api.products.tree(id) });
  // DM-13: shared with the Relationships tab (same key) so the tab label carries the count.
  const relationships = useQuery({ queryKey: ["product", id, "relationships"], queryFn: () => relationshipApi.list(id) });

  const listByCode = useMemo(() => {
    const m: Record<string, OptionList> = {};
    for (const l of optionLists.data ?? []) m[l.code] = l;
    return m;
  }, [optionLists.data]);

  const entity = detail.data?.entity;
  const channelCodes = useMemo(() => {
    const fromEntity = Object.keys(entity?.completeness ?? {});
    const fromMeta = (channels.data ?? []).map((c) => c.code);
    return Array.from(new Set([...fromMeta, ...fromEntity]));
  }, [entity, channels.data]);
  const channelLabel = (code: string) => channels.data?.find((c) => c.code === code)?.label ?? code;
  const effectiveMissingChannel = missingChannel || channelCodes[0] || "";

  const missingSet = useMemo(() => {
    if (!onlyMissing || !entity || !effectiveMissingChannel) return null;
    const r = entity.readiness[effectiveMissingChannel];
    return new Set([...(r?.missing_attributes ?? []), ...(r?.invalid ?? [])]);
  }, [onlyMissing, entity, effectiveMissingChannel]);

  const allAttributes = useMemo(() => (detail.data?.groups ?? []).flatMap((g) => g.attributes), [detail.data]);
  const hasScopable = allAttributes.some((a) => a.channel_scopable);
  const showAi = canRunAi(me.data);

  // AI-06: NEEDS_INPUT chips (and ?attr= links from the AI pages) switch to the form and scroll to the attribute row.
  const goToAttribute = useCallback((code: string) => {
    setTab("attributes");
    setOnlyMissing(false);
    setFocusAttr(code);
  }, []);
  useEffect(() => {
    if (!focusAttr || tab !== "attributes" || !detail.data) return;
    const el = document.getElementById(`attr-${focusAttr}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("flash");
      window.setTimeout(() => el.classList.remove("flash"), 2000);
    }
    setFocusAttr(null);
  }, [focusAttr, tab, detail.data]);

  if (detail.isLoading) return <Spinner label="Loading product" />;
  if (detail.isError) return <ErrorBox error={detail.error} title="Could not load the product" />;
  if (!entity) return null;

  return (
    <div>
      <div className="detail-header">
        <div className="muted small">
          <Link to="/products">Products</Link>
          {detail.data!.ancestors.map((a) => (
            <span key={a.entity_id}>
              {" / "}
              <Link to={`/products/${encodeURIComponent(a.entity_id)}`}>{a.label}</Link>
            </span>
          ))}
        </div>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h1 className="row">
            {entity.label}
            <Badge color="teal">{LEVEL_LABEL[entity.level]}</Badge>
            <LifecycleBadge status={entity.lifecycle_status} />
            {entity.entity_type === "prepack" && <Badge>prepack</Badge>}
          </h1>
          <div className="row">
            <Link to={`/compare?a=${encodeURIComponent(entity.entity_id)}`} className="btn small">
              Compare with...
            </Link>
            {entity.level === "style_color" && (
              <button className="small" onClick={() => setShowCarryover(true)} title="Copy a sibling color's approved values here as drafts (DM-12)">
                Carryover
              </button>
            )}
          </div>
        </div>
        <div className="ids">
          <span>
            Style <b className="mono">{entity.style_number}</b>
          </span>
          {entity.color_code && (
            <span>
              Color <b className="mono">{entity.color_code}</b>
            </span>
          )}
          {entity.size && (
            <span>
              Size <b>{entity.size}</b>
            </span>
          )}
          {entity.sku && (
            <span>
              SKU <b className="mono">{entity.sku}</b>
            </span>
          )}
          {entity.upc && (
            <span>
              UPC <b className="mono">{entity.upc}</b>
            </span>
          )}
          <span>
            Family <b>{entity.family_code ?? "none"}</b>
          </span>
          <span className="row" style={{ gap: 4 }}>
            Brand scopes
            {entity.brand_scopes.length ? entity.brand_scopes.map((b) => <Badge key={b}>{b}</Badge>) : <b>none</b>}
          </span>
        </div>
      </div>

      <div className="panel mb16">
        <div className="panel-body row" style={{ justifyContent: "space-between" }}>
          <div className="row gap16">
            {channelCodes.length === 0 && <span className="muted">No channels configured.</span>}
            {channelCodes.map((c) => (
              <span key={c} className="row" style={{ gap: 6 }}>
                <span className="muted">{channelLabel(c)}</span>
                <PercentPill value={entity.completeness[c]} />
                <ReadinessPill readiness={entity.readiness[c]} />
              </span>
            ))}
          </div>
          <div className="row">
            <label className="inline">
              <input type="checkbox" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} />
              Show only missing required for
            </label>
            <select value={effectiveMissingChannel} onChange={(e) => setMissingChannel(e.target.value)} disabled={channelCodes.length === 0}>
              {channelCodes.map((c) => (
                <option key={c} value={c}>
                  {channelLabel(c)}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="detail-layout">
        <div className="panel">
          <div className="panel-header">
            <h3>Hierarchy</h3>
          </div>
          <div className="panel-body" style={{ padding: 8, maxHeight: "70vh", overflow: "auto" }}>
            {tree.isLoading && <Spinner />}
            {tree.isError && <ErrorBox error={tree.error} title="Could not load the tree" />}
            {tree.data && <TreePanel tree={tree.data} currentId={entity.entity_id} />}
          </div>
        </div>

        <div>
          <Tabs<Tab>
            value={tab}
            onChange={setTab}
            tabs={[
              { key: "attributes", label: "Attributes" },
              { key: "images", label: "Images", count: detail.data!.images.length },
              { key: "history", label: "History", count: detail.data!.history_count },
              { key: "comments", label: "Comments" },
              { key: "relationships", label: "Relationships", count: relationships.data?.rows.length },
              ...(showAi ? [{ key: "ai" as Tab, label: "Ask AI" }] : []),
            ]}
          />
          {tab === "attributes" && (
            <>
              {hasScopable && (
                <div className="row mb8">
                  <span className="muted">Values:</span>
                  <select value={compareChannel} onChange={(e) => setCompareChannel(e.target.value)}>
                    <option value="">Global only</option>
                    {(channels.data ?? []).map((c) => (
                      <option key={c.code} value={c.code}>
                        Global and {c.label} override
                      </option>
                    ))}
                  </select>
                  {compareChannel && channelDetail.isLoading && <Spinner label="Loading channel values" />}
                  {compareChannel && channelDetail.isError && <span className="field-error">Could not load channel values</span>}
                </div>
              )}
              <AttributeForm
                entity={entity}
                channelEntity={compareChannel ? channelDetail.data?.entity : null}
                channelCode={compareChannel || null}
                groups={detail.data!.groups}
                optionLists={listByCode}
                onlyMissing={missingSet}
              />
            </>
          )}
          {tab === "images" && <ImagesPanel entityId={entity.entity_id} />}
          {tab === "history" && <HistoryTab entityId={entity.entity_id} attributes={allAttributes} optionLists={listByCode} />}
          {tab === "comments" && <CommentsTab entityId={entity.entity_id} attributes={allAttributes} />}
          {tab === "relationships" && <RelationshipsTab entityId={entity.entity_id} level={entity.level} />}
          {tab === "ai" && showAi && (
            <AskAiPanel entityId={entity.entity_id} attributes={allAttributes} optionLists={listByCode} onGoToAttribute={goToAttribute} />
          )}
        </div>

        <div className="detail-right stack">
          <WorkflowPanel entityId={entity.entity_id} />
          <div className="panel">
            <div className="panel-header">
              <h3>Children</h3>
              <span className="muted small">{detail.data!.children.length}</span>
            </div>
            <div className="panel-body flush" style={{ maxHeight: 300, overflow: "auto" }}>
              {detail.data!.children.length === 0 ? (
                <div className="empty">
                  {entity.level === "sku" ? "SKUs have no children." : "No child entities yet. The Style Master ingest creates them."}
                </div>
              ) : (
                <table className="data compact">
                  <tbody>
                    {detail.data!.children.map((c) => (
                      <tr key={c.entity_id}>
                        <td>
                          <Link to={`/products/${encodeURIComponent(c.entity_id)}`}>{c.label}</Link>
                        </td>
                        <td>
                          <LifecycleBadge status={c.lifecycle_status} />
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
              <h3>Readiness detail</h3>
            </div>
            <div className="panel-body stack">
              {channelCodes.map((c) => {
                const r = entity.readiness[c];
                if (!r) return null;
                return (
                  <div key={c}>
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <b>{channelLabel(c)}</b>
                      <ReadinessPill readiness={r} />
                    </div>
                    {!r.eligible && <div className="muted small">Not eligible for this channel; see Eligibility below (EXP-12).</div>}
                    {r.missing_attributes.length > 0 && (
                      <div className="small">
                        <span className="muted">Missing:</span> {r.missing_attributes.map((m) => allAttributes.find((a) => a.code === m)?.label ?? m).join(", ")}
                      </div>
                    )}
                    {r.missing_shots.length > 0 && (
                      <div className="small">
                        <span className="muted">Missing shots:</span> {r.missing_shots.join(", ")}
                      </div>
                    )}
                    {r.mapping_gaps.length > 0 && (
                      <div className="small">
                        <span className="muted">Mapping gaps:</span> {r.mapping_gaps.join(", ")}
                      </div>
                    )}
                    {r.invalid.length > 0 && (
                      <div className="small">
                        <span className="muted">Invalid after transform:</span> {r.invalid.join(", ")}
                      </div>
                    )}
                    {r.reasons.length > 0 && <div className="small muted">{r.reasons.join("; ")}</div>}
                    {(r.warnings ?? []).length > 0 && (
                      <ul className="reasons small" style={{ color: "var(--amber)" }} title="Warnings never block a publish">
                        {r.warnings!.map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })}
              <div style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                <div className="muted small mb8">Eligibility (EXP-12)</div>
                <EligibilityPanel entityId={entity.entity_id} channelLabel={channelLabel} />
              </div>
              <div style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                <div className="muted small mb8">Quality (GOV-03)</div>
                <QualityPanel entityId={entity.entity_id} channelLabel={channelLabel} />
              </div>
            </div>
          </div>
        </div>
      </div>
      {showCarryover && <CarryoverDialog entityId={entity.entity_id} attributes={allAttributes} onClose={() => setShowCarryover(false)} />}
    </div>
  );
}
