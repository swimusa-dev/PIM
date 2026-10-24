// Interfaces copied from docs/api-contract.md (PIM API contract v1).
// Keep these in sync with the backend; the frontend builds exactly to this contract.

export type Level = "style" | "style_color" | "sku";
export type ApprovalState = "draft" | "proposed" | "approved" | "rejected";
export type SourceType = "erp" | "import" | "user" | "ai" | "rule" | "default";

export type DataType =
  | "text"
  | "rich_text"
  | "number"
  | "boolean"
  | "date"
  | "single_select"
  | "multi_select"
  | "asset_ref"
  | "product_ref"
  | "reference_entity";

export type AttributeStatus = "proposed" | "confirmed" | "deprecated";
export type SourceOfTruth = "erp" | "plm" | "pim" | "channel";

export interface AttributeValidation {
  min_length?: number;
  max_length?: number;
  regex?: string;
  min?: number;
  max?: number;
}

export interface AttributeDefinition {
  code: string;
  label: string;
  data_type: DataType;
  level: Level | string; // "ref:print" etc. for reference entity attributes (DM-11)
  group_code: string;
  sort_order: number;
  option_list_code?: string | null;
  reference_type_code?: string | null;
  unit?: string | null;
  validation: AttributeValidation;
  channel_scopable: boolean;
  allows_not_applicable: boolean;
  default_value?: string | null;
  owner_role?: string | null;
  owner_person?: string | null;
  status: AttributeStatus;
  source_of_truth: SourceOfTruth;
  help_text?: string | null;
  example_value?: string | null;
}

export interface AttributeGroup {
  code: string;
  label: string;
  owning_role: string;
  sort_order: number;
  read_only: boolean;
}

export interface OptionValue {
  code: string;
  label: string;
  sort_order: number;
  channel_mappings: Record<string, string>;
}

export interface OptionList {
  code: string;
  label: string;
  kind: "option" | "size_scale";
  size_group?: string | null;
  values: OptionValue[];
}

export interface Family {
  code: string;
  label: string;
  group_codes: string[];
}

export interface Channel {
  code: string;
  label: string;
  adapter: string;
  kind: "dtc" | "marketplace" | "retailer";
  enabled: boolean;
  requirement_set_code?: string | null;
  protected_fields: string[];
  config: Record<string, unknown>;
  version: number;
}

export type ReadOnlyReason = "erp" | "inherited" | "no_rights" | "deprecated";

export interface ValueCell {
  value: unknown; // typed JSON value; null when empty
  raw_value?: string | null; // ERP raw value when a normalized mapping applied (IMP-11)
  not_applicable?: boolean;
  source_type: SourceType;
  source_ref?: string | null;
  set_by?: string | null;
  set_at?: string | null; // ISO timestamps
  ai_generated: boolean;
  approval_state: ApprovalState;
  version: number;
  inherited_from?: { level: Level; entity_id: string } | null; // DM-01 strict ownership
  read_only: boolean;
  read_only_reason?: ReadOnlyReason | null;
  is_default?: boolean; // GOV-06
  draft?: { value: unknown; set_by: string; set_at: string } | null; // DM-08 pending draft for this user
}

export interface Readiness {
  ready: boolean;
  eligible: boolean;
  missing_attributes: string[];
  missing_shots: string[];
  mapping_gaps: string[];
  invalid: string[];
  reasons: string[];
}

export type LifecycleStatus = "active" | "discontinued" | "new";

export interface ProductRow {
  entity_id: string;
  level: Level;
  entity_type: "product" | "prepack";
  style_number: string;
  color_code?: string | null;
  size?: string | null;
  sku?: string | null;
  upc?: string | null;
  family_code?: string | null;
  lifecycle_status: LifecycleStatus;
  brand_scopes: string[];
  parent_id?: string | null;
  label: string;
  values: Record<string, ValueCell>;
  completeness: Record<string, number>; // channel_code -> percent 0..100
  readiness: Record<string, Readiness>;
}

