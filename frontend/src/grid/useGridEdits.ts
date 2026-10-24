// DM-03: Edit batching, outcome tracking and undo for the product grid.
// Edits call PUT /api/products/{id}/values grouped per entity; the previous values are kept so
// Ctrl+Z can re-send them (undo of the last edit batch).

import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../api/client";
import type { EditOutcome, ProductQueryResult, ProductRow, ValueCell } from "../api/types";

export interface EditSpec {
  entity_id: string;
  code: string;
  value: unknown;
  prev: unknown;
}

export interface CellStatus {
  outcome: EditOutcome | "saving" | "error";
  message?: string;
}

export const statusKey = (entityId: string, code: string) => `${entityId}\u0000${code}`;

export function useGridEdits(queryKey: unknown[], userEmail: string | undefined, channelCode?: string | null) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<Map<string, CellStatus>>(new Map());
  const undoStack = useRef<EditSpec[][]>([]);
  const [canUndo, setCanUndo] = useState(false);

  const setStatuses = useCallback((entries: [string, CellStatus | null][]) => {
    setStatus((prev) => {
      const next = new Map(prev);
      for (const [k, v] of entries) {
        if (v === null) next.delete(k);
        else next.set(k, v);
      }
      return next;
    });
  }, []);

  /** Patch the cached rows so the grid reflects the edit without a refetch. */
  const patchCache = useCallback(
    (entityId: string, code: string, value: unknown, outcome: EditOutcome) => {
      qc.setQueryData<ProductQueryResult>(queryKey, (old) => {
        if (!old) return old;
        const rows = old.rows.map((r): ProductRow => {
          if (r.entity_id !== entityId) return r;
          const prev: ValueCell = r.values[code] ?? {
            value: null,
            source_type: "user",
            ai_generated: false,
            approval_state: "approved",
            version: 0,
            read_only: false,
          };
          const now = new Date().toISOString();
          const next: ValueCell =
            outcome === "approved"
              ? {
                  ...prev,
                  value,
                  not_applicable: false,
                  source_type: "user",
                  set_by: userEmail ?? prev.set_by,
                  set_at: now,
                  ai_generated: false,
                  approval_state: "approved",
                  is_default: false,
                  draft: null,
                  version: prev.version + 1,
                }
              : outcome === "draft"
                ? { ...prev, draft: { value, set_by: userEmail ?? "", set_at: now } }
                : prev;
          return { ...r, values: { ...r.values, [code]: next } };
        });
        return { ...old, rows };
      });
    },
    [qc, queryKey, userEmail],
  );

  const send = useCallback(
    async (edits: EditSpec[], recordUndo: boolean) => {
      if (edits.length === 0) return;
      const byEntity = new Map<string, EditSpec[]>();
      for (const e of edits) {
        const arr = byEntity.get(e.entity_id) ?? [];
        arr.push(e);
        byEntity.set(e.entity_id, arr);
      }
      setStatuses(edits.map((e) => [statusKey(e.entity_id, e.code), { outcome: "saving" }]));
      const applied: EditSpec[] = [];
      await Promise.all(
        Array.from(byEntity.entries()).map(async ([entityId, list]) => {
          const values: Record<string, unknown> = {};
          for (const e of list) values[e.code] = e.value;
          try {
            const res = await api.products.setValues(entityId, values, channelCode);
            const results = new Map(res.results.map((r) => [r.attribute_code, r]));
            const entries: [string, CellStatus | null][] = [];
            for (const e of list) {
              const r = results.get(e.code);
              const outcome: EditOutcome = r?.outcome ?? "approved";
              patchCache(entityId, e.code, e.value, outcome);
              if (outcome === "approved") {
                applied.push(e);
                entries.push([statusKey(entityId, e.code), null]);
              } else {
                if (outcome === "draft") applied.push(e);
                entries.push([statusKey(entityId, e.code), { outcome, message: r?.message }]);
              }
            }
            setStatuses(entries);
          } catch (err) {
            setStatuses(list.map((e) => [statusKey(e.entity_id, e.code), { outcome: "error", message: errorMessage(err) }]));
          }
        }),
      );
      if (recordUndo && applied.length > 0) {
        undoStack.current.push(applied);
        if (undoStack.current.length > 50) undoStack.current.shift();
        setCanUndo(true);
      }
      // Refresh completeness and readiness in the background.
      qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
    },
    [channelCode, patchCache, qc, setStatuses],
  );

  const applyEdits = useCallback((edits: EditSpec[]) => send(edits, true), [send]);

  const undo = useCallback(async () => {
    const batch = undoStack.current.pop();
    setCanUndo(undoStack.current.length > 0);
    if (!batch) return;
    await send(
      batch.map((e) => ({ entity_id: e.entity_id, code: e.code, value: e.prev, prev: e.value })),
      false,
    );
  }, [send]);

  const markRejected = useCallback(
    (entityId: string, code: string, message: string) =>
      setStatuses([[statusKey(entityId, code), { outcome: "rejected", message }]]),
    [setStatuses],
  );

  const clearStatus = useCallback((entityId: string, code: string) => setStatuses([[statusKey(entityId, code), null]]), [setStatuses]);

  return { status, applyEdits, undo, canUndo, markRejected, clearStatus };
}
