# PIM API contract, Phase 2 additions

Extends `docs/api-contract.md`. Same conventions: `/api` prefix, JSON, identity headers, server-side permission
checks. Phase 2 covers imports (IMP-01 to IMP-08, IMP-12), bulk actions (DM-04), workflows (DM-07), comments and
notifications (DM-09), carryover (DM-12), product compare (DM-06), and the rules engine (GOV-01).

## Common shapes

```ts
type BatchStatus = "uploaded" | "mapped" | "validated" | "matched" | "reviewed" | "committing" | "committed" | "failed" | "rolled_back";
type MatchStatus = "matched" | "new" | "ambiguous" | "unmatched";
type RowAction = "create" | "update" | "skip";

interface ImportSource { code: string; label: string; kind: "supplier" | "retailer" | "shopify" | "worksheet" | "other";
  default_policy: { unmatched: "create" | "update_only" | "create_under_match"; on_error: "skip_row" | "skip_value" } }

interface Transform { op: "trim" | "split" | "concat" | "regex_extract" | "value_replace" | "unit_convert" | "html_clean" | "date_parse" | "case";
  args: Record<string, unknown> }   // split: {delimiter, index}; concat: {separator}; regex_extract: {pattern, group}; value_replace: {map}; unit_convert: {from, to}; date_parse: {formats[]}; case: {mode}

interface ColumnMapping { target: string; sources: string[]; transforms: Transform[]; required?: boolean; skip?: boolean }
  // target is an attribute code, or a core key: style_number, color_code, size, sku, upc, family_code, or "skip"

interface MappingTemplate { id: string; source_code: string; name: string; structure_signature: string; header_row: number;
  group_header_row?: number | null; data_start_row: number; columns: ColumnMapping[]; match_keys: string[];
  unmatched_policy: "create" | "update_only" | "create_under_match"; level: Level; version: number; created_by: string }

interface MappingSuggestion { column: string; target: string; confidence: number; reason: string }   // hidden below threshold server-side

interface ImportFile { index: number; name: string; sheet?: string | null; header_row: number; group_header_row?: number | null;
  data_start_row: number; rows: number; columns: { name: string; group?: string | null; samples: string[] }[]; precedence: number }

interface ImportBatch { id: string; status: BatchStatus; source_code: string; template_id?: string | null; level: Level;
  created_by: string; created_at: string; files: ImportFile[]; mapping: ColumnMapping[]; match_keys: string[];
  options: { on_error: "skip_row" | "skip_value"; unmatched_policy: string; keyless_name_column?: string | null };
  stats: { rows: number; ok: number; warnings: number; errors: number; matched: number; new: number; ambiguous: number; unmatched: number;
           creates: number; adds: number; changes: number; conflicts: number; skipped: number; placeholders_removed: Record<string, number> };
  worksheet_id?: string | null; change_set_id?: string | null; error?: string | null; report?: Record<string, unknown> }

interface ImportRow { id: string; file_index: number; row_number: number; raw: Record<string, string>; mapped: Record<string, unknown>;
  match_status: MatchStatus; match_key_used?: string | null; entity_id?: string | null; entity_label?: string | null;
  candidates: { entity_id: string; label: string; score: number; reason: string }[]; errors: { column?: string; attribute?: string; message: string }[];
  warnings: { column?: string; attribute?: string; message: string }[]; action: RowAction }

interface ImportConflict { id: string; row_id: string; entity_id: string; entity_label: string; attribute_code: string; channel_code?: string | null;
  current: { value: unknown; source_type: string; set_by?: string; set_at?: string; approval_state: string };
  incoming: { value: unknown; source: string; file?: string; row_number?: number }; policy: string;
  status: "open" | "accepted" | "rejected" | "edited"; resolved_value?: unknown }

interface BulkAction { id: string; kind: "set_value" | "clear_value" | "add_option" | "remove_option" | "find_replace" | "copy_attribute" |
  "change_family" | "assign_workflow" | "run_ai" | "send_for_approval"; selection: { view_id?: string; entity_ids?: string[]; level: Level };
  params: Record<string, unknown>; status: "preview" | "queued" | "running" | "succeeded" | "failed" | "rolled_back";
  preview: { total: number; sample: { entity_id: string; label: string; attribute_code?: string; before: unknown; after: unknown }[] };
  report: { changed: number; skipped: number; failed: number; items: { entity_id: string; label: string; outcome: string; reason?: string }[] };
  change_set_id?: string | null; created_by: string; created_at: string }

interface WorkflowItem { id: string; workflow_code: string; workflow_label: string; entity_id: string; entity_label: string;
  step: { id: string; position: number; label: string; kind: "enrich" | "review"; role_code: string; group_codes: string[]; channel_codes: string[] } | null;
  steps_total: number; state: "open" | "done" | "cancelled"; due_at?: string | null; overdue: boolean; assigned_role?: string | null; assigned_email?: string | null;
  history: { at: string; event: string; step?: string; by?: string; comment?: string }[] }

interface Comment { id: string; entity_id: string; attribute_code?: string | null; author: string; body: string; mentions: string[];
  created_at: string; resolved: boolean }
interface Notification { id: string; kind: "mention" | "workflow" | "approval" | "import" | "bulk" | "conflict"; title: string; body?: string | null;
  link?: string | null; created_at: string; read_at?: string | null }

interface Rule { id: string; code: string; label: string; priority: number; enabled: boolean; status: "draft" | "active";
  trigger: "on_save" | "on_import" | "nightly" | "all"; level: Level;
  condition: { all?: Condition[]; any?: Condition[] }; actions: RuleAction[]; brand_scopes: string[];
  last_preview?: RulePreview | null; activated_at?: string | null; activated_by?: string | null }
interface Condition { field: string; op: "eq" | "neq" | "contains" | "in" | "empty" | "not_empty" | "gt" | "lt" | "regex"; value?: unknown }  // field = attr:<code> or core key
interface RuleAction { op: "set" | "clear" | "copy" | "concatenate" | "calculate" | "set_approval_state" | "add_to_workflow" | "trigger_ai";
  target?: string; value?: unknown; source?: string; parts?: string[]; separator?: string; expression?: string; workflow_code?: string; task_type?: string }
interface RulePreview { sample: { entity_id: string; label: string; brand_scopes: string[]; changes: { attribute_code: string; before: unknown; after: unknown }[] }[];
  brands_covered: string[]; matched_total: number; suspicious_constants: { attribute_code: string; value: unknown; brands: string[]; families: string[] }[];
  ok_to_activate: boolean; blockers: string[] }
```