export interface ImageLink {
  id: string;
  asset_id: string;
  entity_id: string;
  shot_type?: string | null;
  tier: 1 | 2 | 3;
  confidence: number;
  status: "proposed" | "confirmed" | "rejected";
  thumbnail_url?: string;
  filename: string;
  width?: number;
  height?: number;
  sort_order: number;
}

// ---- Endpoint payloads ----

export interface Health {
  status: string;
  version: string;
  erp_last_load_at: string | null;
  erp_stale: boolean;
  erp_stale_threshold_hours: number;
}

export type DataRight = "none" | "view" | "edit" | "approve";

export interface Me {
  email: string;
  user_id: string;
  roles: string[];
  permissions: string[];
  data_rights: Record<string, DataRight>;
  channel_rights: Record<string, { run: boolean; edit_profile: boolean }>;
  brand_scopes: string[];
}

export interface ReferenceType {
  code: string;
  label: string;
  attribute_codes: string[];
}

export interface ReferenceEntityRow {
  id: string;
  type_code: string;
  code: string;
  label: string;
  values: Record<string, ValueCell>;
  linked_products: number;
}

export interface ReferenceEntityList {
  rows: ReferenceEntityRow[];
  total: number;
}

export interface ReferenceImpact {
  impact: { products: number; channels: string[] };
  [key: string]: unknown;
}

export type FilterOp =
  | "eq"
  | "neq"
  | "contains"
  | "in"
  | "empty"
  | "not_empty"
  | "gt"
  | "lt"
  | "gte"
  | "lte";

export interface QueryFilter {
  field: string;
  op: FilterOp;
  value: unknown;
}

export interface QuerySort {
  field: string;
  dir: "asc" | "desc";
}

export interface ProductQuery {
  level: Level;
  page: number;
  page_size: number;
  sort: QuerySort[];
  filters: QueryFilter[];
  search: string;
  columns: string[];
  view_id?: string;
}

