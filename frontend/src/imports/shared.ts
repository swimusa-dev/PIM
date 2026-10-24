// Shared helpers for the import wizard (IMP-01 to IMP-08). Metadata-driven: the only hard-coded
// identifiers are the core keys named in the contract.

import type { AttributeDefinition, AttributeGroup, BatchStatus, ColumnMapping, ImportBatch, Level, TransformOp } from "../api/types";
import { attributeAppliesAtLevel } from "../grid/fields";

export type StepKey = "upload" | "map" | "validate" | "match" | "review";

export const STEPS: { key: StepKey; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "map", label: "Map" },
  { key: "validate", label: "Validate" },
  { key: "match", label: "Match" },
  { key: "review", label: "Review and Commit" },
];

/** Index of the furthest step the batch status allows (steps before it are done). */
export function reachedStep(status: BatchStatus | undefined): number {
  switch (status) {
    case undefined:
      return 0;
    case "uploaded":
      return 1;
    case "mapped":
      return 2;
    case "validated":
      return 3;
    case "matched":
      return 4;
    default:
      return 4; // reviewed, committing, committed, failed, rolled_back
  }
}

export const CORE_KEYS: { key: string; label: string; minLevel?: Level }[] = [
  { key: "style_number", label: "Style number" },
  { key: "color_code", label: "Color code", minLevel: "style_color" },
  { key: "size", label: "Size", minLevel: "sku" },
  { key: "sku", label: "SKU", minLevel: "sku" },
  { key: "upc", label: "UPC", minLevel: "sku" },
  { key: "family_code", label: "Family" },
];

const LEVEL_RANK: Record<Level, number> = { style: 0, style_color: 1, sku: 2 };

export function coreKeysForLevel(level: Level) {
  return CORE_KEYS.filter((k) => !k.minLevel || LEVEL_RANK[k.minLevel] <= LEVEL_RANK[level]);
}

export interface TargetOption {
  value: string;
  label: string;
  group: string;
  groupOrder: number;
  attr?: AttributeDefinition;
}

/** Target picker options: Skip, core keys, then attributes grouped by attribute group (P5). */
export function buildTargetOptions(level: Level, attrs: AttributeDefinition[], groups: AttributeGroup[]): TargetOption[] {
  const byCode = new Map(groups.map((g) => [g.code, g]));
  const out: TargetOption[] = [{ value: "skip", label: "Skip this column", group: "Skip", groupOrder: -3 }];
  for (const k of coreKeysForLevel(level)) out.push({ value: k.key, label: k.label, group: "Core keys", groupOrder: -2 });
  const applicable = attrs
    .filter((a) => attributeAppliesAtLevel(a, level) && a.status !== "deprecated")
    .sort((a, b) => {
      const ga = byCode.get(a.group_code)?.sort_order ?? 999;
      const gb = byCode.get(b.group_code)?.sort_order ?? 999;
      return ga - gb || a.sort_order - b.sort_order || a.label.localeCompare(b.label);
    });
  for (const a of applicable) {
    const g = byCode.get(a.group_code);
    out.push({ value: a.code, label: a.label, group: g?.label ?? a.group_code, groupOrder: g?.sort_order ?? 999, attr: a });
  }
  return out;
}

export function groupTargetOptions(opts: TargetOption[]): { group: string; options: TargetOption[] }[] {
  const m = new Map<string, TargetOption[]>();
  for (const o of opts) {
    const arr = m.get(o.group) ?? [];
    arr.push(o);
    m.set(o.group, arr);
  }
  return Array.from(m.entries()).map(([group, options]) => ({ group, options }));
}

export function targetLabel(target: string, opts: TargetOption[]): string {
  if (target === "skip") return "Skip";
  return opts.find((o) => o.value === target)?.label ?? target;
}

export const MAX_SOURCES = 4;

/** Returns a new mapping with `column` assigned to `target` ("" removes the column from every mapping). */
export function setColumnTarget(mapping: ColumnMapping[], column: string, target: string): ColumnMapping[] {
  let next = mapping.map((m) => ({ ...m, sources: m.sources.filter((s) => s !== column) }));
  next = next.filter((m) => m.sources.length > 0 || m.required);
  if (!target) return next;
  if (target === "skip") return [...next, { target: "skip", sources: [column], transforms: [], skip: true }];
  const ix = next.findIndex((m) => m.target === target && !m.skip);
  if (ix >= 0) {
    if (next[ix].sources.length >= MAX_SOURCES) return next;
    next[ix] = { ...next[ix], sources: [...next[ix].sources, column] };
    return next;
  }
  return [...next, { target, sources: [column], transforms: [] }];
}

export function mappingForColumn(mapping: ColumnMapping[], column: string): ColumnMapping | undefined {
  return mapping.find((m) => m.sources.includes(column));
}

export function isMapped(mapping: ColumnMapping[], target: string): boolean {
  return mapping.some((m) => m.target === target && !m.skip && m.sources.length > 0);
}

/** Required targets still unmapped: match keys, identity keys needed to create rows, and columns flagged required. */
export function missingRequired(batch: ImportBatch, mapping: ColumnMapping[], matchKeys: string[], keyless: boolean, unmatchedPolicy: string): string[] {
  const missing = new Set<string>();
  if (!keyless) for (const k of matchKeys) if (!isMapped(mapping, k)) missing.add(k);
  for (const m of mapping) if (m.required && !m.skip && m.sources.length === 0) missing.add(m.target);
  if (unmatchedPolicy !== "update_only") {
    if (batch.level === "style" && !isMapped(mapping, "style_number")) missing.add("style_number");
    if (batch.level === "style_color") {
      if (!isMapped(mapping, "style_number")) missing.add("style_number");
      if (!isMapped(mapping, "color_code")) missing.add("color_code");
    }
    if (batch.level === "sku") {
      const bySku = isMapped(mapping, "sku") || isMapped(mapping, "upc");
      const byParts = isMapped(mapping, "style_number") && isMapped(mapping, "color_code") && isMapped(mapping, "size");
      if (!bySku && !byParts) missing.add("sku");
    }
  }
  return Array.from(missing);
}

export const TRANSFORM_OPS: { op: TransformOp; label: string }[] = [
  { op: "trim", label: "Trim whitespace" },
  { op: "split", label: "Split and take part" },
  { op: "concat", label: "Concatenate sources" },
  { op: "regex_extract", label: "Regex extract" },
  { op: "value_replace", label: "Replace values" },
  { op: "unit_convert", label: "Convert unit" },
  { op: "html_clean", label: "Clean HTML" },
  { op: "date_parse", label: "Parse date" },
  { op: "case", label: "Change case" },
];

export function defaultArgs(op: TransformOp): Record<string, unknown> {
  switch (op) {
    case "split":
      return { delimiter: ",", index: 0 };
    case "concat":
      return { separator: " " };
    case "regex_extract":
      return { pattern: "", group: 1 };
    case "value_replace":
      return { map: {} };
    case "unit_convert":
      return { from: "", to: "" };
    case "date_parse":
      return { formats: ["%Y-%m-%d"] };
    case "case":
      return { mode: "title" };
    default:
      return {};
  }
}

export function confidenceClass(c: number): string {
  return c >= 0.85 ? "hi" : c >= 0.6 ? "mid" : "lo";
}

export function shortValue(v: unknown, max = 60): string {
  if (v === null || v === undefined || v === "") return "";
  const s = typeof v === "string" ? v : Array.isArray(v) ? v.map(String).join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v);
  return s.length > max ? `${s.slice(0, max)}...` : s;
}