## Endpoints

### Imports (IMP-01 to IMP-08)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/imports/sources` | `ImportSource[]` |
| POST / PUT | `/api/imports/sources`, `/api/imports/sources/{code}` | admin upsert |
| GET | `/api/imports/templates?source=` | `MappingTemplate[]` |
| POST / PUT / DELETE | `/api/imports/templates`, `/api/imports/templates/{id}` | save a template from a batch's mapping or edit one |
| GET | `/api/imports/batches?status=&source=&page=` | `{rows: ImportBatch[], total}` (import history, IMP-07) |
| POST | `/api/imports/batches` | multipart: `file` (one or more, repeatable), fields `source_code`, `level` (default `style_color`). Parses, stores to the import volume, detects header rows, recognizes keyed worksheets (IMP-12), auto-applies a matching template by structure signature. Returns `ImportBatch` (status `uploaded`, or `mapped` when a template applied) |
| POST | `/api/imports/batches/{id}/files` | add another file to the batch (mixed sources); body as above |
| POST | `/api/imports/batches/{id}/shopify-pull` | IMP-08: build the batch rows from a Shopify snapshot (API) or an uploaded product CSV (`file`) |
| GET | `/api/imports/batches/{id}` | `ImportBatch` |
| GET | `/api/imports/batches/{id}/suggest-mapping` | `MappingSuggestion[]` for unmapped columns (IMP-02); never auto-applied |
| PUT | `/api/imports/batches/{id}/mapping` | body `{mapping: ColumnMapping[], match_keys: string[], options, template_id?, precedence?: number[]}` → batch (status `mapped`); 400 lists required attributes still unmapped |
| GET | `/api/imports/batches/{id}/value-mappings` | IMP-03: `{lists: [{attribute_code, list_code, values: [{raw, count, option_code?: string|null, suggested?: string|null, confidence?: number}]}]}` |
| PUT | `/api/imports/batches/{id}/value-mappings` | body `{items: [{list_code, raw, option_code}]}` remembered per source |
| POST | `/api/imports/batches/{id}/validate` | runs validation (IMP-04) → batch with stats; rows carry errors and warnings |
| GET | `/api/imports/batches/{id}/rows?status=&match=&page=&page_size=` | `{rows: ImportRow[], total}`; `status` in `ok|warning|error` |
| GET | `/api/imports/batches/{id}/error-file` | downloadable file in the source layout with an added Errors column |
| POST | `/api/imports/batches/{id}/match` | runs matching (IMP-05) → batch; rows get match_status and candidates |
| PUT | `/api/imports/batches/{id}/rows/{row_id}` | body `{entity_id?: string|null, action?: RowAction}` confirm an assisted match or set the row action |
| POST | `/api/imports/batches/{id}/review` | computes the diff (IMP-06 survivorship, IMP-07) → batch with stats and `diff: {creates: [...], adds: [...], changes: [{entity_id, label, attribute_code, old, new}], conflicts: number, skipped: [...]}` (first 200 of each) |
| GET | `/api/imports/batches/{id}/conflicts?status=` | `{rows: ImportConflict[], total}` |
| POST | `/api/imports/conflicts/decide` | body `{conflict_ids: string[], decision: "accept" | "reject" | "edit", value?: unknown}` |
| POST | `/api/imports/batches/{id}/commit` | enqueues the commit job (inline locally) → batch (status `committing` then `committed`) |
| POST | `/api/imports/batches/{id}/rollback` | IMP-07 per-batch rollback → `{restored: n, manual: [{entity_id, label, attribute_code, reason}]}` |
| GET | `/api/imports/batches/{id}/report` | JSON report (counts, placeholders removed per column, skipped rows) |

