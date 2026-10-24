// DM-01, DM-02, DM-03, DM-04, EXP-03: Product grid with level switcher, search, faceted filters, column chooser,
// multi-column sort, server-side paging (100 rows), virtualized rows, saved views, spreadsheet-style
// in-grid editing (navigation, copy/paste of TSV ranges, fill-down, undo), row selection and bulk actions.

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ClipboardEvent } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { api } from "../api/client";
import { canEdit, useAttributes, useChannels, useGroups, useMe, useOptionLists } from "../api/hooks";
import type { Level, OptionList, ProductQuery, ProductRow, QueryFilter, QuerySort, SavedView, ViewDefinition } from "../api/types";
import { AiBadge, ErrorBox, LifecycleBadge, LockIcon, PercentPill, Provenance, ReadinessPill, Spinner, Empty, useToast } from "../components/Common";
import { ValueEditor } from "../components/ValueEditor";
import { buildFieldCatalog, coreValue, defaultColumns, type FieldDef } from "../grid/fields";
import { FilterBuilder, describeFilter } from "../grid/FilterBuilder";
import { ColumnChooser } from "../grid/ColumnChooser";
import { ViewsMenu } from "../grid/ViewsMenu";
import { BulkActionsDialog } from "../grid/BulkActionsDialog";
import { statusKey, useGridEdits, type EditSpec } from "../grid/useGridEdits";
import { cellValue, clipboardValue, displayValue, LEVEL_LABEL } from "../lib/format";
import { parseInput } from "../lib/validation";
import { fromTsv, toTsv } from "../lib/tsv";

const PAGE_SIZE = 100;
const ROW_HEIGHT = 30;
const LABEL_COL_WIDTH = 220;
const LS_LEVEL = "pim.grid.level";

interface CellPos {
  r: number;
  c: number;
}