export interface ProductQueryResult {
  rows: ProductRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProductGroupSection {
  group: AttributeGroup;
  attributes: AttributeDefinition[];
}

export interface ProductDetail {
  entity: ProductRow;
  ancestors: ProductRow[];
  children: ProductRow[];
  groups: ProductGroupSection[];
  images: ImageLink[];
  history_count: number;
}

export type EditOutcome = "approved" | "draft" | "rejected";

export interface ValueEditResult {
  attribute_code: string;
  outcome: EditOutcome;
  message?: string;
}

export interface ValueEditResponse {
  results: ValueEditResult[];
}

export interface HistoryRow {
  id: string;
  attribute_code: string;
  channel_code: string | null;
  old_value: unknown;
  new_value: unknown;
  source_type: SourceType;
  set_by: string;
  set_at: string;
  change_set_id: string | null;
  reason: string | null;
}

export interface HistoryResult {
  rows: HistoryRow[];
  total: number;
}

export interface TreeNode {
  row: ProductRow;
  children: TreeNode[];
}

export interface ProductTree {
  root: ProductRow;
  nodes: TreeNode[];
}

export type ViewShare = "private" | `role:${string}` | "everyone";

export interface ViewDefinition {
  filters: QueryFilter[];
  columns: string[];
  sort: QuerySort[];
  search: string;
}

export interface SavedView {
  id: string;
  name: string;
  level: Level;
  owner_email: string;
  shared_with: ViewShare | string;
  is_default: boolean;
  definition: ViewDefinition;
}

export interface Dashboard {
  open_tasks: number;
  overdue: number;
  blocking_launches: {
    entity_id: string;
    label: string;
    launch_date: string;
    days_left: number;
    channels_not_ready: string[];
  }[];
  readiness_by_channel: {
    channel_code: string;
    label: string;
    ready: number;
    not_ready: number;
    ineligible: number;
  }[];
  recent_ingest: {
    id: string;
    started_at: string;
    finished_at: string | null;
    status: string;
    rows_read: number;
    created: number;
    updated: number;
    discontinued: number;
    placeholders_removed: number;
  }[];
  recent_packages: {
    id: string;
    channel_code: string;
    created_at: string;
    status: string;
    products: number;
    changes: number;
  }[];
  ai_pending: number;
  conflicts_open: number;
}

export interface ApprovalItem {
  entity_id: string;
  label: string;
  attribute_code: string;
  current: unknown;
  proposed: unknown;
  set_at: string;
  draft_id: string;
}

export interface ApprovalQueue {
  groups: { submitter: string; items: ApprovalItem[] }[];
}

export type PackageStatus = "pending" | "building" | "ready" | "failed" | "reconciled";

export interface PackageFile {
  name: string;
  size: number;
}

export interface Package {
  id: string;
  channel_code: string;
  status: PackageStatus;
  created_by: string;
  created_at: string;
  snapshot_at: string | null;
  products: number;
  changes: number;
  files: PackageFile[];
}

export type ReconcileResult = "applied" | "not_applied" | "changed_differently";

export interface PackageRow {
  handle: string;
  title: string;
  field: string;
  current_value: unknown;
  proposed_value: unknown;
  source_type: SourceType;
  approval_state: ApprovalState;
  ai_generated: boolean;
  include: boolean;
  note: string | null;
  // Set after POST /api/packages/{id}/reconcile (contract: "marks rows applied / not_applied / changed_differently").
  reconcile_result?: ReconcileResult | null;
}

export interface PackageSummary {
  by_field?: { field: string; count: number }[];
  by_product?: { handle: string; title?: string; count: number }[];
  skipped?: { handle: string; reason: string }[];
  intentional_clears?: { handle: string; field: string }[];
  [key: string]: unknown;
}

export interface PackageDetail extends Package {
  rows: PackageRow[];
  summary: PackageSummary;
}

export interface PackageCreate {
  channel_code: string;
  selection: { view_id?: string; entity_ids?: string[]; changed_since?: string };
  snapshot: { mode: "api" | "csv_upload" };
}

export type ImageQueueKind = "candidates" | "missing" | "unparsed";

// IMG-05 queues. The contract does not fix the row shapes per kind, so the
// frontend accepts the union below and renders what is present.
export interface ImageQueueCandidate extends ImageLink {
  proposed_label?: string | null;
  proposed_entity_id?: string | null;
}
export interface ImageQueueMissing {
  entity_id: string;
  label: string;
  style_number: string;
  color_code?: string | null;
  missing_shots: string[];
}
export interface ImageQueueUnparsed {
  asset_id: string;
  filename: string;
  thumbnail_url?: string;
  reason?: string | null;
}
export interface ImageQueue {
  kind: ImageQueueKind;
  rows: (ImageQueueCandidate | ImageQueueMissing | ImageQueueUnparsed)[];
  total?: number;
}

export interface ProductImages {
  slots: { shot_type: string; required_by: string[]; link?: ImageLink | null }[];
  candidates: ImageLink[];
}

export interface ErpDefect {
  id?: string;
  entity_id?: string;
  style_number?: string;
  color_code?: string | null;
  attribute_code: string;
  raw_value: string | null;
  issue: string;
  seen_at?: string;
  [key: string]: unknown;
}

export interface ErpDefectsReport {
  rows: ErpDefect[];
  total: number;
  page?: number;
  page_size?: number;
}

export interface AttributeUsageRow {
  code: string;
  label: string;
  group_code: string;
  level: string;
  status: AttributeStatus;
  filled: number;
  total: number;
  fill_rate: number;
  distinct_values?: number;
  used_by_channels?: string[];
  last_set_at?: string | null;
  [key: string]: unknown;
}

export interface UserRole {
  id?: string;
  email: string;
  role: string;
  brand_scopes: string[];
}

export interface JobRun {
  id: string;
  kind: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  message?: string | null;
  [key: string]: unknown;
}

export interface Telemetry {
  job_runs: JobRun[];
  adapter_errors: { adapter: string; at: string; message: string; [key: string]: unknown }[];
  ai_spend: { period?: string; calls?: number; input_tokens?: number; output_tokens?: number; cost_usd?: number; [key: string]: unknown };
  [key: string]: unknown;
}
