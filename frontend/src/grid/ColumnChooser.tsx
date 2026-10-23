// DM-02: Column chooser grouped by attribute group, driven by metadata.

import { useEffect, useMemo, useRef, useState } from "react";
import type { FieldDef } from "./fields";

export function ColumnChooser({
  fields,
  columns,
  onChange,
}: {
  fields: FieldDef[];
  columns: string[];
  onChange: (cols: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (host.current && !host.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const groups = useMemo(() => {
    const m = new Map<string, { label: string; order: number; fields: FieldDef[] }>();
    for (const f of fields) {
      if (q && !f.label.toLowerCase().includes(q.toLowerCase()) && !f.key.toLowerCase().includes(q.toLowerCase())) continue;
      const g = m.get(f.groupCode) ?? { label: f.groupLabel, order: f.groupOrder, fields: [] };
      g.fields.push(f);
      m.set(f.groupCode, g);
    }
    return Array.from(m.values()).sort((a, b) => a.order - b.order);
  }, [fields, q]);

  const selected = new Set(columns);
  const toggle = (key: string) => {
    if (selected.has(key)) onChange(columns.filter((c) => c !== key));
    else onChange([...columns, key]);
  };
  const toggleGroup = (fs: FieldDef[]) => {
    const all = fs.every((f) => selected.has(f.key));
    if (all) onChange(columns.filter((c) => !fs.some((f) => f.key === c)));
    else onChange([...columns, ...fs.filter((f) => !selected.has(f.key)).map((f) => f.key)]);
  };

  return (
    <div className="popover-host" ref={host}>
      <button onClick={() => setOpen((o) => !o)}>Columns ({columns.length})</button>
      {open && (
        <div className="popover" style={{ minWidth: 340 }}>
          <input placeholder="Find a column" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: "100%" }} autoFocus />
          {groups.map((g) => (
            <div key={g.label}>
              <h4 className="row" style={{ justifyContent: "space-between" }}>
                {g.label}
                <button className="link small" onClick={() => toggleGroup(g.fields)}>
                  {g.fields.every((f) => selected.has(f.key)) ? "none" : "all"}
                </button>
              </h4>
              {g.fields.map((f) => (
                <label key={f.key} className="inline">
                  <input type="checkbox" checked={selected.has(f.key)} onChange={() => toggle(f.key)} />
                  <span className="grow">{f.label}</span>
                  {f.attr && <span className="faint mono small">{f.attr.code}</span>}
                  {f.attr?.status === "deprecated" && <span className="badge red">deprecated</span>}
                </label>
              ))}
            </div>
          ))}
          {groups.length === 0 && <div className="empty">No column matches "{q}".</div>}
        </div>
      )}
    </div>
  );
}
