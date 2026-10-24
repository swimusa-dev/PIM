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

// =====================================================================================
// Phase 2 (docs/api-contract-phase2.md): imports, bulk actions, workflows, comments,
// notifications, carryover, compare, rules.
// =====================================================================================

export type BatchStatus =
  | "uploaded"
  | "mapped"
  | "validated"
  | "matched"
  | "reviewed"
  | "committing"
  | "committed"
  | "failed"
  | "rolled_back";
export type MatchStatus = "matched" | "new" | "ambiguous" | "unmatched";
export type RowAction = "create" | "update" | "skip";
export type UnmatchedPolicy = "create" | "update_only" | "create_under_match";
export type OnErrorPolicy = "skip_row" | "skip_value";
export type ImportSourceKind = "supplier" | "retailer" | "shopify" | "worksheet" | "other";

export interface ImportSource {
  code: string;
  label: string;
  kind: ImportSourceKind;
  default_policy: { unmatched: UnmatchedPolicy; on_error: OnErrorPolicy };
}

export type TransformOp =
  | "trim"
  | "split"
  | "concat"
  | "regex_extract"
  | "value_replace"
  | "unit_convert"
  | "html_clean"
  | "date_parse"
  | "case";

// split: {delimiter, index}; concat: {separator}; regex_extract: {pattern, group}; value_replace: {map};
// unit_convert: {from, to}; date_parse: {formats[]}; case: {mode}
export interface Transform {
  op: TransformOp;
  args: Record<string, unknown>;
}

// target is an attribute code, or a core key: style_number, color_code, size, sku, upc, family_code, or "skip"
export interface ColumnMapping {
  target: string;
  sources: string[];
  transforms: Transform[];
  required?: boolean;
  skip?: boolean;
}

export interface MappingTemplate {
  id: string;
  source_code: string;
  name: string;
  structure_signature: string;
  header_row: number;
  group_header_row?: number | null;
  data_start_row: number;
  columns: ColumnMapping[];
  match_keys: string[];
  unmatched_policy: UnmatchedPolicy;
  level: Level;
  version: number;
  created_by: string;
}

export interface MappingSuggestion {
  column: string;
  target: string;
  confidence: number;
  reason: string;
}

export interface ImportFileColumn {
  name: string;
  group?: string | null;
  samples: string[];
}

export interface ImportFile {
  index: number;
  name: string;
  sheet?: string | null;
  header_row: number;
  group_header_row?: number | null;
  data_start_row: number;
  rows: number;
  columns: ImportFileColumn[];
  precedence: number;
}

export interface ImportBatchOptions {
  on_error: OnErrorPolicy;
  unmatched_policy: string;
  keyless_name_column?: string | null;
}

export interface ImportBatchStats {
  rows: number;
  ok: number;
  warnings: number;
  errors: number;
  matched: number;
  new: number;
  ambiguous: number;
  unmatched: number;
  creates: number;
  adds: number;
  changes: number;
  conflicts: number;
  skipped: number;
  placeholders_removed: Record<string, number>;
}

export interface ImportDiffChange {
  entity_id: string;
  label: string;
  attribute_code: string;
  old: unknown;
  new: unknown;
  [key: string]: unknown;
}

// Shapes of creates / adds / skipped entries are not fixed by the contract (first 200 of each);
// the frontend renders the fields that are present.
export interface ImportDiff {
  creates: Record<string, unknown>[];
  adds: Record<string, unknown>[];
  changes: ImportDiffChange[];
  conflicts: number;
  skipped: Record<string, unknown>[];
}

export interface ImportBatch {
  id: string;
  status: BatchStatus;
  source_code: string;
  template_id?: string | null;
  level: Level;
  created_by: string;
  created_at: string;
  files: ImportFile[];
  mapping: ColumnMapping[];
  match_keys: string[];
  options: ImportBatchOptions;
  stats: ImportBatchStats;
  worksheet_id?: string | null;
  change_set_id?: string | null;
  error?: string | null;
  report?: Record<string, unknown>;
  diff?: ImportDiff; // set by POST /review
}

export interface ImportRowIssue {
  column?: string;
  attribute?: string;
  message: string;
}

export interface ImportRowCandidate {
  entity_id: string;
  label: string;
  score: number;
  reason: string;
}

