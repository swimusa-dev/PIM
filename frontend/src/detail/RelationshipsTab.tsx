// DM-13: Product relationships tab. Own and inherited links grouped by type, target as a link to its product
// page, Broken and Inherited badges, quantity when the type allows it, Remove on own links, and an add form
// with a type select, a product search picker, a paste box and an optional quantity. Read only without edit
// rights on the style details group (admins pass). Layer still owns Shopify cross-sell data (D-09).

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, relationshipApi } from "../api/client";
import { isAdmin, useMe } from "../api/hooks";
import type { Level, Me, ProductRow, Relationship, RelationshipAddResult, RelationshipType } from "../api/types";
import { Badge, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { formatDate, LEVEL_LABEL } from "../lib/format";

const STYLE_DETAILS_GROUP = "style_details";

/** Edit on the style details group (or the `*` wildcard), or the admin_metadata permission. */
export function canEditRelationships(me: Me | undefined): boolean {
  if (!me) return false;
  if (isAdmin(me)) return true;
  const r = me.data_rights[STYLE_DETAILS_GROUP] ?? me.data_rights["*"] ?? "none";
  return r === "edit" || r === "approve";
}

function targetText(t: Relationship["target"]): string {
  const ids = [t.style_number, t.color_code].filter(Boolean).join("-");
  if (ids && t.label) return `${ids} ${t.label}`;
  return ids || t.label || t.entity_id;
}

/** Debounced search over the products query; picking a row hands its entity id to the caller. */
function ProductPicker({ level, exclude, onPick }: { level: Level; exclude: Set<string>; onPick: (row: ProductRow) => void }) {
  const [text, setText] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const h = window.setTimeout(() => setDebounced(text.trim()), 300);
    return () => window.clearTimeout(h);
  }, [text]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (hostRef.current && !hostRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const q = useQuery({
    queryKey: ["products", "search", level, debounced],
    queryFn: () => api.products.query({ level, page: 1, page_size: 10, sort: [], filters: [], search: debounced, columns: [] }),
    enabled: open && debounced.length > 0,
  });

  return (
    <div className="popover-host" ref={hostRef} style={{ display: "block" }}>
      <label className="field">
        Search products
        <input
          value={text}
          placeholder={`Search ${LEVEL_LABEL[level] ?? level} by style number, name or UPC`}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
          }}
        />
      </label>
      {open && debounced && (
        <div className="search-results">
          {q.isLoading && <div className="item faint">Searching</div>}
          {q.isError && <div className="item" style={{ color: "var(--red)" }}>Search failed</div>}
          {q.data && q.data.rows.length === 0 && <div className="item faint">No matches</div>}
          {q.data?.rows.map((r) => {
            const already = exclude.has(r.entity_id);
            return (
              <div
                key={r.entity_id}
                className={`item${already ? " faint" : ""}`}
                onClick={() => {
                  if (already) return;
                  onPick(r);
                  setText("");
                  setDebounced("");
                  setOpen(false);
                }}
              >
                <span className="mono">{[r.style_number, r.color_code].filter(Boolean).join("-")}</span> {r.label}
                {already && <span className="faint small"> (added)</span>}
                {r.lifecycle_status === "discontinued" && <Badge color="red">discontinued</Badge>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function RelationshipsTab({ entityId, level }: { entityId: string; level: Level }) {
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const editable = canEditRelationships(me.data);

  const rowsQ = useQuery({ queryKey: ["product", entityId, "relationships"], queryFn: () => relationshipApi.list(entityId) });
  const typesQ = useQuery({ queryKey: ["relationship-types"], queryFn: () => relationshipApi.types(), staleTime: 5 * 60 * 1000 });

  const [typeCode, setTypeCode] = useState("");
  const [targets, setTargets] = useState<ProductRow[]>([]);
  const [paste, setPaste] = useState("");
  const [quantity, setQuantity] = useState("");
  const [lastResult, setLastResult] = useState<RelationshipAddResult | null>(null);

  const levelTypes = useMemo(
    () => (typesQ.data ?? []).filter((t) => t.enabled && t.level === level).sort((a, b) => a.sort_order - b.sort_order),
    [typesQ.data, level],
  );
  const selectedType: RelationshipType | undefined = levelTypes.find((t) => t.code === typeCode) ?? levelTypes[0];
  const effectiveTypeCode = selectedType?.code ?? "";

  const typeOrder = useMemo(() => {
    const m = new Map<string, number>();
    for (const t of typesQ.data ?? []) m.set(t.code, t.sort_order);
    return m;
  }, [typesQ.data]);

  const groups = useMemo(() => {
    const byType = new Map<string, { label: string; rows: Relationship[] }>();
    for (const r of rowsQ.data?.rows ?? []) {
      const g = byType.get(r.type_code) ?? { label: r.type_label, rows: [] };
      g.rows.push(r);
      byType.set(r.type_code, g);
    }
    return Array.from(byType.entries())
      .sort(([a], [b]) => (typeOrder.get(a) ?? 999) - (typeOrder.get(b) ?? 999) || a.localeCompare(b))
      .map(([code, g]) => ({ code, ...g }));
  }, [rowsQ.data, typeOrder]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["product", entityId] });
    qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
  };

  const add = useMutation({
    mutationFn: () =>
      relationshipApi.add(entityId, {
        type_code: effectiveTypeCode,
        targets: targets.length ? targets.map((t) => t.entity_id) : undefined,
        paste: paste.trim() || undefined,
        quantity: selectedType?.allows_quantity && quantity.trim() !== "" ? Number(quantity) : undefined,
      }),
    onSuccess: (res) => {
      setLastResult(res);
      setTargets([]);
      setPaste("");
      const skipped = res.skipped?.length ?? 0;
      toast(`${res.created} relationship${res.created === 1 ? "" : "s"} added${skipped ? `, ${skipped} skipped` : ""}.`, skipped && !res.created ? "warn" : "ok");
      invalidate();
    },
    onError: (e) => toast(`Could not add: ${(e as Error).message}`, "error"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => relationshipApi.remove(id),
    onSuccess: () => {
      toast("Relationship removed.", "ok");
      invalidate();
    },
    onError: (e) => toast(`Could not remove: ${(e as Error).message}`, "error"),
  });

  const quantityInvalid = !!selectedType?.allows_quantity && quantity.trim() !== "" && !(Number(quantity) > 0);
  const canSubmit = !!effectiveTypeCode && (targets.length > 0 || paste.trim().length > 0) && !quantityInvalid && !add.isPending;
  const excluded = useMemo(() => new Set([entityId, ...targets.map((t) => t.entity_id)]), [entityId, targets]);

  return (
    <div className="stack gap16">
      <div className="panel">
        <div className="panel-header">
          <h3>
            Relationships <span className="muted small">{rowsQ.data?.rows.length ?? 0}</span>
          </h3>
          {!editable && <span className="muted small">Read only: editing needs the style details group.</span>}
        </div>
        {rowsQ.isLoading && (
          <div className="panel-body">
            <Spinner label="Loading relationships" />
          </div>
        )}
        {rowsQ.isError && (
          <div className="panel-body">
            <ErrorBox error={rowsQ.error} title="Could not load relationships" />
          </div>
        )}
        {rowsQ.data && groups.length === 0 && (
          <Empty title="No related products">
            {level === "style_color" ? "Links set on this style-color or inherited from its style appear here." : "Nothing is linked to this product yet."}
          </Empty>
        )}
        {groups.map((g) => (
          <div key={g.code}>
            <div className="row" style={{ padding: "8px 12px 4px", gap: 8 }}>
              <b>{g.label}</b>
              <span className="muted small">{g.rows.length}</span>
            </div>
            <table className="data compact">
              <tbody>
                {g.rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/products/${encodeURIComponent(r.target.entity_id)}`}>{targetText(r.target)}</Link>
                    </td>
                    <td className="nowrap">
                      {r.inherited && <Badge title="Set on the style; edit it there">Inherited from style</Badge>}{" "}
                      {r.broken && <Badge color="amber" title="The related product is discontinued or missing">Broken</Badge>}{" "}
                      {r.direction === "two_way" && <Badge title="Both products link to each other">two way</Badge>}
                    </td>
                    <td className="nowrap">{r.quantity !== null && r.quantity !== undefined ? `Qty ${r.quantity}` : ""}</td>
                    <td className="muted small nowrap">
                      {r.created_by} on {formatDate(r.created_at, false)}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {editable && !r.inherited && (
                        <button className="small" disabled={remove.isPending} onClick={() => remove.mutate(r.id)}>
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>

      {editable && level === "sku" && <div className="muted small">Relationships are set on styles and style-colors, not on SKUs.</div>}

      {editable && level !== "sku" && (
        <div className="panel">
          <div className="panel-header">
            <h3>Add relationships</h3>
          </div>
          <div className="panel-body stack">
            {typesQ.isError && <ErrorBox error={typesQ.error} title="Could not load relationship types" />}
            {typesQ.data && levelTypes.length === 0 && (
              <span className="muted small">No enabled relationship type applies to a {LEVEL_LABEL[level] ?? level}.</span>
            )}
            {levelTypes.length > 0 && (
              <>
                <label className="field">
                  Type
                  <select value={effectiveTypeCode} onChange={(e) => setTypeCode(e.target.value)}>
                    {levelTypes.map((t) => (
                      <option key={t.code} value={t.code}>
                        {t.label}
                        {t.direction === "two_way" ? " (two way)" : ""}
                      </option>
                    ))}
                  </select>
                </label>
                {selectedType?.help_text && <div className="muted small">{selectedType.help_text}</div>}
                <ProductPicker level={level} exclude={excluded} onPick={(r) => setTargets((t) => [...t, r])} />
                {targets.length > 0 && (
                  <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
                    {targets.map((t) => (
                      <span key={t.entity_id} className="badge teal">
                        {[t.style_number, t.color_code].filter(Boolean).join("-")} {t.label}{" "}
                        <button className="link small" style={{ marginLeft: 4 }} onClick={() => setTargets((x) => x.filter((y) => y.entity_id !== t.entity_id))} aria-label={`Remove ${t.label}`}>
                          x
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <label className="field">
                  Or paste a list
                  <textarea
                    value={paste}
                    onChange={(e) => setPaste(e.target.value)}
                    placeholder={level === "style" ? "Style numbers separated by commas, e.g. 200809, 200811" : "Style-colors separated by commas, e.g. 200809-FVP, 200809 ECB"}
                    rows={2}
                  />
                </label>
                {selectedType?.allows_quantity && (
                  <label className="field" style={{ maxWidth: 160 }}>
                    Quantity (optional)
                    <input type="number" min={1} step={1} value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="e.g. 2" />
                    {quantityInvalid && <span className="field-error">Enter a whole number above zero.</span>}
                  </label>
                )}
                <div className="row">
                  <button className="primary" disabled={!canSubmit} onClick={() => add.mutate()}>
                    {add.isPending ? "Adding" : "Add"}
                  </button>
                  {selectedType?.direction === "two_way" && <span className="muted small">Two way: the related product links back here.</span>}
                </div>
              </>
            )}
            {add.isError && <ErrorBox error={add.error} title="Could not add relationships" />}
            {lastResult && (
              <div className="small">
                <div>
                  Added {lastResult.created}
                  {lastResult.skipped.length > 0 ? `, skipped ${lastResult.skipped.length}` : ""}.
                </div>
                {lastResult.skipped.length > 0 && (
                  <ul className="reasons small">
                    {lastResult.skipped.map((s, i) => (
                      <li key={i}>
                        <span className="mono">{s.token}</span>: {s.reason}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
