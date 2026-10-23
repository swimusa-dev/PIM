// GOV-02: Field-level history with filter by attribute and user, and a Restore button per row.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AttributeDefinition, OptionList } from "../api/types";
import { Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { displayValue, formatDate } from "../lib/format";

const PAGE_SIZE = 50;

export function HistoryTab({
  entityId,
  attributes,
  optionLists,
}: {
  entityId: string;
  attributes: AttributeDefinition[];
  optionLists: Record<string, OptionList>;
}) {
  const [attributeCode, setAttributeCode] = useState("");
  const [userInput, setUserInput] = useState("");
  const [user, setUser] = useState("");
  const [page, setPage] = useState(1);
  const qc = useQueryClient();
  const toast = useToast();
  const attrByCode = new Map(attributes.map((a) => [a.code, a]));

  const q = useQuery({
    queryKey: ["product", entityId, "history", attributeCode, user, page],
    queryFn: () => api.products.history(entityId, { attribute_code: attributeCode || undefined, user: user || undefined, page }),
  });

  const restore = useMutation({
    mutationFn: (historyId: string) => api.products.restore(entityId, historyId),
    onSuccess: (res) => {
      const r = res?.results?.[0];
      toast(r?.outcome === "draft" ? "Restored as a draft, pending approval" : "Value restored", "ok");
      qc.invalidateQueries({ queryKey: ["product", entityId] });
      qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
    },
    onError: (e) => toast(`Restore failed: ${(e as Error).message}`, "error"),
  });

  return (
    <div className="stack">
      <div className="row">
        <select
          value={attributeCode}
          onChange={(e) => {
            setAttributeCode(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All attributes</option>
          {attributes
            .slice()
            .sort((a, b) => a.label.localeCompare(b.label))
            .map((a) => (
              <option key={a.code} value={a.code}>
                {a.label}
              </option>
            ))}
        </select>
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            setUser(userInput.trim());
            setPage(1);
          }}
        >
          <input placeholder="Filter by user email" value={userInput} onChange={(e) => setUserInput(e.target.value)} />
          <button type="submit">Apply</button>
        </form>
      </div>
      {q.isLoading && <Spinner label="Loading history" />}
      {q.isError && <ErrorBox error={q.error} title="Could not load history" />}
      {q.data && q.data.rows.length === 0 && (
        <Empty title="No history">{attributeCode || user ? "No changes match the filters." : "No value on this product has changed yet."}</Empty>
      )}
      {q.data && q.data.rows.length > 0 && (
        <div className="panel">
          <table className="data compact">
            <thead>
              <tr>
                <th>When</th>
                <th>Attribute</th>
                <th>Channel</th>
                <th>Old value</th>
                <th>New value</th>
                <th>Source</th>
                <th>By</th>
                <th>Reason</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((h) => {
                const a = attrByCode.get(h.attribute_code);
                return (
                  <tr key={h.id}>
                    <td className="nowrap">{formatDate(h.set_at)}</td>
                    <td>
                      {a?.label ?? h.attribute_code}
                      <div className="faint mono small">{h.attribute_code}</div>
                    </td>
                    <td>{h.channel_code ?? <span className="faint">global</span>}</td>
                    <td className="pre" style={{ maxWidth: 240 }}>
                      {displayValue(h.old_value, a, optionLists) || <span className="faint">(empty)</span>}
                    </td>
                    <td className="pre" style={{ maxWidth: 240 }}>
                      {displayValue(h.new_value, a, optionLists) || <span className="faint">(empty)</span>}
                    </td>
                    <td>{h.source_type}</td>
                    <td>{h.set_by}</td>
                    <td className="muted small">
                      {h.reason ?? ""}
                      {h.change_set_id && <div className="faint mono">set {h.change_set_id}</div>}
                    </td>
                    <td>
                      <button
                        className="small"
                        disabled={restore.isPending}
                        onClick={() => restore.mutate(h.id)}
                        title="Restore the old value of this single attribute"
                      >
                        Restore
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="grid-status">
            <span>{q.data.total} changes</span>
            <span className="row">
              <button className="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </button>
              <span>
                Page {page} of {Math.max(1, Math.ceil(q.data.total / PAGE_SIZE))}
              </span>
              <button className="small" disabled={page * PAGE_SIZE >= q.data.total} onClick={() => setPage((p) => p + 1)}>
                Next
              </button>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
