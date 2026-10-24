// DM-06: Compare two products side by side, highlight differences, copy values A to B or B to A
// per row or for the selected rows (POST copy-from).

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useChannels, useGroups, useOptionLists } from "../api/hooks";
import type { Level, OptionList, ProductRow } from "../api/types";
import { AiBadge, ApprovalBadge, Badge, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { cellValue, displayValue, LEVEL_LABEL } from "../lib/format";

function ProductSearch({ label, value, level, onPick }: { label: string; value: string; level: Level; onPick: (row: ProductRow) => void }) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const hostRef = useRef<HTMLDivElement>(null);
  const q = useQuery({
    queryKey: ["products", "search", level, text],
    queryFn: () => api.products.query({ level, page: 1, page_size: 10, sort: [], filters: [], search: text.trim(), columns: [] }),
    enabled: open && text.trim().length > 0,
  });
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (hostRef.current && !hostRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);
  return (
    <div className="popover-host" ref={hostRef} style={{ display: "block" }}>
      <label className="field">
        {label}
        <input
          value={open ? text : value || text}
          placeholder="Search style number, name, UPC"
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
          }}
        />
      </label>
      {open && text.trim() && (
        <div className="search-results">
          {q.isLoading && <div className="item faint">Searching</div>}
          {q.isError && <div className="item" style={{ color: "var(--red)" }}>Search failed</div>}
          {q.data && q.data.rows.length === 0 && <div className="item faint">No matches</div>}
          {q.data?.rows.map((r) => (
            <div
              key={r.entity_id}
              className="item"
              onClick={() => {
                onPick(r);
                setText("");
                setOpen(false);
              }}
            >
              {r.label} <span className="faint mono small">{r.entity_id}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ComparePage() {
  const [params, setParams] = useSearchParams();
  const a = params.get("a") ?? "";
  const b = params.get("b") ?? "";
  const channel = params.get("channel") ?? "";
  const [level, setLevel] = useState<Level>("style_color");
  const [aLabel, setALabel] = useState("");
  const [bLabel, setBLabel] = useState("");
  const [onlyDiff, setOnlyDiff] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const channels = useChannels();
  const groups = useGroups();
  const optionLists = useOptionLists();
  const qc = useQueryClient();
  const toast = useToast();

  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setParams(next, { replace: true });
  };

  const q = useQuery({ queryKey: ["products", "compare", a, b, channel], queryFn: () => api.compare.get(a, b, channel || undefined), enabled: !!a && !!b });
  const listByCode = useMemo(() => {
    const m: Record<string, OptionList> = {};
    for (const l of optionLists.data ?? []) m[l.code] = l;
    return m;
  }, [optionLists.data]);
  const groupLabel = (code: string) => groups.data?.find((g) => g.code === code)?.label ?? code;

  const copy = useMutation({
    mutationFn: ({ to, from, codes }: { to: string; from: string; codes: string[] }) => api.compare.copyFrom(to, from, codes, channel || null),
    onSuccess: (r) => {
      const approved = r.results.filter((x) => x.outcome === "approved").length;
      const draft = r.results.filter((x) => x.outcome === "draft").length;
      const rejected = r.results.filter((x) => x.outcome === "rejected");
      toast(`${approved} copied${draft ? `, ${draft} as drafts` : ""}${rejected.length ? `, ${rejected.length} rejected` : ""}.`, rejected.length ? "warn" : "ok");
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["products", "compare"] });
      qc.invalidateQueries({ queryKey: ["product"] });
    },
    onError: (e) => toast(`Copy failed: ${(e as Error).message}`, "error"),
  });

  const rows = useMemo(() => {
    if (!q.data) return [];
    const byGroup = new Map((groups.data ?? []).map((g) => [g.code, g.sort_order]));
    return q.data.attributes
      .slice()
      .sort((x, y) => (byGroup.get(x.group_code) ?? 999) - (byGroup.get(y.group_code) ?? 999) || x.sort_order - y.sort_order)
      .map((attr) => {
        const ca = q.data!.a.values[attr.code];
        const cb = q.data!.b.values[attr.code];
        const va = cellValue(ca);
        const vb = cellValue(cb);
        const differs = JSON.stringify(va ?? null) !== JSON.stringify(vb ?? null);
        return { attr, ca, cb, va, vb, differs };
      })
      .filter((r) => !onlyDiff || r.differs);
  }, [q.data, groups.data, onlyDiff]);
  const diffCount = useMemo(() => rows.filter((r) => r.differs).length, [rows]);

  const toggle = (code: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(code)) n.delete(code);
      else n.add(code);
      return n;
    });

  return (
    <div>
      <div className="page-header">
        <h1>Compare products</h1>
        <span className="muted small">Pick two products, spot the differences, copy values across.</span>
      </div>
      <div className="panel mb16">
        <div className="panel-body form-grid" style={{ alignItems: "end" }}>
          <label className="field">
            Search level
            <select value={level} onChange={(e) => setLevel(e.target.value as Level)}>
              {(["style", "style_color", "sku"] as Level[]).map((l) => (
                <option key={l} value={l}>
                  {LEVEL_LABEL[l]}
                </option>
              ))}
            </select>
          </label>
          <ProductSearch
            label="Product A"
            level={level}
            value={aLabel || q.data?.a.label || a}
            onPick={(r) => {
              setALabel(r.label);
              set({ a: r.entity_id });
            }}
          />
          <ProductSearch
            label="Product B"
            level={level}
            value={bLabel || q.data?.b.label || b}
            onPick={(r) => {
              setBLabel(r.label);
              set({ b: r.entity_id });
            }}
          />
          <label className="field">
            Channel (optional)
            <select value={channel} onChange={(e) => set({ channel: e.target.value })}>
              <option value="">Global values</option>
              {(channels.data ?? []).map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label} overrides
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={() => {
              set({ a: b, b: a });
              const t = aLabel;
              setALabel(bLabel);
              setBLabel(t);
            }}
            disabled={!a || !b}
          >
            Swap A and B
          </button>
        </div>
      </div>

      {(!a || !b) && <Empty title="Choose two products to compare">Use the search fields above, or open Compare from a product's detail header.</Empty>}
      {a && b && q.isLoading && <Spinner label="Comparing" />}
      {a && b && q.isError && <ErrorBox error={q.error} title="Could not compare" />}
      {q.data && (
        <div className="panel">
          <div className="panel-header">
            <div className="row">
              <label className="inline">
                <input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} />
                Only differences ({diffCount})
              </label>
              <span className="faint small">{selected.size} selected</span>
            </div>
            <div className="row">
              <button
                className="small"
                disabled={selected.size === 0 || copy.isPending}
                onClick={() => copy.mutate({ to: q.data.b.entity_id, from: q.data.a.entity_id, codes: Array.from(selected) })}
              >
                Copy A to B (selected)
              </button>
              <button
                className="small"
                disabled={selected.size === 0 || copy.isPending}
                onClick={() => copy.mutate({ to: q.data.a.entity_id, from: q.data.b.entity_id, codes: Array.from(selected) })}
              >
                Copy B to A (selected)
              </button>
              <button className="small link" onClick={() => setSelected(new Set(rows.filter((r) => r.differs).map((r) => r.attr.code)))}>
                Select all differences
              </button>
            </div>
          </div>
          <table className="data compare-table">
            <thead>
              <tr>
                <th />
                <th>Attribute</th>
                <th>
                  A: <Link to={`/products/${encodeURIComponent(q.data.a.entity_id)}`}>{q.data.a.label}</Link>
                </th>
                <th>
                  B: <Link to={`/products/${encodeURIComponent(q.data.b.entity_id)}`}>{q.data.b.label}</Link>
                </th>
                <th>Copy</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="empty">
                    {onlyDiff ? "No differences." : "No attributes to show."}
                  </td>
                </tr>
              )}
              {rows.map(({ attr, ca, cb, va, vb, differs }) => (
                <tr key={attr.code}>
                  <td>
                    <input type="checkbox" checked={selected.has(attr.code)} onChange={() => toggle(attr.code)} aria-label={`Select ${attr.label}`} />
                  </td>
                  <td>
                    <div>{attr.label}</div>
                    <div className="faint small">{groupLabel(attr.group_code)}</div>
                  </td>
                  <td className={differs ? "differs a" : ""}>
                    {ca?.not_applicable ? "N/A" : displayValue(va, attr, listByCode) || <span className="faint">empty</span>}
                    {ca?.ai_generated && <AiBadge />}
                    {ca && ca.approval_state !== "approved" && <ApprovalBadge state={ca.approval_state} />}
                    {ca?.read_only && <Badge title={ca.read_only_reason ?? "read only"}>locked</Badge>}
                  </td>
                  <td className={differs ? "differs" : ""}>
                    {cb?.not_applicable ? "N/A" : displayValue(vb, attr, listByCode) || <span className="faint">empty</span>}
                    {cb?.ai_generated && <AiBadge />}
                    {cb && cb.approval_state !== "approved" && <ApprovalBadge state={cb.approval_state} />}
                    {cb?.read_only && <Badge title={cb.read_only_reason ?? "read only"}>locked</Badge>}
                  </td>
                  <td className="nowrap">
                    <button
                      className="small"
                      title="Copy A to B"
                      disabled={copy.isPending || !differs || !!cb?.read_only}
                      onClick={() => copy.mutate({ to: q.data.b.entity_id, from: q.data.a.entity_id, codes: [attr.code] })}
                    >
                      A &rarr; B
                    </button>{" "}
                    <button
                      className="small"
                      title="Copy B to A"
                      disabled={copy.isPending || !differs || !!ca?.read_only}
                      onClick={() => copy.mutate({ to: q.data.a.entity_id, from: q.data.b.entity_id, codes: [attr.code] })}
                    >
                      B &rarr; A
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
