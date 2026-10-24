// DM-11: Reference entities (Print, Fabric, Model profile, and any type the metadata defines).
// List with search, detail form from the type's attributes, impact dialog before saving.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAttributes, useMe, useOptionLists, useReferenceTypes, canEdit } from "../api/hooks";
import { AiBadge, Dialog, Empty, ErrorBox, LockIcon, Provenance, Spinner, useToast } from "../components/Common";
import { ValueEditor } from "../components/ValueEditor";
import { cellValue, displayValue } from "../lib/format";
import type { OptionList, ReferenceImpact } from "../api/types";

export function ReferenceIndexPage() {
  const types = useReferenceTypes();
  if (types.isLoading) return <Spinner />;
  if (types.isError) return <ErrorBox error={types.error} title="Could not load reference types" />;
  return (
    <div>
      <div className="page-header">
        <h1>Reference data</h1>
      </div>
      {types.data!.length === 0 ? (
        <Empty title="No reference entity types are defined">
          Seed Print, Fabric and Model profile types in the metadata layer to manage shared copy here.
        </Empty>
      ) : (
        <div className="cards">
          {types.data!.map((t) => (
            <Link key={t.code} to={`/reference/${encodeURIComponent(t.code)}`} style={{ color: "inherit", textDecoration: "none" }}>
              <div className="card">
                <div className="card-title">{t.code}</div>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{t.label}</div>
                <div className="muted small">{t.attribute_codes.length} attributes</div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export function ReferenceListPage() {
  const { type = "" } = useParams();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const types = useReferenceTypes();
  const typeDef = types.data?.find((t) => t.code === type);
  const attrs = useAttributes({ level: `ref:${type}` });
  const optionLists = useOptionLists();
  const listByCode = useMemo(() => indexLists(optionLists.data), [optionLists.data]);

  const list = useQuery({
    queryKey: ["reference", type, search, page],
    queryFn: () => api.reference.list(type, { q: search, page, page_size: pageSize }),
  });

  // Show the first few attributes of the type as list columns, driven by metadata.
  const columns = useMemo(() => (attrs.data ?? []).slice().sort((a, b) => a.sort_order - b.sort_order).slice(0, 4), [attrs.data]);

  return (
    <div>
      <div className="page-header">
        <h1>
          <Link to="/reference">Reference data</Link> / {typeDef?.label ?? type}
        </h1>
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(1);
            setSearch(q);
          }}
        >
          <input placeholder={`Search ${typeDef?.label ?? type}`} value={q} onChange={(e) => setQ(e.target.value)} />
          <button type="submit">Search</button>
        </form>
      </div>
      {list.isLoading && <Spinner />}
      {list.isError && <ErrorBox error={list.error} title="Could not load records" />}
      {list.data && list.data.rows.length === 0 && (
        <Empty title={search ? `No ${typeDef?.label ?? type} records match "${search}"` : `No ${typeDef?.label ?? type} records yet`}>
          Records are created by imports or the admin seed; link products to them from the product detail page.
        </Empty>
      )}
      {list.data && list.data.rows.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Code</th>
                <th>Label</th>
                {columns.map((c) => (
                  <th key={c.code}>{c.label}</th>
                ))}
                <th className="right">Linked products</th>
              </tr>
            </thead>
            <tbody>
              {list.data.rows.map((r) => (
                <tr key={r.id}>
                  <td className="mono">
                    <Link to={`/reference/${encodeURIComponent(type)}/${encodeURIComponent(r.id)}`}>{r.code}</Link>
                  </td>
                  <td>{r.label}</td>
                  {columns.map((c) => (
                    <td key={c.code} style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {displayValue(cellValue(r.values[c.code]), c, listByCode)}
                    </td>
                  ))}
                  <td className="num">{r.linked_products}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="grid-status">
            <span>
              {list.data.total} record{list.data.total === 1 ? "" : "s"}
            </span>
            <span className="row">
              <button className="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </button>
              <span>
                Page {page} of {Math.max(1, Math.ceil(list.data.total / pageSize))}
              </span>
              <button className="small" disabled={page * pageSize >= list.data.total} onClick={() => setPage((p) => p + 1)}>
                Next
              </button>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

export function ReferenceDetailPage() {
  const { type = "", id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const me = useMe();
  const types = useReferenceTypes();
  const typeDef = types.data?.find((t) => t.code === type);
  const attrs = useAttributes({ level: `ref:${type}` });
  const optionLists = useOptionLists();
  const listByCode = useMemo(() => indexLists(optionLists.data), [optionLists.data]);

  const detail = useQuery({ queryKey: ["reference", type, "detail", id], queryFn: () => api.reference.detail(type, id) });
  const [edits, setEdits] = useState<Record<string, unknown>>({});
  const [impact, setImpact] = useState<ReferenceImpact | null>(null);

  const preview = useMutation({
    mutationFn: () => api.reference.save(type, id, edits, false),
    onSuccess: (r) => setImpact(r),
  });
  const save = useMutation({
    mutationFn: () => api.reference.save(type, id, edits, true),
    onSuccess: () => {
      toast("Saved. Linked products were updated.", "ok");
      setEdits({});
      setImpact(null);
      qc.invalidateQueries({ queryKey: ["reference", type] });
      qc.invalidateQueries({ queryKey: ["products"] });
    },
  });

  if (detail.isLoading || attrs.isLoading) return <Spinner label="Loading record" />;
  if (detail.isError) return <ErrorBox error={detail.error} title="Could not load the record" />;
  if (attrs.isError) return <ErrorBox error={attrs.error} title="Could not load attribute metadata" />;
  const row = detail.data!;
  const sorted = (attrs.data ?? []).slice().sort((a, b) => a.sort_order - b.sort_order);
  const dirty = Object.keys(edits).length;

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="muted small">
            <Link to="/reference">Reference data</Link> / <Link to={`/reference/${encodeURIComponent(type)}`}>{typeDef?.label ?? type}</Link>
          </div>
          <h1>
            {row.label} <span className="mono muted" style={{ fontSize: 13 }}>{row.code}</span>
          </h1>
          <div className="muted small">
            Linked to {row.linked_products} product{row.linked_products === 1 ? "" : "s"}. Changes here update every linked product.
          </div>
        </div>
        <div className="actions">
          <button onClick={() => navigate(-1)}>Back</button>
          <button onClick={() => setEdits({})} disabled={!dirty}>
            Discard changes
          </button>
          <button className="primary" disabled={!dirty || preview.isPending} onClick={() => preview.mutate()}>
            {preview.isPending ? "Checking impact" : `Save${dirty ? ` (${dirty})` : ""}`}
          </button>
        </div>
      </div>
      {preview.isError && <ErrorBox error={preview.error} title="Could not compute impact" />}

      <div className="panel">
        {sorted.length === 0 && (
          <Empty title="This type has no attributes">Add attributes with level ref:{type} under Admin, Attributes.</Empty>
        )}
        {sorted.map((a) => {
          const cell = row.values[a.code];
          const editable = canEdit(me.data, a) && !(cell?.read_only ?? false) && a.status !== "deprecated";
          const current = a.code in edits ? edits[a.code] : cellValue(cell);
          return (
            <div className="attr-row" key={a.code}>
              <div className="attr-label">
                {a.label}
                <LockIcon cell={cell} />
                {cell?.ai_generated && <AiBadge />}
                <span className="code">{a.code}</span>
              </div>
              <div className="attr-value">
                {editable ? (
                  <ValueEditor
                    key={`${a.code}:${String(current)}`}
                    attr={a}
                    optionList={a.option_list_code ? listByCode[a.option_list_code] : undefined}
                    value={current}
                    onCommit={(v) => setEdits((e) => ({ ...e, [a.code]: v }))}
                  />
                ) : (
                  <Provenance cell={cell}>
                    <div className="readonly-value">{displayValue(current, a, listByCode) || <span className="faint">empty</span>}</div>
                  </Provenance>
                )}
                {a.help_text && <div className="help">{a.help_text}</div>}
              </div>
            </div>
          );
        })}
      </div>

      {impact && (
        <Dialog
          title="Confirm save"
          onClose={() => setImpact(null)}
          footer={
            <>
              <button onClick={() => setImpact(null)} disabled={save.isPending}>
                Cancel
              </button>
              <button className="primary" onClick={() => save.mutate()} disabled={save.isPending}>
                {save.isPending ? "Saving" : "Save"}
              </button>
            </>
          }
        >
          <p>
            This change affects <b>{impact.impact.products}</b> product{impact.impact.products === 1 ? "" : "s"}
            {impact.impact.channels.length > 0 ? (
              <>
                {" "}
                across channels <b>{impact.impact.channels.join(", ")}</b>
              </>
            ) : (
              " and no channel exports"
            )}
            . Save?
          </p>
          <ul className="muted small">
            {Object.keys(edits).map((k) => (
              <li key={k}>
                {sorted.find((a) => a.code === k)?.label ?? k}: {displayValue(edits[k], sorted.find((a) => a.code === k), listByCode) || "(cleared)"}
              </li>
            ))}
          </ul>
          {save.isError && <ErrorBox error={save.error} title="Save failed" />}
        </Dialog>
      )}
    </div>
  );
}

function indexLists(lists: OptionList[] | undefined): Record<string, OptionList> {
  const m: Record<string, OptionList> = {};
  for (const l of lists ?? []) m[l.code] = l;
  return m;
}

