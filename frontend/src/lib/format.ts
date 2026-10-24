// Display helpers shared by the grid, detail page, approvals and packages.

import type { AttributeDefinition, OptionList, ValueCell } from "../api/types";

export function formatDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return withTime
    ? d.toLocaleString("en-US", { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
    : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function hoursSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return null;
  return Math.max(0, Math.round((Date.now() - d) / 36e5));
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Human-readable rendering of any attribute value, using option labels when available. */
export function displayValue(
  value: unknown,
  attr?: AttributeDefinition,
  optionLists?: Record<string, OptionList>,
): string {
  if (value === null || value === undefined || value === "") return "";
  if (attr?.data_type === "boolean" || typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) {
    return value.map((v) => displayValue(v, attr ? { ...attr, data_type: "single_select" } : undefined, optionLists)).join(", ");
  }
  if (attr && (attr.data_type === "single_select" || attr.data_type === "multi_select") && attr.option_list_code && optionLists) {
    const list = optionLists[attr.option_list_code];
    const found = list?.values.find((o) => o.code === String(value));
    if (found) return found.label;
  }
  if (attr?.data_type === "reference_entity" && typeof value === "object" && value !== null) {
    const v = value as { label?: string; code?: string; id?: string };
    return v.label ?? v.code ?? v.id ?? JSON.stringify(value);
  }
  if (attr?.data_type === "date" && typeof value === "string") return formatDate(value, false);
  if (typeof value === "number") return attr?.unit ? `${value} ${attr.unit}` : String(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Text put on the clipboard for a cell (TSV export), without unit suffixes or labels so it round-trips. */
export function clipboardValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function cellValue(cell: ValueCell | undefined): unknown {
  if (!cell) return null;
  if (cell.not_applicable) return null;
  return cell.value;
}

export const READ_ONLY_REASON_TEXT: Record<string, string> = {
  erp: "Owned by the ERP (BlueCherry Style Master). Edit it in the ERP.",
  inherited: "Inherited from the owning level. Edit it at the owning entity.",
  no_rights: "You do not have edit rights on this attribute group.",
  deprecated: "This attribute is deprecated and can no longer be edited.",
};

export function readOnlyText(cell: ValueCell | undefined): string {
  if (!cell || !cell.read_only) return "";
  if (cell.read_only_reason && READ_ONLY_REASON_TEXT[cell.read_only_reason]) {
    return READ_ONLY_REASON_TEXT[cell.read_only_reason];
  }
  return "Read only.";
}

export function provenanceText(cell: ValueCell | undefined): string {
  if (!cell) return "No value";
  const parts: string[] = [];
  parts.push(`Source: ${cell.source_type}${cell.source_ref ? ` (${cell.source_ref})` : ""}`);
  if (cell.set_by) parts.push(`Set by: ${cell.set_by}`);
  if (cell.set_at) parts.push(`Set at: ${formatDate(cell.set_at)}`);
  parts.push(`AI generated: ${cell.ai_generated ? "yes" : "no"}`);
  parts.push(`Approval: ${cell.approval_state}`);
  if (cell.is_default) parts.push("Default value applied");
  if (cell.raw_value) parts.push(`ERP raw value: ${cell.raw_value}`);
  if (cell.inherited_from) parts.push(`Inherited from ${cell.inherited_from.level} ${cell.inherited_from.entity_id}`);
  if (cell.draft) parts.push(`Draft pending by ${cell.draft.set_by} at ${formatDate(cell.draft.set_at)}`);
  if (cell.read_only) parts.push(readOnlyText(cell));
  return parts.join("\n");
}

export const LEVEL_LABEL: Record<string, string> = {
  style: "Style",
  style_color: "Style-Color",
  sku: "SKU",
};

export function titleCase(s: string): string {
  return s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
