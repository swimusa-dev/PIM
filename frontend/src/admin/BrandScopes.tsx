// D-15, RBAC-04: brand scopes. A brand is a rule over the ERP fields stored on each product: a scope matches when ANY of
// its rules matches, and a rule matches when ALL its conditions do. Edited here instead of the seed files; channels pick
// scopes in their eligibility rules and user roles use them to limit what a person sees.

import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { isAdmin, useMe } from "../api/hooks";
import type { BrandScopeDef, ScopeMatches } from "../api/types";
import { Badge, Dialog, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { RecomputeButton } from "./Eligibility";

interface Cond {
  field: string;
  op: string;
  value: string;
}

const OP_LABEL: Record<string, string> = { eq: "is", neq: "is not", in: "is one of", contains: "contains" };

const fromServer = (rules: BrandScopeDef["rules"]): Cond[][] =>
  rules.map((r) => r.map((c) => ({ field: c.field, op: c.op, value: Array.isArray(c.value) ? c.value.join(", ") : c.value })));

const toServer = (rules: Cond[][]) =>
  rules.map((r) => r.map((c) => ({ field: c.field, op: c.op, value: c.op === "in" ? c.value.split(",").map((v) => v.trim()).filter(Boolean) : c.value.trim() })));

export function summarize(rules: BrandScopeDef["rules"]): string {
  return rules
    .map((r) => r.map((c) => `${c.field.replace("_", " ")} ${OP_LABEL[c.op] ?? c.op} ${Array.isArray(c.value) ? c.value.join(" or ") : c.value}`).join(" and "))
    .join("  OR  ");
}

export function BrandScopesTab() {
  const me = useMe();
  const admin = isAdmin(me.data);
  const toast = useToast();
  const qc = useQueryClient();
  const scopes = useQuery({ queryKey: ["metadata", "brand-scopes"], queryFn: api.metadata.brandScopes });
  const [editing, setEditing] = useState<{ scope: BrandScopeDef; isNew: boolean } | null>(null);
  const [needsApply, setNeedsApply] = useState(false);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["metadata"] });
    setNeedsApply(true);
  };
  const remove = useMutation({
    mutationFn: (code: string) => api.metadata.deleteBrandScope(code),
    onSuccess: () => {
      toast("Brand scope deleted", "ok");
      refresh();
    },
    onError: (e) => toast((e as Error).message, "error"),
  });

  if (scopes.isLoading) return <Spinner label="Loading brand scopes" />;
  if (scopes.isError) return <ErrorBox error={scopes.error} title="Could not load brand scopes" />;

  return (
    <div className="stack">
      <div className="row mb8" style={{ justifyContent: "space-between" }}>
        <span className="muted small">
          A brand scope groups products by a rule over their division, brand and other ERP fields. Channels choose scopes in their eligibility rules.
        </span>
        {admin && (
          <button className="primary" onClick={() => setEditing({ scope: { code: "", label: "", enabled: true, rules: [[{ field: "division", op: "eq", value: "" }]], used_by: [] }, isNew: true })}>
            Add brand scope
          </button>
        )}
      </div>
      {needsApply && admin && (
        <div className="panel">
          <div className="panel-body row" style={{ justifyContent: "space-between" }}>
            <span className="small">Changes to a scope apply to the products already loaded once you apply them. Readiness is recomputed too.</span>
            <RecomputeButton primary onDone={() => setNeedsApply(false)} />
          </div>
        </div>
      )}
      {scopes.data!.length === 0 ? (
        <Empty title="No brand scopes">Add one to group products by division or brand.</Empty>
      ) : (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Code</th>
                <th>Label</th>
                <th>Rule</th>
                <th>Status</th>
                <th>Used by</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {scopes.data!.map((s) => (
                <Fragment key={s.code}>
                  <tr>
                    <td className="mono">{s.code}</td>
                    <td>{s.label}</td>
                    <td className="small">{summarize(s.rules)}</td>
                    <td>{s.enabled ? <Badge color="green">enabled</Badge> : <Badge>disabled</Badge>}</td>
                    <td>
                      <div className="chips">
                        {s.used_by.map((u) => (
                          <span key={u} className="badge">
                            {u}
                          </span>
                        ))}
                        {s.used_by.length === 0 && <span className="faint">nothing</span>}
                      </div>
                    </td>
                    <td className="nowrap">
                      {admin && (
                        <>
                          <button className="small" onClick={() => setEditing({ scope: s, isNew: false })}>
                            Edit
                          </button>{" "}
                          <button
                            className="small"
                            disabled={s.used_by.length > 0 || remove.isPending}
                            title={s.used_by.length > 0 ? "In use. Remove it from its channels and roles first, or disable it." : "Delete this scope"}
                            onClick={() => window.confirm(`Delete the brand scope ${s.label}?`) && remove.mutate(s.code)}
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <ScopeDialog
          initial={editing.scope}
          isNew={editing.isNew}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function ScopeDialog({ initial, isNew, onClose, onSaved }: { initial: BrandScopeDef; isNew: boolean; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const options = useQuery({ queryKey: ["metadata", "eligibility-options"], queryFn: api.metadata.eligibilityOptions });
  const [code, setCode] = useState(initial.code);
  const [label, setLabel] = useState(initial.label);
  const [enabled, setEnabled] = useState(initial.enabled);
  const [rules, setRules] = useState<Cond[][]>(fromServer(initial.rules));
  const [matches, setMatches] = useState<ScopeMatches | null>(null);

  const edit = (next: Cond[][]) => {
    setRules(next);
    setMatches(null);
  };
  const setCond = (ri: number, ci: number, patch: Partial<Cond>) => edit(rules.map((r, i) => (i !== ri ? r : r.map((c, j) => (j !== ci ? c : { ...c, ...patch })))));
  const preview = useMutation({ mutationFn: () => api.metadata.previewBrandScope(toServer(rules)), onSuccess: setMatches });
  const save = useMutation({
    mutationFn: () => api.metadata.saveBrandScope(code, { label, enabled, rules: toServer(rules) }),
    onSuccess: () => {
      toast(`Saved ${label}.`, "ok");
      onSaved();
    },
  });

  const valid = /^[a-z][a-z0-9_]{1,62}$/.test(code) && label.trim() !== "" && rules.length > 0 && rules.every((r) => r.length > 0 && r.every((c) => c.value.trim() !== ""));
  const fields = options.data?.fields ?? ["division"];
  const ops = options.data?.ops ?? ["eq"];

  return (
    <Dialog
      title={isNew ? "Add brand scope" : `Edit brand scope ${initial.code}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button onClick={onClose} disabled={save.isPending}>
            Cancel
          </button>
          <button onClick={() => preview.mutate()} disabled={!valid || preview.isPending}>
            {preview.isPending ? "Counting" : "Preview matches"}
          </button>
          <button className="primary" onClick={() => save.mutate()} disabled={!valid || save.isPending}>
            {save.isPending ? "Saving" : "Save"}
          </button>
        </>
      }
    >
      <div className="stack">
        <div className="form-grid">
          <label className="field">
            Label
            <input value={label} onChange={(ev) => setLabel(ev.target.value)} placeholder="Miraclesuit" />
          </label>
          <label className="field">
            Code (lower case letters, digits and underscores)
            <input className="mono" value={code} disabled={!isNew} onChange={(ev) => setCode(ev.target.value)} placeholder="miraclesuit" />
          </label>
          <label className="inline" style={{ alignSelf: "end" }}>
            <input type="checkbox" checked={enabled} onChange={(ev) => setEnabled(ev.target.checked)} /> Enabled
          </label>
        </div>

        <p className="muted small">
          The scope matches a product when <strong>any</strong> of the rules below matches. A rule matches when <strong>all</strong> of its conditions do.
          Values are not case sensitive. For "is one of", separate the values with commas.
        </p>
        {rules.map((rule, ri) => (
          <Fragment key={ri}>
            {ri > 0 && <div className="muted small" style={{ textAlign: "center" }}>or</div>}
            <div className="panel">
              <div className="panel-body stack">
                {rule.map((c, ci) => (
                  <div className="row" key={ci} style={{ gap: 8 }}>
                    <span className="muted small" style={{ width: 28 }}>{ci === 0 ? "when" : "and"}</span>
                    <select value={c.field} onChange={(ev) => setCond(ri, ci, { field: ev.target.value })}>
                      {fields.map((f) => (
                        <option key={f} value={f}>
                          {f.replace("_", " ")}
                        </option>
                      ))}
                    </select>
                    <select value={c.op} onChange={(ev) => setCond(ri, ci, { op: ev.target.value })}>
                      {ops.map((op) => (
                        <option key={op} value={op}>
                          {OP_LABEL[op] ?? op}
                        </option>
                      ))}
                    </select>
                    <input className="grow" value={c.value} onChange={(ev) => setCond(ri, ci, { value: ev.target.value })} placeholder={c.op === "in" ? "VALUE ONE, VALUE TWO" : "VALUE"} />
                    <button
                      className="small"
                      disabled={rule.length === 1}
                      title="Remove this condition"
                      onClick={() => edit(rules.map((r, i) => (i !== ri ? r : r.filter((_, j) => j !== ci))))}
                    >
                      Remove
                    </button>
                  </div>
                ))}
                <div className="row">
                  <button className="small" onClick={() => edit(rules.map((r, i) => (i !== ri ? r : [...r, { field: "division", op: "eq", value: "" }])))}>
                    Add condition (and)
                  </button>
                  <button className="small" disabled={rules.length === 1} onClick={() => edit(rules.filter((_, i) => i !== ri))}>
                    Remove this rule
                  </button>
                </div>
              </div>
            </div>
          </Fragment>
        ))}
        <div>
          <button className="small" onClick={() => edit([...rules, [{ field: "division", op: "eq", value: "" }]])}>
            Add another rule (or)
          </button>
        </div>

        {preview.isError && <ErrorBox error={preview.error} title="Could not count matches" />}
        {matches && (
          <div className="panel">
            <div className="panel-body stack">
              <strong>
                {matches.style_colors.toLocaleString()} style-colors in {matches.styles.toLocaleString()} styles match
              </strong>
              {matches.divisions.length > 0 && (
                <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                  {matches.divisions.map((d) => (
                    <li key={d.division}>
                      {d.division}: {d.style_colors.toLocaleString()}
                    </li>
                  ))}
                </ul>
              )}
              {matches.style_colors === 0 && <span className="muted small">Nothing matches. Check the spelling of the value against your Style Master.</span>}
            </div>
          </div>
        )}
        {save.isError && <ErrorBox error={save.error} title="Save failed" />}
      </div>
    </Dialog>
  );
}
