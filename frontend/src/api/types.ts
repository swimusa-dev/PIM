// Interfaces copied from docs/api-contract.md (PIM API contract v1) plus the Phase 2, 3, 4 and 5 additions
// (AI-01 to AI-07 and GOV-03, then Phase 5 EXP-08, EXP-09, EXP-10, EXP-11, D-03, D-13 at the end of the file).
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
  // Phase 6 (EXP-03): non-blocking notes, e.g. a related product that is discontinued or missing.
  warnings?: string[];
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
  // Phase 4 (GOV-03): quality grade and score per channel; "" is the overall score. Absent before the first recompute.
  quality?: Record<string, QualityCell>;
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
  // Phase 3 (IMG-03, IMG-05, IMG-06): rule failures per channel, AI-generated flag, match evidence.
  rule_failures?: Record<string, string[]>;
  ai_generated_image?: boolean;
  evidence?: Record<string, unknown>;
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
  // Phase 4 (AI-04): set when the draft came from an AI run.
  run_id?: string | null;
  ai_output_id?: string | null;
}

export interface ApprovalQueue {
  groups: { submitter: string; items: ApprovalItem[] }[];
  // Phase 4 (AI-04): runs with drafts in the queue, for the Run filter.
  runs?: ApprovalRunSummary[];
}

export type PackageStatus = "pending" | "building" | "ready" | "failed" | "reconciled";

export interface PackageFile {
  name: string;
  size: number;
  // Phase 5 (D-13): "matrixify" for matrixify.xlsx beside the review workbook and the native CSVs.
  kind?: string;
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
  // Phase 5 (D-03): the last Shopify sandbox run report, when any.
  sandbox_report?: SandboxReport | null;
}

export interface PackageCreate {
  channel_code: string;
  selection: { view_id?: string; entity_ids?: string[]; changed_since?: string };
  snapshot: { mode: "api" | "csv_upload" };
}

export type ImageQueueKind = "candidates" | "missing" | "unparsed" | "failing_rules";

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
  rows: (ImageQueueCandidate | ImageQueueMissing | ImageQueueUnparsed | ImageQueueFailingRules)[];
  total?: number;
}

