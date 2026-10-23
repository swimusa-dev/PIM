// Field catalog for the product grid (DM-02). Everything except the hierarchy keys comes from metadata.

import type { AttributeDefinition, AttributeGroup, Channel, Level, ProductRow } from "../api/types";

export type FieldKind = "core" | "attr" | "completeness" | "readiness";

export interface FieldDef {
  key: string; // query field: core name, attr:<code>, completeness:<ch>, readiness:<ch>
  label: string;
  kind: FieldKind;
  groupCode: string;
  groupLabel: string;
  groupOrder: number;
  attr?: AttributeDefinition;
  channelCode?: string;
  width: number;
  sortable: boolean;
}

export const LEVEL_RANK: Record<Level, number> = { style: 0, style_color: 1, sku: 2 };

// The only hard-coded identifiers allowed (DM-01), plus core entity fields named in the contract.
export const CORE_FIELDS: { key: string; label: string; minLevel?: Level; width: number }[] = [
  { key: "style_number", label: "Style number", width: 120 },
  { key: "color_code", label: "Color code", minLevel: "style_color", width: 100 },
  { key: "size", label: "Size", minLevel: "sku", width: 80 },
  { key: "sku", label: "SKU", minLevel: "sku", width: 160 },
  { key: "upc", label: "UPC", minLevel: "sku", width: 130 },
  { key: "family_code", label: "Family", width: 120 },
  { key: "lifecycle_status", label: "Lifecycle", width: 110 },
  { key: "entity_type", label: "Entity type", width: 100 },
  { key: "brand_scopes", label: "Brand scopes", width: 140 },
];

// Extra core filter-only fields from the contract (not rendered as columns).
export const FILTER_ONLY_FIELDS: { key: string; label: string }[] = [
  { key: "approval_state", label: "Approval state" },
  { key: "ai_generated", label: "AI generated" },
  { key: "missing_images", label: "Missing images" },
  { key: "import_batch", label: "Import batch" },
];

export function attributeAppliesAtLevel(attr: AttributeDefinition, level: Level): boolean {
  if (!(attr.level in LEVEL_RANK)) return false; // ref:* attributes belong to reference entities
  return LEVEL_RANK[attr.level as Level] <= LEVEL_RANK[level];
}

export function buildFieldCatalog(
  level: Level,
  attrs: AttributeDefinition[],
  groups: AttributeGroup[],
  channels: Channel[],
): FieldDef[] {
  const groupByCode = new Map(groups.map((g) => [g.code, g]));
  const out: FieldDef[] = [];
  for (const c of CORE_FIELDS) {
    if (c.minLevel && LEVEL_RANK[c.minLevel] > LEVEL_RANK[level]) continue;
    out.push({ key: c.key, label: c.label, kind: "core", groupCode: "__core", groupLabel: "Core fields", groupOrder: -2, width: c.width, sortable: true });
  }
  for (const ch of channels) {
    out.push({
      key: `completeness:${ch.code}`,
      label: `${ch.label} completeness`,
      kind: "completeness",
      groupCode: "__channels",
      groupLabel: "Channels",
      groupOrder: -1,
      channelCode: ch.code,
      width: 120,
      sortable: true,
    });
    out.push({
      key: `readiness:${ch.code}`,
      label: `${ch.label} readiness`,
      kind: "readiness",
      groupCode: "__channels",
      groupLabel: "Channels",
      groupOrder: -1,
      channelCode: ch.code,
      width: 110,
      sortable: true,
    });
  }
  const sortedAttrs = attrs
    .filter((a) => attributeAppliesAtLevel(a, level))
    .sort((a, b) => {
      const ga = groupByCode.get(a.group_code)?.sort_order ?? 999;
      const gb = groupByCode.get(b.group_code)?.sort_order ?? 999;
      return ga - gb || a.sort_order - b.sort_order || a.label.localeCompare(b.label);
    });
  for (const a of sortedAttrs) {
    const g = groupByCode.get(a.group_code);
    out.push({
      key: `attr:${a.code}`,
      label: a.unit ? `${a.label} (${a.unit})` : a.label,
      kind: "attr",
      groupCode: a.group_code,
      groupLabel: g?.label ?? a.group_code,
      groupOrder: g?.sort_order ?? 999,
      attr: a,
      width: a.data_type === "rich_text" ? 260 : a.data_type === "boolean" ? 80 : a.data_type === "number" ? 100 : 160,
      sortable: true,
    });
  }
  return out;
}

export function defaultColumns(level: Level, channels: Channel[]): string[] {
  const cols = CORE_FIELDS.filter((c) => !c.minLevel || LEVEL_RANK[c.minLevel] <= LEVEL_RANK[level])
    .filter((c) => c.key !== "entity_type" && c.key !== "brand_scopes")
    .map((c) => c.key);
  for (const ch of channels.filter((c) => c.enabled)) {
    cols.push(`completeness:${ch.code}`);
    cols.push(`readiness:${ch.code}`);
  }
  return cols;
}

export function coreValue(row: ProductRow, key: string): string {
  switch (key) {
    case "style_number":
      return row.style_number;
    case "color_code":
      return row.color_code ?? "";
    case "size":
      return row.size ?? "";
    case "sku":
      return row.sku ?? "";
    case "upc":
      return row.upc ?? "";
    case "family_code":
      return row.family_code ?? "";
    case "lifecycle_status":
      return row.lifecycle_status;
    case "entity_type":
      return row.entity_type;
    case "brand_scopes":
      return row.brand_scopes.join(", ");
    default:
      return "";
  }
}

export function attrCodeOf(key: string): string | null {
  return key.startsWith("attr:") ? key.slice(5) : null;
}