export interface ImportRow {
  id: string;
  file_index: number;
  row_number: number;
  raw: Record<string, string>;
  mapped: Record<string, unknown>;
  match_status: MatchStatus;
  match_key_used?: string | null;
  entity_id?: string | null;
  entity_label?: string | null;
  candidates: ImportRowCandidate[];
  errors: ImportRowIssue[];
  warnings: ImportRowIssue[];
  action: RowAction;
}

export interface ImportConflict {
  id: string;
  row_id: string;
  entity_id: string;
  entity_label: string;
  attribute_code: string;
  channel_code?: string | null;
  current: { value: unknown; source_type: string; set_by?: string; set_at?: string; approval_state: string };
  incoming: { value: unknown; source: string; file?: string; row_number?: number };
  policy: string;
  status: "open" | "accepted" | "rejected" | "edited";
  resolved_value?: unknown;
}

export interface ValueMappingEntry {
  raw: string;
  count: number;
  option_code?: string | null;
  suggested?: string | null;
  confidence?: number;
}

export interface ValueMappingList {
  attribute_code: string;
  list_code: string;
  values: ValueMappingEntry[];
}

export interface ValueMappings {
  lists: ValueMappingList[];
}

export interface MappingUpdate {
  mapping: ColumnMapping[];
  match_keys: string[];
  options: ImportBatchOptions;
  template_id?: string | null;
  precedence?: number[];
}

/** Header-row edits from the Upload step, applied through PUT /api/imports/batches/{id}/files before mapping. */
export interface FileEdit {
  index: number;
  header_row: number;
  group_header_row?: number | null;
  data_start_row?: number;
}

export interface ImportRollbackResult {
  restored: number;
  manual: { entity_id: string; label: string; attribute_code: string; reason: string }[];
}

export interface ImportBatchList {
  rows: ImportBatch[];
  total: number;
}

export interface ImportRowList {
  rows: ImportRow[];
  total: number;
}

export interface ImportConflictList {
  rows: ImportConflict[];
  total: number;
}

// ---- Keyed worksheets (IMP-12) ----
export interface WorksheetCreate {
  selection: { view_id?: string; entity_ids?: string[]; level: Level };
  group_codes: string[];
  include_erp_context: boolean;
}

export interface WorksheetCreated {
  id: string;
  file_name: string;
  rows: number;
  url: string;
}

export interface Worksheet {
  id: string;
  created_by: string;
  created_at: string;
  rows: number;
  group_codes: string[];
  file_name: string;
}

// ---- Bulk actions (DM-04) ----
export type BulkKind =
  | "set_value"
  | "clear_value"
  | "add_option"
  | "remove_option"
  | "find_replace"
  | "copy_attribute"
  | "change_family"
  | "assign_workflow"
  | "run_ai"
  | "send_for_approval";
export type BulkStatus = "preview" | "queued" | "running" | "succeeded" | "failed" | "rolled_back";

export interface BulkSelection {
  view_id?: string;
  entity_ids?: string[];
  level: Level;
}

export interface BulkPreviewSample {
  entity_id: string;
  label: string;
  attribute_code?: string;
  before: unknown;
  after: unknown;
}

export interface BulkReportItem {
  entity_id: string;
  label: string;
  outcome: string;
  reason?: string;
}

export interface BulkAction {
  id: string;
  kind: BulkKind;
  selection: BulkSelection;
  params: Record<string, unknown>;
  status: BulkStatus;
  preview: { total: number; sample: BulkPreviewSample[] };
  report: { changed: number; skipped: number; failed: number; items: BulkReportItem[] };
  change_set_id?: string | null;
  created_by: string;
  created_at: string;
}

export interface BulkPreviewRequest {
  kind: BulkKind;
  selection: BulkSelection;
  params: Record<string, unknown>;
}

// ---- Workflows (DM-07, DM-12) ----
export type WorkflowStepKind = "enrich" | "review";

export interface WorkflowStepDef {
  id?: string;
  position: number;
  label: string;
  kind: WorkflowStepKind;
  role_code: string;
  group_codes: string[];
  channel_codes: string[];
  due_in_days: number;
}

// GET /api/workflows returns "definitions with steps"; the exact envelope is not fixed by the
// contract so `entry_rule` is kept as free text.
export interface WorkflowDefinition {
  code: string;
  label: string;
  enabled: boolean;
  entry_rule?: string | null;
  steps: WorkflowStepDef[];
}

