// 1.3: Attribute groups (editable, PUT /api/metadata/groups) and families (read from metadata).

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAttributes, useFamilies, useGroups } from "../api/hooks";
import type { AttributeGroup } from "../api/types";
import { Empty, ErrorBox, Spinner, useToast } from "../components/Common";

export function GroupsTab() {
  const groups = useGroups();
  const attrs = useAttributes();
  const qc = useQueryClient();
  const toast = useToast();
  const [rows, setRows] = useState<AttributeGroup[]>([]);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (groups.data && !dirty) setRows(groups.data.slice().sort((a, b) => a.sort_order - b.sort_order));
  }, [groups.data, dirty]);

  const save = useMutation({
    mutationFn: () => api.metadata.saveGroups(rows),
    onSuccess: () => {
      toast("Groups saved", "ok");
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["metadata"] });
    },
    onError: (e) => toast(`Save failed: ${(e as Error).message}`, "error"),
  });

  const update = (i: number, patch: Partial<AttributeGroup>) => {
    setRows((r) => r.map((g, j) => (j === i ? { ...g, ...patch } : g)));
    setDirty(true);
  };
  const add = () => {
    setRows((r) => [...r, { code: "", label: "", owning_role: "", sort_order: (r[r.length - 1]?.sort_order ?? 0) + 10, read_only: false }]);
    setDirty(true);
  };
  const countFor = (code: string) => (attrs.data ?? []).filter((a) => a.group_code === code).length;

  if (groups.isLoading) return <Spinner label="Loading groups" />;
  if (groups.isError) return <ErrorBox error={groups.error} title="Could not load groups" />;

  return (
    <div>
      <div className="row mb8" style={{ justifyContent: "space-between" }}>
        <span className="muted small">Groups order the detail page and carry the owning role used for data rights.</span>
        <div className="row">
          <button onClick={add}>Add group</button>
          <button className="primary" disabled={!dirty || save.isPending || rows.some((g) => !g.code || !g.label)} onClick={() => save.mutate()}>
            {save.isPending ? "Saving" : "Save all"}
          </button>
        </div>
      </div>
      <div className="panel">
        <table className="data compact">
          <thead>
            <tr>
              <th>Code</th>
              <th>Label</th>
              <th>Owning role</th>
              <th>Sort</th>
              <th>Read only</th>
              <th className="right">Attributes</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((g, i) => (
              <tr key={i}>
                <td>
                  <input className="mono" value={g.code} onChange={(e) => update(i, { code: e.target.value })} disabled={!!groups.data?.some((x) => x.code === g.code && g.code !== "")} />
                </td>
                <td>
                  <input value={g.label} onChange={(e) => update(i, { label: e.target.value })} />
                </td>
                <td>
                  <input value={g.owning_role} onChange={(e) => update(i, { owning_role: e.target.value })} />
                </td>
                <td style={{ width: 80 }}>
                  <input type="number" value={g.sort_order} onChange={(e) => update(i, { sort_order: Number(e.target.value) })} />
                </td>
                <td>
                  <input type="checkbox" checked={g.read_only} onChange={(e) => update(i, { read_only: e.target.checked })} />
                </td>
                <td className="num">{countFor(g.code)}</td>
                <td>
                  {countFor(g.code) === 0 && (
                    <button
                      className="small danger"
                      onClick={() => {
                        setRows((r) => r.filter((_, j) => j !== i));
                        setDirty(true);
                      }}
                    >
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <Empty title="No groups">Add groups such as Style Details, Merch, SEO, Copy, and one per channel.</Empty>}
      </div>
    </div>
  );
}

export function FamiliesTab() {
  const families = useFamilies();
  const groups = useGroups();
  if (families.isLoading) return <Spinner label="Loading families" />;
  if (families.isError) return <ErrorBox error={families.error} title="Could not load families" />;
  const label = (code: string) => groups.data?.find((g) => g.code === code)?.label ?? code;
  return (
    <div>
      <p className="muted small">
        A family says which attribute groups apply to a product type. Families are seeded from the repo YAML; the contract has
        no family write endpoint yet, so this view is read only.
      </p>
      {families.data!.length === 0 ? (
        <Empty title="No families">Seed families such as Swim Top, Swim Bottom, One-Piece, Cover-Up and Apparel.</Empty>
      ) : (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Code</th>
                <th>Label</th>
                <th>Attribute groups</th>
              </tr>
            </thead>
            <tbody>
              {families.data!.map((f) => (
                <tr key={f.code}>
                  <td className="mono">{f.code}</td>
                  <td>{f.label}</td>
                  <td>
                    <div className="chips">
                      {f.group_codes.map((g) => (
                        <span key={g} className="badge teal">
                          {label(g)}
                        </span>
                      ))}
                    </div>
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