export function ProductGridPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const me = useMe();
  const attrs = useAttributes();
  const groups = useGroups();
  const channels = useChannels();
  const optionLists = useOptionLists();

  const [level, setLevel] = useState<Level>(() => {
    try {
      const v = localStorage.getItem(LS_LEVEL);
      return v === "style" || v === "style_color" || v === "sku" ? v : "style_color";
    } catch {
      return "style_color";
    }
  });
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<QueryFilter[]>([]);
  const [showFilters, setShowFilters] = useState(false);
  const [columns, setColumns] = useState<string[] | null>(null);
  const [sort, setSort] = useState<QuerySort[]>([]);
  const [page, setPage] = useState(1);
  const [activeView, setActiveView] = useState<SavedView | null>(null);
  // DM-04: row selection for bulk actions (entity ids, kept across pages until the level changes).
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showBulk, setShowBulk] = useState(false);

  const listByCode = useMemo(() => {
    const m: Record<string, OptionList> = {};
    for (const l of optionLists.data ?? []) m[l.code] = l;
    return m;
  }, [optionLists.data]);
  const groupReadOnly = useMemo(() => new Set((groups.data ?? []).filter((g) => g.read_only).map((g) => g.code)), [groups.data]);

  const fields = useMemo(
    () => buildFieldCatalog(level, attrs.data ?? [], groups.data ?? [], channels.data ?? []),
    [level, attrs.data, groups.data, channels.data],
  );
  const fieldByKey = useMemo(() => new Map(fields.map((f) => [f.key, f])), [fields]);

  const effectiveColumns = useMemo(() => {
    const base = columns ?? defaultColumns(level, channels.data ?? []);
    // Keep only columns that exist at this level; a view saved at another level may reference others.
    return base.filter((k) => fieldByKey.has(k));
  }, [columns, level, channels.data, fieldByKey]);
  const visibleFields = useMemo(
    () => effectiveColumns.map((k) => fieldByKey.get(k)!).filter(Boolean),
    [effectiveColumns, fieldByKey],
  );

  // Apply the user's default view for this level once views are known (DM-02).
  const views = useQuery({ queryKey: ["views", level], queryFn: () => api.views.list(level) });
  const appliedDefaultFor = useRef<string | null>(null);
  useEffect(() => {
    if (!views.data || appliedDefaultFor.current === level) return;
    appliedDefaultFor.current = level;
    const def = views.data.find((v) => v.is_default && v.level === level);
    if (def && !activeView) applyView(def);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [views.data, level]);

  const applyView = (v: SavedView) => {
    setActiveView(v);
    setFilters(v.definition.filters ?? []);
    setColumns(v.definition.columns?.length ? v.definition.columns : null);
    setSort(v.definition.sort ?? []);
    setSearch(v.definition.search ?? "");
    setSearchInput(v.definition.search ?? "");
    if (v.level !== level) changeLevel(v.level, false);
    setPage(1);
  };
  const clearView = () => {
    setActiveView(null);
    setFilters([]);
    setColumns(null);
    setSort([]);
    setSearch("");
    setSearchInput("");
    setPage(1);
  };
  const changeLevel = (l: Level, resetView = true) => {
    setLevel(l);
    try {
      localStorage.setItem(LS_LEVEL, l);
    } catch {
      // ignore storage failures
    }
    if (resetView) {
      setActiveView(null);
      setColumns(null);
      appliedDefaultFor.current = null;
    }
    setPage(1);
    setActive(null);
    setAnchor(null);
    setSelected(new Set());
  };

  const currentDefinition: ViewDefinition = useMemo(
    () => ({ filters, columns: effectiveColumns, sort, search }),
    [filters, effectiveColumns, sort, search],
  );

  // Drop filters that still need a value so a half-built filter does not hit the server.
  const activeFilters = useMemo(
    () =>
      filters.filter((f) => {
        if (f.op === "empty" || f.op === "not_empty") return true;
        if (Array.isArray(f.value)) return f.value.length > 0;
        return f.value !== "" && f.value !== null && f.value !== undefined;
      }),
    [filters],
  );

  const queryBody: ProductQuery = useMemo(
    () => ({
      level,
      page,
      page_size: PAGE_SIZE,
      sort,
      filters: activeFilters,
      search,
      columns: effectiveColumns,
      view_id: activeView?.id,
    }),
    [level, page, sort, activeFilters, search, effectiveColumns, activeView?.id],
  );
  const queryKey = useMemo(() => ["products", "query", queryBody], [queryBody]);
  const q = useQuery({
    queryKey,
    queryFn: () => api.products.query(queryBody),
    placeholderData: keepPreviousData,
    enabled: attrs.isSuccess && groups.isSuccess && channels.isSuccess,
  });
  const rows = useMemo(() => q.data?.rows ?? [], [q.data]);
  const total = q.data?.total ?? 0;
  const pageAllSelected = rows.length > 0 && rows.every((r) => selected.has(r.entity_id));
  const toggleSelected = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const togglePage = () =>
    setSelected((s) => {
      const n = new Set(s);
      if (pageAllSelected) rows.forEach((r) => n.delete(r.entity_id));
      else rows.forEach((r) => n.add(r.entity_id));
      return n;
    });

  // ---- Editing state (DM-03) ----
  const edits = useGridEdits(queryKey, me.data?.email);
  const [anchor, setAnchor] = useState<CellPos | null>(null);
  const [active, setActive] = useState<CellPos | null>(null);
  const [editing, setEditing] = useState<(CellPos & { initialText?: string }) | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Column 0 is the product label column; data columns start at 1.
  const colCount = visibleFields.length + 1;
  const fieldAt = useCallback((c: number): FieldDef | undefined => (c >= 1 ? visibleFields[c - 1] : undefined), [visibleFields]);

  const isEditable = useCallback(
    (row: ProductRow, field: FieldDef | undefined): boolean => {
      if (!field || field.kind !== "attr" || !field.attr) return false;
      const a = field.attr;
      if (a.status === "deprecated") return false;
      if (a.level !== row.level) return false; // strict ownership (DM-01)
      if (a.source_of_truth === "erp") return false;
      if (groupReadOnly.has(a.group_code)) return false;
      const cell = row.values[a.code];
      if (cell?.read_only) return false;
      return canEdit(me.data, a);
    },
    [groupReadOnly, me.data],
  );

  const range = useMemo(() => {
    if (!active) return null;
    const a = anchor ?? active;
    return {
      r1: Math.min(a.r, active.r),
      r2: Math.max(a.r, active.r),
      c1: Math.min(a.c, active.c),
      c2: Math.max(a.c, active.c),
    };
  }, [anchor, active]);

  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });

  const moveActive = useCallback(
    (dr: number, dc: number, extend = false) => {
      setActive((cur) => {
        const base = cur ?? { r: 0, c: 1 };
        const r = Math.max(0, Math.min(rows.length - 1, base.r + dr));
        const c = Math.max(0, Math.min(colCount - 1, base.c + dc));
        const next = { r, c };
        if (!extend) setAnchor(next);
        else if (!anchor) setAnchor(base);
        rowVirtualizer.scrollToIndex(r, { align: "auto" });
        requestAnimationFrame(() => {
          scrollRef.current?.querySelector<HTMLElement>(`td[data-r="${r}"][data-c="${c}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
        });
        return next;
      });
    },
    [rows.length, colCount, anchor, rowVirtualizer],
  );

  const startEdit = useCallback(
    (pos: CellPos, initialText?: string) => {
      const row = rows[pos.r];
      const field = fieldAt(pos.c);
      if (!row || !isEditable(row, field)) return;
      setEditing({ ...pos, initialText });
      edits.clearStatus(row.entity_id, field!.attr!.code);
    },
    [rows, fieldAt, isEditable, edits],
  );

  const commitEdit = useCallback(
    (pos: CellPos, value: unknown) => {
      const row = rows[pos.r];
      const field = fieldAt(pos.c);
      if (!row || !field?.attr) return;
      const prev = cellValue(row.values[field.attr.code]);
      setEditing(null);
      if (JSON.stringify(prev ?? null) === JSON.stringify(value ?? null)) return;
      void edits.applyEdits([{ entity_id: row.entity_id, code: field.attr.code, value, prev }]);
    },
    [rows, fieldAt, edits],
  );

  const afterEditNavigate = useCallback(
    (key: "Tab" | "ShiftTab" | "Enter" | "ShiftEnter" | "ArrowUp" | "ArrowDown") => {
      scrollRef.current?.focus();
      if (key === "Tab") moveActive(0, 1);
      else if (key === "ShiftTab") moveActive(0, -1);
      else if (key === "Enter" || key === "ArrowDown") moveActive(1, 0);
      else if (key === "ShiftEnter" || key === "ArrowUp") moveActive(-1, 0);
    },
    [moveActive],
  );

  const copyRange = useCallback((): string | null => {
    if (!range) return null;
    const block: string[][] = [];
    for (let r = range.r1; r <= range.r2; r++) {
      const row = rows[r];
      if (!row) continue;
      const line: string[] = [];
      for (let c = range.c1; c <= range.c2; c++) {
        if (c === 0) {
          line.push(row.label);
          continue;
        }
        const f = fieldAt(c)!;
        if (f.kind === "core") line.push(coreValue(row, f.key));
        else if (f.kind === "completeness") line.push(String(row.completeness[f.channelCode!] ?? ""));
        else if (f.kind === "readiness") {
          const rd = row.readiness[f.channelCode!];
          line.push(!rd ? "" : !rd.eligible ? "Ineligible" : rd.ready ? "Ready" : "Not ready");
        } else line.push(clipboardValue(cellValue(row.values[f.attr!.code])));
      }
      block.push(line);
    }
    return toTsv(block);
  }, [range, rows, fieldAt]);

  const pasteBlock = useCallback(
    (text: string) => {
      if (!active) return;
      const block = fromTsv(text);
      if (block.length === 0) return;
      const specs: EditSpec[] = [];
      let skipped = 0;
      let invalid = 0;
      // A single value pasted over a multi-cell selection fills the selection (Excel behavior).
      const single = block.length === 1 && block[0].length === 1;
      const r1 = active.r;
      const c1 = active.c;
      const r2 = single && range ? range.r2 : r1 + block.length - 1;
      const c2 = single && range ? range.c2 : c1 + Math.max(...block.map((b) => b.length)) - 1;
      const rStart = single && range ? range.r1 : r1;
      const cStart = single && range ? range.c1 : c1;
      for (let r = rStart; r <= r2; r++) {
        const row = rows[r];
        if (!row) break;
        for (let c = cStart; c <= c2; c++) {
          const text = single ? block[0][0] : (block[r - r1]?.[c - c1] ?? "");
          const field = fieldAt(c);
          if (!isEditable(row, field)) {
            skipped += 1;
            continue;
          }
          const a = field!.attr!;
          const parsed = parseInput(text, a, a.option_list_code ? listByCode[a.option_list_code] : undefined);
          if (!parsed.ok) {
            invalid += 1;
            edits.markRejected(row.entity_id, a.code, parsed.error ?? "Invalid value");
            continue;
          }
          const prev = cellValue(row.values[a.code]);
          if (JSON.stringify(prev ?? null) === JSON.stringify(parsed.value ?? null)) continue;
          specs.push({ entity_id: row.entity_id, code: a.code, value: parsed.value, prev });
        }
      }
      setAnchor({ r: rStart, c: cStart });
      setActive({ r: Math.min(r2, rows.length - 1), c: Math.min(c2, colCount - 1) });
      if (specs.length) void edits.applyEdits(specs);
      const notes: string[] = [];
      if (specs.length) notes.push(`${specs.length} cell${specs.length === 1 ? "" : "s"} updated`);
      if (skipped) notes.push(`${skipped} read-only skipped`);
      if (invalid) notes.push(`${invalid} invalid`);
      if (notes.length) toast(`Paste: ${notes.join(", ")}`, invalid ? "warn" : "ok");
    },
    [active, range, rows, fieldAt, isEditable, listByCode, edits, colCount, toast],
  );

  const fillDown = useCallback(() => {
    if (!range || range.r2 === range.r1) return;
    const specs: EditSpec[] = [];
    for (let c = range.c1; c <= range.c2; c++) {
      const field = fieldAt(c);
      if (!field?.attr) continue;
      const top = rows[range.r1];
      if (!top) continue;
      const value = cellValue(top.values[field.attr.code]);
      for (let r = range.r1 + 1; r <= range.r2; r++) {
        const row = rows[r];
        if (!row || !isEditable(row, field)) continue;
        const prev = cellValue(row.values[field.attr.code]);
        if (JSON.stringify(prev ?? null) === JSON.stringify(value ?? null)) continue;
        specs.push({ entity_id: row.entity_id, code: field.attr.code, value, prev });
      }
    }
    if (specs.length) void edits.applyEdits(specs);
    else toast("Nothing to fill: the cells below are read-only or already equal", "warn");
  }, [range, rows, fieldAt, isEditable, edits, toast]);

  const clearSelection = useCallback(() => {
    if (!range) return;
    const specs: EditSpec[] = [];
    for (let r = range.r1; r <= range.r2; r++) {
      const row = rows[r];
      if (!row) continue;
      for (let c = range.c1; c <= range.c2; c++) {
        const field = fieldAt(c);
        if (!isEditable(row, field)) continue;
        const prev = cellValue(row.values[field!.attr!.code]);
        if (prev === null || prev === undefined) continue;
        specs.push({ entity_id: row.entity_id, code: field!.attr!.code, value: null, prev });
      }
    }
    if (specs.length) void edits.applyEdits(specs);
  }, [range, rows, fieldAt, isEditable, edits]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (editing) return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && (e.key === "c" || e.key === "C")) {
      const tsv = copyRange();
      if (tsv !== null && navigator.clipboard?.writeText) {
        e.preventDefault();
        void navigator.clipboard.writeText(tsv).then(() => toast("Copied", "ok"));
      }
      return;
    }
    if (ctrl && (e.key === "d" || e.key === "D")) {
      e.preventDefault();
      fillDown();
      return;
    }
    if (ctrl && (e.key === "z" || e.key === "Z")) {
      e.preventDefault();
      if (edits.canUndo) void edits.undo().then(() => toast("Undid last edit batch", "ok"));
      return;
    }
    if (ctrl) return; // Ctrl+V arrives as a paste event
    switch (e.key) {
      case "ArrowUp":
        e.preventDefault();
        moveActive(-1, 0, e.shiftKey);
        return;
      case "ArrowDown":
        e.preventDefault();
        moveActive(1, 0, e.shiftKey);
        return;
      case "ArrowLeft":
        e.preventDefault();
        moveActive(0, -1, e.shiftKey);
        return;
      case "ArrowRight":
        e.preventDefault();
        moveActive(0, 1, e.shiftKey);
        return;
      case "Tab":
        e.preventDefault();
        moveActive(0, e.shiftKey ? -1 : 1);
        return;
      case "Enter":
      case "F2":
        e.preventDefault();
        if (active) startEdit(active);
        return;
      case "Escape":
        if (active) setAnchor(active);
        return;
      case "Delete":
      case "Backspace":
        e.preventDefault();
        clearSelection();
        return;
      case "PageDown":
        e.preventDefault();
        moveActive(20, 0, e.shiftKey);
        return;
      case "PageUp":
        e.preventDefault();
        moveActive(-20, 0, e.shiftKey);
        return;
      default:
        if (e.key.length === 1 && active && !e.altKey) {
          const row = rows[active.r];
          const field = fieldAt(active.c);
          if (row && isEditable(row, field) && field!.attr!.data_type !== "boolean" && field!.attr!.data_type !== "single_select" && field!.attr!.data_type !== "multi_select") {
            e.preventDefault();
            startEdit(active, e.key);
          }
        }
    }
  };

  const onPaste = (e: ClipboardEvent<HTMLDivElement>) => {
    if (editing) return;
    const text = e.clipboardData.getData("text/plain");
    if (!text) return;
    e.preventDefault();
    pasteBlock(text);
  };
  const onCopy = (e: ClipboardEvent<HTMLDivElement>) => {
    if (editing) return;
    const tsv = copyRange();
    if (tsv === null) return;
    e.clipboardData.setData("text/plain", tsv);
    e.preventDefault();
  };

  // ---- Sorting ----
  const toggleSort = (key: string, multi: boolean) => {
    setPage(1);
    setSort((prev) => {
      const ix = prev.findIndex((s) => s.field === key);
      const cur = ix >= 0 ? prev[ix] : null;
      const nextDir: "asc" | "desc" | null = !cur ? "asc" : cur.dir === "asc" ? "desc" : null;
      const others = multi ? prev.filter((s) => s.field !== key) : [];
      if (!nextDir) return others;
      const entry = { field: key, dir: nextDir };
      if (multi && ix >= 0) {
        const copy = prev.slice();
        copy[ix] = entry;
        return copy;
      }
      return [...others, entry];
    });
  };

  // ---- react-table column defs (header rendering, sizing) ----
  const tableColumns = useMemo<ColumnDef<ProductRow>[]>(
    () => [
      { id: "__label", header: `Product (${LEVEL_LABEL[level]})`, size: LABEL_COL_WIDTH },
      ...visibleFields.map<ColumnDef<ProductRow>>((f) => ({ id: f.key, header: f.label, size: f.width })),
    ],
    [visibleFields, level],
  );
  const table = useReactTable({
    data: rows,
    columns: tableColumns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
    manualFiltering: true,
  });
  const tableWidth = tableColumns.reduce((w, c) => w + (c.size ?? 150), 0);
  const virtualRows = rowVirtualizer.getVirtualItems();
  const paddingTop = virtualRows.length > 0 ? virtualRows[0].start : 0;
  const paddingBottom = virtualRows.length > 0 ? rowVirtualizer.getTotalSize() - virtualRows[virtualRows.length - 1].end : 0;

  const metaError = attrs.error ?? groups.error ?? channels.error;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const renderCell = (row: ProductRow, field: FieldDef, pos: CellPos) => {
    if (field.kind === "core") {
      const v = coreValue(row, field.key);
      if (field.key === "lifecycle_status") return <LifecycleBadge status={v} />;
      return <span className={field.key === "style_number" || field.key === "sku" || field.key === "upc" ? "mono" : ""}>{v}</span>;
    }
    if (field.kind === "completeness") return <PercentPill value={row.completeness[field.channelCode!]} />;
    if (field.kind === "readiness") return <ReadinessPill readiness={row.readiness[field.channelCode!]} />;
    const a = field.attr!;
    const cell = row.values[a.code];
    const isEditingHere = editing && editing.r === pos.r && editing.c === pos.c;
    if (isEditingHere) {
      return (
        <ValueEditor
          attr={a}
          optionList={a.option_list_code ? listByCode[a.option_list_code] : undefined}
          value={cellValue(cell)}
          autoFocus
          compact
          initialText={editing.initialText}
          onCommit={(v) => commitEdit(pos, v)}
          onCancel={() => {
            setEditing(null);
            scrollRef.current?.focus();
          }}
          onNavigate={afterEditNavigate}
        />
      );
    }
    const st = edits.status.get(statusKey(row.entity_id, a.code));
    const shown = cell?.draft ? cell.draft.value : cellValue(cell);
    const text = cell?.not_applicable ? "N/A" : displayValue(shown, a, listByCode);
    return (
      <Provenance cell={cell}>
        <span className={cell?.is_default ? "is-default" : ""}>{text}</span>
        {cell?.ai_generated && <AiBadge />}
        {(cell?.draft || st?.outcome === "draft") && (
          <span className="badge amber cell-draft" title="Draft, pending approval">
            Draft, pending approval
          </span>
        )}
        {st?.outcome === "saving" && <span className="faint small"> saving</span>}
        {(st?.outcome === "rejected" || st?.outcome === "error") && (
          <span className="badge red cell-draft" title={st.message}>
            {st.message ? st.message.slice(0, 60) : "Rejected"}
          </span>
        )}
        <LockIcon cell={cell} />
      </Provenance>
    );
  };

  return (
    <div className="grid-page">
      <div className="grid-toolbar">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="row">
            <div className="seg" role="tablist" aria-label="Hierarchy level">
              {(["style", "style_color", "sku"] as Level[]).map((l) => (
                <button key={l} className={l === level ? "active" : ""} onClick={() => changeLevel(l)}>
                  {LEVEL_LABEL[l]}
                </button>
              ))}
            </div>
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                setSearch(searchInput.trim());
                setPage(1);
              }}
            >
              <input
                placeholder="Search style number, name, UPC, any text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                style={{ width: 300 }}
              />
              <button type="submit">Search</button>
            </form>
            <button onClick={() => setShowFilters((s) => !s)}>
              Filters {activeFilters.length > 0 ? `(${activeFilters.length})` : ""}
            </button>
            <ColumnChooser fields={fields} columns={effectiveColumns} onChange={(c) => setColumns(c)} />
            {sort.length > 0 && (
              <button className="link small" onClick={() => setSort([])}>
                Clear sort ({sort.length})
              </button>
            )}
          </div>
          <div className="row">
            <button
              disabled={selected.size === 0 && !activeView}
              title={selected.size > 0 ? `${selected.size} rows selected` : activeView ? `Apply to the whole view "${activeView.name}"` : "Select rows or apply a saved view first"}
              onClick={() => setShowBulk(true)}
            >
              Bulk actions{selected.size > 0 ? ` (${selected.size})` : activeView ? " (whole view)" : ""}
            </button>
            {selected.size > 0 && (
              <button className="link small" onClick={() => setSelected(new Set())}>
                Clear selection
              </button>
            )}
            <ViewsMenu level={level} current={currentDefinition} activeView={activeView} onApply={applyView} onClear={clearView} />
          </div>
        </div>
        {showFilters && (
          <div className="panel" style={{ padding: 10 }}>
            <FilterBuilder
              filters={filters}
              onChange={(f) => {
                setFilters(f);
                setPage(1);
              }}
              fields={fields}
              optionLists={listByCode}
            />
          </div>
        )}
        {!showFilters && activeFilters.length > 0 && (
          <div className="chips">
            {activeFilters.map((f, i) => (
              <span key={i} className="badge teal">
                {describeFilter(f, fields)}
              </span>
            ))}
          </div>
        )}
      </div>

      {metaError && <ErrorBox error={metaError} title="Could not load attribute metadata" />}
      {q.isError && <ErrorBox error={q.error} title="Could not load products" />}

      <div
        className="grid-scroll"
        ref={scrollRef}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        onCopy={onCopy}
        aria-label="Product grid"
      >
        {(q.isLoading || (!q.data && (attrs.isLoading || groups.isLoading || channels.isLoading))) && <Spinner label="Loading products" />}
        {q.data && rows.length === 0 && (
          <Empty title="No products match">
            {search || activeFilters.length
              ? "Change the search or remove a filter. Saved views keep their filters until you clear them."
              : "No entities exist at this level yet. Run the Style Master ingest from Admin, Telemetry."}
          </Empty>
        )}
        {rows.length > 0 && (
          <table className="grid-table" style={{ width: tableWidth }}>
            <colgroup>
              {tableColumns.map((c) => (
                <col key={c.id} style={{ width: c.size }} />
              ))}
            </colgroup>
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((h, ci) => {
                    const key = h.column.id;
                    const sIx = sort.findIndex((s) => s.field === key);
                    const field = fieldByKey.get(key);
                    return (
                      <th
                        key={h.id}
                        className={ci === 0 ? "sticky-col" : ""}
                        title={field?.attr ? `${field.attr.code} (${field.attr.data_type}, ${field.attr.level}, ${field.groupLabel})` : key}
                        onClick={(e) => {
                          if (ci === 0 || !field?.sortable) return;
                          toggleSort(key, e.shiftKey);
                        }}
                      >
                        {ci === 0 && (
                          <input
                            type="checkbox"
                            className="row-select"
                            checked={pageAllSelected}
                            onChange={togglePage}
                            onClick={(e) => e.stopPropagation()}
                            aria-label="Select all rows on this page"
                            title="Select all rows on this page"
                          />
                        )}
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {sIx >= 0 && (
                          <span className="sort-ix">
                            {sort[sIx].dir === "asc" ? "▲" : "▼"}
                            {sort.length > 1 ? sIx + 1 : ""}
                          </span>
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {paddingTop > 0 && (
                <tr>
                  <td style={{ height: paddingTop, border: "none" }} colSpan={colCount} />
                </tr>
              )}
              {virtualRows.map((vr) => {
                const row = rows[vr.index];
                const r = vr.index;
                return (
                  <tr key={row.entity_id} data-index={r} style={{ height: ROW_HEIGHT }}>
                    <td
                      className={`sticky-col${active?.r === r && active.c === 0 ? " active" : ""}${selected.has(row.entity_id) ? " row-selected" : ""}`}
                      data-r={r}
                      data-c={0}
                      onMouseDown={() => {
                        setActive({ r, c: 0 });
                        setAnchor({ r, c: 0 });
                      }}
                    >
                      <input
                        type="checkbox"
                        className="row-select"
                        checked={selected.has(row.entity_id)}
                        onChange={() => toggleSelected(row.entity_id)}
                        onMouseDown={(e) => e.stopPropagation()}
                        onKeyDown={(e) => e.stopPropagation()}
                        aria-label={`Select ${row.label}`}
                      />
                      <Link to={`/products/${encodeURIComponent(row.entity_id)}`} title="Open product detail">
                        {row.label}
                      </Link>
                      {row.entity_type === "prepack" && <span className="badge" style={{ marginLeft: 4 }}>prepack</span>}
                    </td>
                    {visibleFields.map((f, i) => {
                      const c = i + 1;
                      const pos = { r, c };
                      const editable = isEditable(row, f);
                      const inRange = !!range && r >= range.r1 && r <= range.r2 && c >= range.c1 && c <= range.c2;
                      const isActive = active?.r === r && active.c === c;
                      const isEditingHere = editing?.r === r && editing.c === c;
                      const st = f.attr ? edits.status.get(statusKey(row.entity_id, f.attr.code)) : undefined;
                      const cls = [
                        !editable && f.kind === "attr" ? "ro" : "",
                        inRange ? "selected" : "",
                        isActive ? "active" : "",
                        isEditingHere ? "editing" : "",
                        st?.outcome === "draft" ? "pending" : "",
                        st?.outcome === "rejected" || st?.outcome === "error" ? "rejected" : "",
                      ]
                        .filter(Boolean)
                        .join(" ");
                      return (
                        <td
                          key={f.key}
                          className={cls}
                          data-r={r}
                          data-c={c}
                          onMouseDown={(e) => {
                            if (isEditingHere) return;
                            if (editing) setEditing(null);
                            if (e.shiftKey && anchor) setActive(pos);
                            else {
                              setActive(pos);
                              setAnchor(pos);
                            }
                          }}
                          onDoubleClick={() => {
                            if (editable) startEdit(pos);
                            else if (f.kind === "core" || f.kind === "completeness" || f.kind === "readiness") navigate(`/products/${encodeURIComponent(row.entity_id)}`);
                          }}
                        >
                          {renderCell(row, f, pos)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
              {paddingBottom > 0 && (
                <tr>
                  <td style={{ height: paddingBottom, border: "none" }} colSpan={colCount} />
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid-status">
        <span>
          {total > 0
            ? `Showing ${(page - 1) * PAGE_SIZE + 1} to ${Math.min(page * PAGE_SIZE, total)} of ${total.toLocaleString()} ${LEVEL_LABEL[level]} rows`
            : "No rows"}
          {q.isFetching && <span className="faint"> (refreshing)</span>}
          {range && range.r1 !== range.r2 || (range && range.c1 !== range.c2) ? (
            <span className="faint"> | {(range!.r2 - range!.r1 + 1) * (range!.c2 - range!.c1 + 1)} cells selected</span>
          ) : null}
        </span>
        <span className="row">
          <span className="faint">Enter edits, Tab moves, Ctrl+C / Ctrl+V copy and paste, Ctrl+D fills down, Ctrl+Z undoes</span>
          <button className="small" disabled={!edits.canUndo} onClick={() => void edits.undo()}>
            Undo
          </button>
          <button className="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </button>
          <span>
            Page {page} of {pageCount}
          </span>
          <button className="small" disabled={page >= pageCount} onClick={() => setPage((p) => p + 1)}>
            Next
          </button>
        </span>
      </div>
      {showBulk && (
        <BulkActionsDialog
          level={level}
          entityIds={Array.from(selected)}
          view={activeView}
          onClose={() => setShowBulk(false)}
          onDone={() => {
            setSelected(new Set());
            void q.refetch();
          }}
        />
      )}
    </div>
  );
}