export interface WorkflowItemStep {
  id: string;
  position: number;
  label: string;
  kind: WorkflowStepKind;
  role_code: string;
  group_codes: string[];
  channel_codes: string[];
}

export interface WorkflowItem {
  id: string;
  workflow_code: string;
  workflow_label: string;
  entity_id: string;
  entity_label: string;
  step: WorkflowItemStep | null;
  steps_total: number;
  state: "open" | "done" | "cancelled";
  due_at?: string | null;
  overdue: boolean;
  assigned_role?: string | null;
  assigned_email?: string | null;
  history: { at: string; event: string; step?: string; by?: string; comment?: string }[];
}

export interface WorkflowInbox {
  rows: WorkflowItem[];
  total: number;
}

export type WorkflowScope = "mine" | "role" | "all";
export type AgeBucket = "0-2" | "3-7" | "8-14" | "15+";

export interface WorkflowManager {
  by_step: { workflow_code: string; step_label: string; open: number; overdue: number; oldest_days: number }[];
  by_age: { bucket: AgeBucket; count: number }[];
}

export interface WorkflowReject {
  to_step_id: string;
  comment: string;
  attribute_comments?: { attribute_code: string; comment: string }[];
}

export interface CarryoverInfo {
  siblings: { entity_id: string; label: string; color_code: string; approved_values: number; last_approved_at?: string | null }[];
  steps_skippable: string[];
}

// ---- Comments and notifications (DM-09) ----
export interface Comment {
  id: string;
  entity_id: string;
  attribute_code?: string | null;
  author: string;
  body: string;
  mentions: string[];
  created_at: string;
  resolved: boolean;
}

export type NotificationKind = "mention" | "workflow" | "approval" | "import" | "bulk" | "conflict";

export interface Notification {
  id: string;
  kind: NotificationKind;
  title: string;
  body?: string | null;
  link?: string | null;
  created_at: string;
  read_at?: string | null;
}

export interface NotificationList {
  rows: Notification[];
  unread: number;
}

// ---- Compare (DM-06) ----
export interface CompareResult {
  attributes: AttributeDefinition[];
  a: ProductRow;
  b: ProductRow;
}

// ---- Rules (GOV-01, GOV-06) ----
export type RuleTrigger = "on_save" | "on_import" | "nightly" | "all";
export type ConditionOp = "eq" | "neq" | "contains" | "in" | "empty" | "not_empty" | "gt" | "lt" | "regex";
export type RuleActionOp =
  | "set"
  | "clear"
  | "copy"
  | "concatenate"
  | "calculate"
  | "set_approval_state"
  | "add_to_workflow"
  | "trigger_ai";

// field = attr:<code> or core key
export interface Condition {
  field: string;
  op: ConditionOp;
  value?: unknown;
}

export interface RuleAction {
  op: RuleActionOp;
  target?: string;
  value?: unknown;
  source?: string;
  parts?: string[];
  separator?: string;
  expression?: string;
  workflow_code?: string;
  task_type?: string;
}

export interface RulePreview {
  sample: { entity_id: string; label: string; brand_scopes: string[]; changes: { attribute_code: string; before: unknown; after: unknown }[] }[];
  brands_covered: string[];
  matched_total: number;
  suspicious_constants: { attribute_code: string; value: unknown; brands: string[]; families: string[] }[];
  ok_to_activate: boolean;
  blockers: string[];
}

export interface Rule {
  id: string;
  code: string;
  label: string;
  priority: number;
  enabled: boolean;
  status: "draft" | "active";
  trigger: RuleTrigger;
  level: Level;
  condition: { all?: Condition[]; any?: Condition[] };
  actions: RuleAction[];
  brand_scopes: string[];
  last_preview?: RulePreview | null;
  activated_at?: string | null;
  activated_by?: string | null;
}

export type RuleInput = Omit<Rule, "id" | "last_preview" | "activated_at" | "activated_by" | "status"> & { status?: "draft" | "active" };

// GET /api/rules/runs rows are not fixed by the contract beyond "history"; render what is present.
export interface RuleRun {
  id: string;
  rule_id?: string;
  rule_code?: string;
  started_at?: string;
  finished_at?: string | null;
  status?: string;
  affected?: number;
  trigger?: string;
  by?: string;
  [key: string]: unknown;
}
