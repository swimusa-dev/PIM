// 1.3, DM-14: Option lists with values (code, label, sort, per-channel mappings). Size scales are flagged with size_group.

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useChannels, useOptionLists } from "../api/hooks";
import type { OptionList, OptionValue } from "../api/types";
import { Badge, Empty, ErrorBox, Spinner, useToast } from "../components/Common";

export function OptionListsTab() {
  const lists = useOptionLists();
  const channels = useChannels();
  const qc = useQueryClient();
  const toast = useToast();
  const [selected, setSelected] = useState<string>("");
  const [draft, setDraft] = useState<OptionList | null>(null);
  const [creating, setCreating] = useState(false);

  const current = lists.data?.find((l) => l.code === selected) ?? null;
  useEffect(() => {
    if (creating) return;
    setDraft(current ? JSON.parse(JSON.stringify(current)) : null);
  }, [current, creating]);

  const save = useMutation({
    mutationFn: (l: OptionList) => api.metadata.saveOptionList(l.code, l),
    onSuccess: (_, l) => {
      toast("Option list saved", "ok");
      setCreating(false);
      setSelected(l.code);
      qc.invalidateQueries({ queryKey: ["metadata"] });
    },
    onError: (e) => toast(`Save failed: ${(e as Error).message}`, "error"),
  });

  if (lists.isLoading) return <Spinner label="Loading option lists" />;
  if (lists.isError) return <ErrorBox error={lists.error} title="Could not load option lists" />;

  const channelCodes = (channels.data ?? []).map((c) => c.code);
  const updateValue = (i: number, patch: Partial<OptionValue>) =>
    setDraft((d) => (d ? { ...d, values: d.values.map((v, j) => (j === i ? { ...v, ...patch } : v)) } : d));
  const setMapping = (i: number, ch: string, val: string) =>
    setDraft((d) => {
      if (!d) return d;
      const values = d.values.map((v, j) => {
        if (j !== i) return v;
        const m = { ...v.channel_mappings };
        if (val) m[ch] = val;
        else delete m[ch];
        return { ...v, channel_mappings: m };
      });
      return { ...d, values };
    });

  return (
    <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 16 }}>
      <div className="panel">
        <div className="panel-header">
          <h3>Lists</h3>
          <button
            className="small"
            onClick={() => {
              setCreating(true);
              setSelected("");
              setDraft({ code: "", label: "", kind: "option", values: [] });
            }}
          >
            New
          </button>
        </div>
        <div className="panel-body flush" style={{ maxHeight: "70vh", overflow: "auto" }}>
          {lists.data!.length === 0 && <Empty title="No option lists">Create one for each select attribute.</Empty>}
          {lists.data!.map((l) => (
            <div
              key={l.code}
              className="menu-item"
              style={{ cursor: "pointer", background: l.code === selected ? "var(--teal-light)" : undefined }}
              onClick={() => {
                setCreating(false);
                setSelected(l.code);
              }}
            >
              <span>
                {l.label}
                <div className="faint mono small">{l.code}</div>
              </span>
              <span className="row" style={{ gap: 4 }}>
                {l.kind === "size_scale" && <Badge color="purple" title={`Size group ${l.size_group ?? ""}`}>size scale</Badge>}
                <span className="faint small">{l.values.length}</span>
              </span>
            </div>
          ))}
        </div>
      </div>

      <div>
        {!draft ? (
          <Empty title="Choose an option list">Select a list on the left to edit its values and channel mappings, or create a new one.</Empty>
        ) : (
          <div className="panel">
            <div className="panel-header">
              <div className="row">
                <input className="mono" placeholder="code" value={draft.code} disabled={!creating} onChange={(e) => setDraft({ ...draft, code: e.target.value })} style={{ width: 160 }} />
                <input placeholder="Label" value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} />
                <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as OptionList["kind"] })}>
                  <option value="option">option list</option>
                  <option value="size_scale">size scale</option>
                </select>
                {draft.kind === "size_scale" && (
                  <input placeholder="size_group (e.g. alpha, numeric, cup)" value={draft.size_group ?? ""} onChange={(e) => setDraft({ ...draft, size_group: e.target.value || null })} />
                )}
              </div>
              <div className="row">
                <button
                  className="small"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      values: [...draft.values, { code: "", label: "", sort_order: (draft.values[draft.values.length - 1]?.sort_order ?? 0) + 10, channel_mappings: {} }],
                    })
                  }
                >
                  Add value
                </button>
                <button
                  className="primary small"
                  disabled={save.isPending || !draft.code || !draft.label || draft.values.some((v) => !v.code)}
                  onClick={() => save.mutate(draft)}
                >
                  {save.isPending ? "Saving" : "Save list"}
                </button>
              </div>
            </div>
            <div className="panel-body flush" style={{ overflow: "auto" }}>
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Label</th>
                    <th>Sort</th>
                    {channelCodes.map((c) => (
                      <th key={c} title={`Value sent to ${c}`}>
                        {c} mapping
                      </th>
                    ))}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {draft.values
                    .map((v, i) => ({ v, i }))
                    .sort((a, b) => a.v.sort_order - b.v.sort_order)
                    .map(({ v, i }) => (
                      <tr key={i}>
                        <td>
                          <input className="mono" value={v.code} onChange={(e) => updateValue(i, { code: e.target.value })} />
                        </td>
                        <td>
                          <input value={v.label} onChange={(e) => updateValue(i, { label: e.target.value })} />
                        </td>
                        <td style={{ width: 70 }}>
                          <input type="number" value={v.sort_order} onChange={(e) => updateValue(i, { sort_order: Number(e.target.value) })} />
                        </td>
                        {channelCodes.map((c) => (
                          <td key={c}>
                            <input value={v.channel_mappings[c] ?? ""} onChange={(e) => setMapping(i, c, e.target.value)} placeholder="same" />
                          </td>
                        ))}
                        <td>
                          <button className="small danger" onClick={() => setDraft({ ...draft, values: draft.values.filter((_, j) => j !== i) })}>
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
              {draft.values.length === 0 && <div className="empty">No values yet. Add the first value.</div>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