export interface ProductImages {
  slots: { shot_type: string; required_by: string[]; link?: ImageLink | null }[];
  candidates: ImageLink[];
  // Phase 3: every non-rejected link in sort order (slots keep one link per shot type; ordering needs them all).
  links?: ImageLink[];
  // Phase 3: the technical image rules per channel (shape owned by the backend, rendered as key/value).
  rules?: Record<string, Record<string, unknown>>;
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
  // Phase 6 (GOV-04): 30-day error rate per adapter.
  adapter_error_rates?: AdapterErrorRate[];
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

// =====================================================================================
// Phase 3 (docs/api-contract-phase3.md): channel exports (EXP-01, EXP-02, EXP-04, EXP-05,
// EXP-06, EXP-12) and images (IMG-03, IMG-05, IMG-06, IMG-07).
// =====================================================================================

export type TargetFieldType = "string" | "number" | "integer" | "boolean" | "enum" | "array" | "object" | "date";

export interface TargetField {
  name: string;
  type: TargetFieldType;
  required: boolean;
  enum?: string[];
  max_length?: number;
  min?: number;
  max?: number;
  group?: string | null;
  description?: string | null;
  path?: string | null; // JSON pointer inside the payload for API channels
}

export type TargetSchemaSource = "walmart_spec" | "mirakl" | "shopify" | "retailer_xlsx" | "manual";

export interface TargetSchema {
  source: TargetSchemaSource;
  version?: string | null;
  loaded_at: string;
  product_type?: string | null;
  fields: TargetField[];
  raw_available: boolean;
}

export interface SchemaDiff {
  added: TargetField[];
  removed: TargetField[];
  required_changed: { name: string; before: boolean; after: boolean }[];
  enum_changed: { name: string; added: string[]; removed: string[] }[];
}

export type ChannelTransformOp = "concatenate" | "format" | "unit_convert" | "conditional" | "case" | "truncate";

// concatenate {parts[], separator}; format {template "{{attr.x}} ..."}; unit_convert {from,to};
// conditional {when: Condition, then: value, else?: value}; case {mode}; truncate {max_length}
export interface ChannelTransform {
  target: string;
  op: ChannelTransformOp;
  args: Record<string, unknown>;
}

export interface ImageProfile {
  shot_types: string[];
  width?: number;
  height?: number;
  format: "jpg" | "png" | "webp";
  pad_to_ratio?: string | null;
  background?: "white" | "transparent" | null;
  naming?: string | null; // e.g. "{{style_number}}-{{color_code}}-{{seq}}"
}

export interface ChannelMapping {
  attribute_mapping: Record<string, string>;
  transforms: ChannelTransform[];
  value_mappings: { attribute_code: string; list_code: string; mapped: number; unmapped: string[] }[];
  gaps: { required_fields_unmapped: string[]; mapped_fields_missing_in_schema: string[] };
  // Assumption: the GET also echoes the image profile saved with the PUT so the editor can show it.
  image_profile?: ImageProfile | null;
}

export interface ChannelMappingUpdate {
  attribute_mapping: Record<string, string>;
  transforms: ChannelTransform[];
  image_profile?: ImageProfile;
}

export type PayloadIssueKind = "missing_required" | "invalid_type" | "enum" | "length" | "schema" | "transform" | "image";

export interface PayloadIssue {
  entity_id: string;
  label: string;
  field?: string | null;
  attribute_code?: string | null;
  message: string;
  kind: PayloadIssueKind;
  severity: "error" | "warning";
}

export type PublishKind = "dry_run" | "package" | "publish" | "scheduled";
export type PublishMode = "delta" | "full";
export type PublishStatus = "running" | "completed" | "failed" | "skipped" | "submitted" | "accepted" | "partial" | "rejected";

export interface PublishFile {
  name: string;
  size: number;
  kind: string;
}

export interface Publish {
  id: string;
  channel_code: string;
  channel_version: number;
  kind: PublishKind;
  mode: PublishMode;
  status: PublishStatus;
  created_by: string;
  created_at: string;
  finished_at?: string | null;
  product_count: number;
  valid_count: number;
  invalid_count: number;
  selection: Record<string, unknown>;
  files: PublishFile[];
  // dry_run: summary.preview object[]; package transport: summary.package_id; Phase 5: summary.delivery (DeliveryResult),
  // summary.walmart (WalmartFeedSummary), summary.listing_quality ({[external_id]: number}).
  summary: Record<string, unknown>;
  external_batch_id?: string | null;
  error?: string | null;
}

export type PublishItemStatus = "pending" | "valid" | "invalid" | "submitted" | "accepted" | "rejected" | "in_review";

export interface PublishItemError {
  message: string;
  field?: string | null;
  attribute_code?: string | null;
  kind: "internal" | "external";
}

export interface PublishItem {
  id: string;
  entity_id: string;
  label: string;
  external_id?: string | null;
  status: PublishItemStatus;
  issues: PayloadIssue[];
  errors: PublishItemError[];
  updated_at: string;
  // Phase 5 (EXP-08): Walmart Listing Quality score pulled by the feedback poll.
  listing_quality?: number | null;
}

export interface PublishDetail extends Publish {
  items: PublishItem[];
}

export interface PublishList {
  rows: Publish[];
  total: number;
}

export interface PublishItemList {
  rows: PublishItem[];
  total: number;
}

export interface PublishSelection {
  view_id?: string;
  entity_ids?: string[];
  changed_since?: string;
}

export interface PublishRequest {
  selection: PublishSelection;
  mode: PublishMode;
  preview: number;
}

export interface FeedbackResult {
  updated: number;
  accepted: number;
  rejected: number;
  in_review: number;
}

export interface ChannelHealth {
  channel_code: string;
  publishes: number;
  products_sent: number;
  accepted: number;
  rejected: number;
  in_review: number;
  health_score: number | null;
  last_publish_at?: string | null;
  last_success_at?: string | null;
  open_rejections: number;
  top_errors: { message: string; count: number; kind: "internal" | "external" }[];
  // Phase 5 (EXP-08)
  listing_quality_avg?: number | null;
  feeds_in_progress?: number;
}

export interface ChannelDelta {
  changed: number;
  sample: { entity_id: string; label: string; reasons: string[] }[];
}

export interface ExportSchedule {
  enabled: boolean;
  mode: PublishMode;
  every_hours?: number | null;
  at_hour?: number | null;
  at_minute?: number;
  timezone: string;
  view_id?: string | null;
  last_run_at?: string | null;
  last_result?: string | null;
}

export interface RunNowResult {
  status: "started" | "skipped";
  reason?: string;
}

export interface EligibilityOverride {
  id: string;
  entity_id: string;
  channel_code: string;
  reason: string;
  approved_by: string;
  created_at: string;
  expires_at?: string | null;
}

export interface EligibilityChannel {
  eligible: boolean;
  reasons: string[];
  override?: EligibilityOverride | null;
}

export interface Eligibility {
  channels: Record<string, EligibilityChannel>;
}

export interface Rendition {
  asset_id: string;
  version_id?: string | null;
  channel_code: string;
  url: string;
  width?: number | null;
  height?: number | null;
  format: string;
  source: "air_cdn" | "job";
  created_at: string;
}

export interface ShotType {
  code: string;
  label: string;
  sort_order: number;
}

/** Rows of the failing_rules image queue: confirmed links plus the product label and the failing reasons. */
export interface ImageQueueFailingRules extends ImageLink {
  label?: string | null;
  entity_label?: string | null;
  reasons?: string[];
}

// =================================================================================
// Phase 4: AI enrichment and quality score (docs/api-contract-phase4.md)
// AI-01 to AI-07, GOV-03
// =================================================================================

export type TaskType = "generate" | "adapt" | "extract" | "classify" | "check" | "restructure" | "expand";

export interface BrandVoice {
  brand_code: string;
  label: string;
  tone: string;
  do_rules: string[];
  dont_rules: string[];
  blocked_terms: string[];
  trademark_terms: Record<string, string>;
  punctuation_rules: string[];
  examples: string[];
  version: number;
  updated_at: string;
  updated_by?: string | null;
}

export type TemplateStatus = "draft" | "active" | "retired";
export type ModelTask = "copy" | "classify";

export interface PromptTemplate {
  code: string;
  version: number;
  label: string;
  task_type: TaskType;
  target_attribute?: string | null;
  // extract / restructure write several attributes; classify targets a select attribute; check targets any text attribute
  output_attributes: string[];
  channel_code?: string | null;
  family_code?: string | null;
  brand_code: string;
  body: string; // uses {{attr.<code>}}, {{core.<field>}}, {{input.text}}, {{channel.max_length}}
  input_attributes: string[];
  input_shot_types: string[];
  accepts_text_input: boolean;
  accepts_document: boolean;
  max_length?: number | null; // null = from the attribute definition and channel requirement
  model_task: ModelTask; // which configured endpoint (AI-01)
  status: TemplateStatus;
  updated_at: string;
  updated_by?: string | null;
  eval_gate?: { last_run_id?: string | null; last_score?: number | null; blocked: boolean };
}

export interface TemplateVersion {
  version: number;
  body: string;
  updated_at: string;
  updated_by?: string | null;
  note?: string | null;
}

export interface PromptTemplateDetail extends PromptTemplate {
  versions: TemplateVersion[];
}

/** Fields sent on create and update (the server owns code on update, version, status and timestamps). */
export type PromptTemplateInput = Omit<PromptTemplate, "version" | "updated_at" | "updated_by" | "eval_gate" | "status"> & {
  status?: TemplateStatus;
  note?: string | null;
};

export interface TemplatePreview {
  prompt: string;
  inputs: Record<string, unknown>;
  missing_inputs: string[];
}

export type AiOutputStatus = "proposed" | "accepted" | "edited" | "rejected" | "failed" | "needs_input" | "info";

export interface DiffPart {
  op: "equal" | "insert" | "delete";
  text: string;
}

export interface CheckFinding {
  kind: string;
  message: string;
  severity: "error" | "warning";
}

export interface AiOutput {
  id: string;
  run_id?: string | null;
  entity_id: string;
  label: string;
  attribute_code: string;
  channel_code: string;
  task_type: TaskType;
  template_code: string;
  template_version: number;
  model: string;
  status: AiOutputStatus; // info = check / classify-below-threshold results
  proposed_value: unknown;
  current_value: unknown;
  final_value?: unknown; // after accept or edit
  diff: DiffPart[]; // word-level vs current_value
  draft_id?: string | null;
  confidence?: number | null;
  needs_input: string[];
  grounding_errors: string[];
  check_findings?: CheckFinding[]; // task_type check
  rejection_reason?: string | null;
  edit_distance?: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  created_by: string;
  created_at: string;
  decided_by?: string | null;
  decided_at?: string | null;
}

export interface AiOutputList {
  rows: AiOutput[];
  total: number;
}

export interface AiAskRequest {
  entity_id: string;
  template_code: string;
  channel_code?: string;
  text?: string;
  document?: { name: string; content_base64: string };
  image_asset_ids?: string[];
}

export type AiRunStatus = "sample_pending" | "sample_approved" | "running" | "completed" | "failed" | "cancelled";

export interface AiRun {
  id: string;
  kind: "single" | "bulk" | "eval";
  template_code: string;
  template_version: number;
  task_type: TaskType;
  channel_code: string;
  selection: Record<string, unknown>;
  status: AiRunStatus;
  sample_entity_ids: string[];
  total: number;
  done: number;
  proposed: number;
  failed: number;
  needs_input: number;
  created_by: string;
  created_at: string;
  finished_at?: string | null;
  job_run_id?: string | null;
  error?: string | null;
  report: Record<string, unknown>;
}

export interface AiRunDetail extends AiRun {
  outputs: AiOutput[]; // first 200 (and the samples right after POST /api/ai/runs)
}

export interface AiRunList {
  rows: AiRun[];
  total: number;
}

export interface AiRunCreate {
  template_code: string;
  selection: { view_id?: string; entity_ids?: string[] };
  channel_code?: string;
}

export interface AiMetrics {
  template_code: string;
  template_version?: number | null;
  outputs: number;
  accepted: number;
  edited: number;
  rejected: number;
  pending: number;
  acceptance_rate: number | null;
  mean_edit_distance: number | null;
  rejection_reasons: { reason: string; count: number }[];
  tokens: { prompt: number; completion: number };
}

export interface EvalCase {
  id: string;
  entity_id: string;
  label: string;
  attribute_code: string;
  reference_text: string;
  created_at: string;
}

export type EvalRunStatus = "running" | "passed" | "blocked" | "failed";

export interface EvalRun {
  id: string;
  template_code: string;
  template_version: number;
  model: string;
  status: EvalRunStatus;
  cases: number;
  scores: { overlap: number; length_ok: number; grounded: number; voice_ok: number; composite: number };
  baseline_run_id?: string | null;
  baseline_composite?: number | null;
  delta?: number | null;
  threshold: number;
  mlflow_run_id?: string | null;
  created_by: string;
  created_at: string;
  finished_at?: string | null;
  error?: string | null;
  sample: { entity_id: string; label: string; reference: string; output: string; overlap: number }[];
}

export type QualityGrade = "A" | "B" | "C" | "D" | "E";

export interface QualitySettings {
  excluded_groups: string[];
  weights: Record<string, number>; // check code -> weight
  enabled_checks: string[];
  grade_bands: { A: number; B: number; C: number; D: number }; // minimum score per grade, E below D
}

export interface QualityCheck {
  code: string;
  label: string;
  passed: boolean;
  weight: number;
  details: string[];
}

export interface QualityScore {
  entity_id: string;
  channel_code: string; // "" = overall
  grade: QualityGrade;
  score: number;
  checks: QualityCheck[];
  computed_at: string;
}

export interface QualityDashboardRow {
  key: string;
  label: string;
  A: number;
  B: number;
  C: number;
  D: number;
  E: number;
  avg_score: number;
}

export type QualityDashboardBy = "family" | "season" | "channel";

/** Grid rows: `quality: {[channel_code or ""]: {grade, score}}` (GOV-03). */
export interface QualityCell {
  grade: QualityGrade;
  score: number;
}

/** Approval queue rows carry the originating run (AI-04); `runs` summarizes them for the Run filter. */
export interface ApprovalRunSummary {
  run_id: string;
  template_code: string;
  count: number;
}

// =====================================================================================
// Phase 5: marketplaces, feeds, Shopify sandbox (docs/api-contract-phase5.md)
// EXP-08, EXP-09, EXP-10, EXP-11, D-03, D-13
// =====================================================================================

export type FeedCaseTransform = "as_is" | "title" | "sentence" | "upper" | "lower";

/** One column of a template-based feed. `source` is an attribute code, a ref path, core.<field>, erp.<field>,
 * image:<n>, nrf_color, nrf_size or gtin. */
export interface FeedColumn {
  header: string;
  source: string;
  always_include: boolean;
  case_transform: FeedCaseTransform;
  value_map: Record<string, string>;
  required: boolean;
}

export type TransportKind = "download" | "sftp" | "email" | "api";
export type FeedFileFormat = "csv" | "xlsx" | "json";
export type RithumProgram = "nordstrom_dropship" | "targetplus";

export interface SftpSettings {
  host: string;
  port: number;
  path: string;
  username: string;
  secret_name: string; // app secret resource holding the password or key
  host_key: string; // pinned server key: ssh-keyscan line, bare base64 key, or "SHA256:<fingerprint>"
}

export interface EmailSettings {
  to: string[];
  subject: string;
}

export interface WalmartSettings {
  spec_version: string;
  product_type: string;
  max_items_per_feed: number;
  variant_attribute_names: string[];
}

export interface RithumSettings {
  supplier_id?: string | null;
  vpn_prefix?: string | null;
  program: RithumProgram;
  family_rules: boolean;
}

export interface ChannelTransport {
  transport: TransportKind;
  file_format: FeedFileFormat;
  feed_template_path?: string | null;
  feed_template_name?: string | null;
  header_row: number;
  feed_columns: FeedColumn[];
  sftp?: SftpSettings | null;
  email?: EmailSettings | null;
  walmart?: WalmartSettings | null;
  rithum?: RithumSettings | null;
}

/** POST /api/channels/{code}/feed-template response. */
export interface FeedTemplateUpload {
  feed_template_path: string;
  feed_template_name: string;
  columns: string[];
  schema_loaded: boolean;
}

export type DeliveryStatus = "delivered" | "skipped" | "failed";

export interface DeliveryResult {
  transport: string;
  status: DeliveryStatus;
  detail: string;
  at: string;
  files: string[];
}

/** `Publish.summary.walmart` (EXP-08). */
export interface WalmartFeedSummary {
  feed_ids: string[];
  status: string;
  next_poll_at?: string | null;
  polls: number;
}

export type SandboxMutationStatus = "planned" | "ok" | "error";

export interface SandboxMutation {
  kind: string;
  handle: string;
  fields: string[];
  status: SandboxMutationStatus;
  message?: string;
}

export interface SandboxProtectedCheck {
  handle: string;
  field: string;
  before: unknown;
  after: unknown;
  unchanged: boolean;
}

export interface SandboxReport {
  store: string;
  mode: "plan" | "executed";
  products: number;
  mutations: SandboxMutation[];
  protected_check: SandboxProtectedCheck[];
  errors: string[];
  at: string;
}

// =====================================================================================
// Phase 6: relationships, whole-product restore and change sets, digest settings, adapter
// error rates (docs/api-contract-phase6.md: DM-13, GOV-02, DM-07, DM-09, GOV-04)
// =====================================================================================

export type RelationshipDirection = "one_way" | "two_way";

export interface RelationshipType {
  code: string;
  label: string;
  direction: RelationshipDirection;
  level: "style" | "style_color";
  allows_quantity: boolean;
  enabled: boolean;
  sort_order: number;
  help_text?: string | null;
}

export interface RelationshipTarget {
  entity_id: string;
  label: string | null;
  style_number: string | null;
  color_code: string | null;
  lifecycle_status: string | null;
}

export interface Relationship {
  id: string;
  type_code: string;
  type_label: string;
  direction: RelationshipDirection;
  /** Set on the style and shown on its colors, where it is read only. */
  inherited: boolean;
  quantity?: number | null;
  created_by: string;
  created_at: string;
  target: RelationshipTarget;
  /** The target is discontinued or gone. */
  broken: boolean;
}

export interface RelationshipAddRequest {
  type_code: string;
  targets?: string[];
  paste?: string;
  quantity?: number;
}

export interface RelationshipAddResult {
  created: number;
  skipped: { token: string; reason: string }[];
  rows: Relationship[];
}

export type ChangeSetKind = "edit" | "import" | "bulk" | "ai" | "ingest" | "rule" | "restore" | "rollback" | "approval" | string;

export interface ChangeSet {
  id: string;
  kind: ChangeSetKind;
  created_by: string;
  created_at: string;
  description?: string | null;
  source_ref?: string | null;
  rolled_back_at?: string | null;
  /** History rows in the set. */
  changes?: number | null;
}

export interface ChangeSetList {
  rows: ChangeSet[];
  total: number;
}

export type RestoreToOutcome = "approved" | "draft" | "rejected" | "unchanged" | "skipped";

export interface RestoreToResult {
  change_set_id: string;
  restored: number;
  results: { attribute_code: string; channel_code?: string | null; outcome: RestoreToOutcome; message?: string | null }[];
}

export interface RollbackResult {
  restored: number;
  /** Values touched since the set was written; they are listed, not reverted. */
  manual: { entity_id: string; attribute_code: string; reason: string }[];
  [k: string]: unknown;
}

export type DigestFrequency = "daily" | "weekly" | "off";

export interface MeSettings {
  email: string;
  digest_frequency: DigestFrequency;
  last_digest_at?: string | null;
}

export interface AdapterErrorRate {
  adapter: string;
  window_days: number;
  calls: number;
  errors: number;
  /** 0..1, or null when the adapter made no calls in the window. */
  error_rate: number | null;
  last_error_at?: string | null;
  last_error?: string | null;
}