### Keyed worksheets (IMP-12)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/worksheets` | body `{selection: {view_id?, entity_ids?, level}, group_codes: string[], include_erp_context: boolean}` → `{id, file_name, rows, url: "/api/worksheets/{id}/file"}` |
| GET | `/api/worksheets` | history `[{id, created_by, created_at, rows, group_codes, file_name}]` |
| GET | `/api/worksheets/{id}/file` | XLSX download |

Returned worksheets are uploaded through `POST /api/imports/batches` with `source_code=worksheet`; the server recognizes them by the embedded id, skips mapping, matches by key, and rejects edits to locked columns.

### Bulk actions (DM-04)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/bulk/preview` | body `{kind, selection, params}` → `BulkAction` (status `preview`) with first 20 changes and total |
| POST | `/api/bulk/{id}/run` | enqueue → `BulkAction` (status `queued|running|succeeded`) |
| GET | `/api/bulk?page=` | history |
| GET | `/api/bulk/{id}` | detail with report |
| POST | `/api/bulk/{id}/rollback` | reverts the action's change set |

`params` per kind: set_value `{attribute_code, value, channel_code?}`; clear_value `{attribute_code, channel_code?}`; add_option / remove_option `{attribute_code, option_codes[]}`; find_replace `{attribute_code, find, replace, regex?: bool, case_sensitive?: bool}`; copy_attribute `{from_attribute, to_attribute}`; change_family `{family_code}`; assign_workflow `{workflow_code}`; run_ai `{task_type, target_attribute, template_code?}`; send_for_approval `{}`.

### Workflows (DM-07, DM-12)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/workflows` | definitions with steps |
| PUT | `/api/workflows/{code}` | admin upsert definition `{label, enabled, entry_rule, steps: [{position, label, kind, role_code, group_codes, channel_codes, due_in_days}]}` (max 20 steps) |
| GET | `/api/workflows/inbox?scope=mine|role|all&overdue=` | My Work: `{rows: WorkflowItem[], total}` |
| GET | `/api/workflows/manager` | `{by_step: [{workflow_code, step_label, open, overdue, oldest_days}], by_age: [{bucket: "0-2"|"3-7"|"8-14"|"15+", count}]}` |
| POST | `/api/workflows/items/{id}/advance` | body `{comment?}` completes the current step (requires rights on the step's role or admin) |
| POST | `/api/workflows/items/{id}/reject` | body `{to_step_id, comment, attribute_comments?: [{attribute_code, comment}]}` |
| POST | `/api/workflows/items/{id}/assign` | body `{email}` |
| POST | `/api/workflows/items/{id}/cancel` | |
| POST | `/api/workflows/start` | body `{workflow_code, entity_ids: string[]}` |
| GET | `/api/products/{id}/workflow` | open items for a product |
| GET | `/api/products/{id}/carryover` | DM-12: `{siblings: [{entity_id, label, color_code, approved_values: number, last_approved_at}], steps_skippable: string[]}` |
| POST | `/api/products/{id}/carryover` | body `{from_entity_id, attribute_codes?: string[]}` copies the sibling's approved style-color values as drafts → `{drafts: n}` |

### Comments and notifications (DM-09)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/products/{id}/comments` | `Comment[]` (style-color comments include the style's) |
| POST | `/api/products/{id}/comments` | body `{body, attribute_code?}`; `@email` or `@first.last` tokens become mentions and notify |
| POST | `/api/comments/{id}/resolve` | |
| GET | `/api/notifications?unread=true` | `{rows: Notification[], unread: n}` |
| POST | `/api/notifications/read` | body `{ids?: string[]}` (all when omitted) |

### Compare (DM-06)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/products/compare?a=&b=&channel=` | `{attributes: AttributeDefinition[], a: ProductRow, b: ProductRow}` with values resolved for both (and channel overrides when `channel` is given) |
| POST | `/api/products/{id}/copy-from` | body `{from_entity_id, attribute_codes: string[], channel_code?}` copies values (respects rights, lands as approved or draft) |

### Rules (GOV-01, GOV-06)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/rules` | `Rule[]` |
| POST / PUT / DELETE | `/api/rules`, `/api/rules/{id}` | admin |
| POST | `/api/rules/{id}/preview` | runs on 20 sample products from at least 3 brand scopes → `RulePreview` (stored as last_preview) |
| POST | `/api/rules/{id}/activate` | requires a preview with `ok_to_activate` (or `{force: true, reason}` logged) |
| POST | `/api/rules/{id}/run` | run now over the rule's level → `{affected, report}` |
| GET | `/api/rules/runs?rule_id=` | history |
