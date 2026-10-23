// DM-05, DM-01, DM-06, DM-11, IMG-05, GOV-02, EXP-03: Product detail page. Header with identifiers,
// hierarchy tree, completeness per channel with "show only missing required", attribute groups,
// channel override compare, images panel, history tab.

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useChannels, useOptionLists } from "../api/hooks";
import type { OptionList } from "../api/types";
import { Badge, ErrorBox, LifecycleBadge, PercentPill, ReadinessPill, Spinner, Tabs } from "../components/Common";
import { TreePanel } from "../detail/TreePanel";
import { AttributeForm } from "../detail/AttributeForm";
import { ImagesPanel } from "../detail/ImagesPanel";
import { HistoryTab } from "../detail/HistoryTab";
import { LEVEL_LABEL } from "../lib/format";

type Tab = "attributes" | "images" | "history";

export function ProductDetailPage() {
  const { id = "" } = useParams();
  const channels = useChannels();
  const optionLists = useOptionLists();
  const [tab, setTab] = useState<Tab>("attributes");
  const [missingChannel, setMissingChannel] = useState("");
  const [onlyMissing, setOnlyMissing] = useState(false);
  const [compareChannel, setCompareChannel] = useState("");

  const detail = useQuery({ queryKey: ["product", id, "detail", null], queryFn: () => api.products.detail(id) });
  const channelDetail = useQuery({
    queryKey: ["product", id, "detail", compareChannel],
    queryFn: () => api.products.detail(id, compareChannel),
    enabled: !!compareChannel,
  });
  const tree = useQuery({ queryKey: ["product", id, "tree"], queryFn: () => api.products.tree(id) });

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
        <h1 className="row">
          {entity.label}
          <Badge color="teal">{LEVEL_LABEL[entity.level]}</Badge>
          <LifecycleBadge status={entity.lifecycle_status} />
          {entity.entity_type === "prepack" && <Badge>prepack</Badge>}
        </h1>
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
        </div>

        <div className="detail-right stack">
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
                    {!r.eligible && <div className="muted small">Not eligible for this channel (EXP-12).</div>}
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
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
