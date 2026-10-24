# PIM API contract (v1)

All endpoints are under `/api`. JSON in and out. The React SPA is served from `/` by the same FastAPI app (ARC-01).
Identity comes from Databricks App headers (`X-Forwarded-Email`, `X-Forwarded-User`, `x-forwarded-access-token`) [D7];
in local development `PIM_DEV_USER_EMAIL` and `PIM_DEV_USER_ROLES` stand in. Every write is permission-checked on the
server (P7). Errors return `{"detail": "..."}` with 400, 403, 404, or 409.

## Common shapes

```ts
type Level = "style" | "style_color" | "sku";
type ApprovalState = "draft" | "proposed" | "approved" | "rejected";
type SourceType = "erp" | "import" | "user" | "ai" | "rule" | "default";

interface AttributeDefinition {
  code: string; label: string;
  data_type: "text"|"rich_text"|"number"|"boolean"|"date"|"single_select"|"multi_select"|"asset_ref"|"product_ref"|"reference_entity";
  level: Level | string;            // "ref:print" etc. for reference entity attributes (DM-11)
  group_code: string; sort_order: number;
  option_list_code?: string | null; reference_type_code?: string | null;
  unit?: string | null; validation: { min_length?: number; max_length?: number; regex?: string; min?: number; max?: number };
  channel_scopable: boolean; allows_not_applicable: boolean; default_value?: string | null;
  owner_role?: string | null; owner_person?: string | null;
  status: "proposed" | "confirmed" | "deprecated";
  source_of_truth: "erp" | "plm" | "pim" | "channel";
  help_text?: string | null; example_value?: string | null;
}
interface AttributeGroup { code: string; label: string; owning_role: string; sort_order: number; read_only: boolean; }
interface OptionList { code: string; label: string; kind: "option" | "size_scale"; size_group?: string|null;
  values: { code: string; label: string; sort_order: number; channel_mappings: Record<string,string> }[] }
interface Family { code: string; label: string; group_codes: string[] }
interface Channel { code: string; label: string; adapter: string; kind: "dtc"|"marketplace"|"retailer"; enabled: boolean;
  requirement_set_code?: string|null; protected_fields: string[]; config: Record<string, unknown>; version: number }

interface ValueCell {
  value: unknown;                   // typed JSON value; null when empty
  raw_value?: string | null;        // ERP raw value when a normalized mapping applied (IMP-11)
  not_applicable?: boolean;
  source_type: SourceType; source_ref?: string|null;
  set_by?: string|null; set_at?: string|null;       // ISO timestamps
  ai_generated: boolean; approval_state: ApprovalState; version: number;
  inherited_from?: { level: Level; entity_id: string } | null;   // DM-01 strict ownership
  read_only: boolean; read_only_reason?: "erp"|"inherited"|"no_rights"|"deprecated"|null;
  is_default?: boolean;             // GOV-06
  draft?: { value: unknown; set_by: string; set_at: string } | null;   // DM-08 pending draft for this user
}
interface ProductRow {
  entity_id: string; level: Level; entity_type: "product" | "prepack";
  style_number: string; color_code?: string|null; size?: string|null; sku?: string|null; upc?: string|null;
  family_code?: string|null; lifecycle_status: "active"|"discontinued"|"new"; brand_scopes: string[];
  parent_id?: string|null; label: string;
  values: Record<string, ValueCell>;
  completeness: Record<string, number>;                  // channel_code -> percent 0..100
  readiness: Record<string, { ready: boolean; eligible: boolean; missing_attributes: string[]; missing_shots: string[]; mapping_gaps: string[]; invalid: string[]; reasons: string[] }>;
}
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | `{status, version, erp_last_load_at, erp_stale, erp_stale_threshold_hours}` (IMP-09 header banner) |
| GET | `/api/me` | `{email, user_id, roles[], permissions[], data_rights: {group_code: "none"|"view"|"edit"|"approve"}, channel_rights: {channel_code: {run: bool, edit_profile: bool}}, brand_scopes[]}` |
| GET | `/api/metadata/attributes?level=&group=` | `AttributeDefinition[]` |
| POST / PUT | `/api/metadata/attributes` / `/api/metadata/attributes/{code}` | admin upsert |
| GET / PUT | `/api/metadata/groups` | `AttributeGroup[]` |
| GET | `/api/metadata/option-lists` | `OptionList[]` (values included) |
| PUT | `/api/metadata/option-lists/{code}` | admin upsert incl. values |
| GET | `/api/metadata/families` | `Family[]` |
| GET | `/api/metadata/channels` | `Channel[]` |
| PUT | `/api/metadata/channels/{code}` | admin upsert |
| GET | `/api/metadata/reference-types` | `[{code, label, attribute_codes[]}]` |
| GET | `/api/reference-entities/{type}?q=&page=&page_size=` | `{rows: [{id, type_code, code, label, values: Record<string, ValueCell>, linked_products: number}], total}` |
| GET / PUT | `/api/reference-entities/{type}/{id}` | detail; PUT body `{values: {code: value}}` returns `{impact: {products: n, channels: string[]}, ...}`; pass `?confirm=true` to save |
| POST | `/api/products/query` | body `{level, page, page_size, sort: [{field, dir}], filters: [{field, op, value}], search, columns: string[], view_id?}`; `field` is `attr:<code>` or a core field (`style_number`, `color_code`, `size`, `sku`, `upc`, `family_code`, `lifecycle_status`, `completeness:<channel>`, `readiness:<channel>`, `approval_state`, `ai_generated`, `missing_images`, `import_batch`); ops: `eq, neq, contains, in, empty, not_empty, gt, lt, gte, lte`. Returns `{rows: ProductRow[], total, page, page_size}` |
| GET | `/api/products/{entity_id}` | `{entity: ProductRow, ancestors: ProductRow[], children: ProductRow[], groups: [{group: AttributeGroup, attributes: AttributeDefinition[]}], images: ImageLink[], history_count}` |
| PUT | `/api/products/{entity_id}/values` | body `{channel_code?: string|null, values: {attr_code: value}}` → `{results: [{attribute_code, outcome: "approved"|"draft"|"rejected", message?}]}` |
| POST | `/api/products/{entity_id}/values/clear` | body `{attribute_codes: string[], channel_code?}` |
| GET | `/api/products/{entity_id}/history?attribute_code=&user=&page=` | `{rows: [{id, attribute_code, channel_code, old_value, new_value, source_type, set_by, set_at, change_set_id, reason}], total}` |
| POST | `/api/products/{entity_id}/history/{history_id}/restore` | GOV-02 single attribute restore |
| GET | `/api/products/{entity_id}/tree` | `{root: ProductRow, nodes: [{row: ProductRow, children: [...]}]}` |
| GET | `/api/views?level=` | `[{id, name, level, owner_email, shared_with: "private"|"role:<role>"|"everyone", is_default, definition: {filters, columns, sort, search}}]` |
| POST / PUT / DELETE | `/api/views`, `/api/views/{id}` | DM-02 |
| GET | `/api/dashboard` | `{open_tasks: n, overdue: n, blocking_launches: [{entity_id, label, launch_date, days_left, channels_not_ready[]}], readiness_by_channel: [{channel_code, label, ready, not_ready, ineligible}], recent_ingest: [{id, started_at, finished_at, status, rows_read, created, updated, discontinued, placeholders_removed}], recent_packages: [{id, channel_code, created_at, status, products, changes}], ai_pending: n, conflicts_open: n}` |
| GET | `/api/approvals?group=` | DM-08 queue: `{groups: [{submitter, items: [{entity_id, label, attribute_code, current, proposed, set_at, draft_id}]}]}` |
| POST | `/api/approvals/decide` | body `{draft_ids: string[], decision: "approve"|"reject", comment?}` |
| GET | `/api/packages?channel=` | EXP-13 packages `[{id, channel_code, status: "pending"|"building"|"ready"|"failed"|"reconciled", created_by, created_at, snapshot_at, products, changes, files: [{name, size}]}]` |
| POST | `/api/packages` | body `{channel_code, selection: {view_id?, entity_ids?, changed_since?}, snapshot: {mode: "api"|"csv_upload"}}` → package |
| GET | `/api/packages/{id}` | package + `rows: [{handle, title, field, current_value, proposed_value, source_type, approval_state, ai_generated, include, note}]` + `summary` |
| GET | `/api/packages/{id}/files/{name}` | file download |
| POST | `/api/packages/{id}/snapshot-upload` | multipart Shopify product CSV (snapshot mode csv_upload) |
| POST | `/api/packages/{id}/review-upload` | multipart edited review workbook; regenerates CSVs |
| POST | `/api/packages/{id}/reconcile` | compares against a fresh snapshot; marks rows applied / not_applied / changed_differently |
| GET | `/api/images/queue?kind=candidates|missing|unparsed&channel=` | IMG-05 queues |
| GET | `/api/products/{entity_id}/images` | `{slots: [{shot_type, required_by: string[], link?: ImageLink}], candidates: ImageLink[]}` |
| POST | `/api/images/links/{link_id}/confirm` `/reject` | body `{shot_type?}` |
| GET | `/api/admin/erp-defects?page=` | IMP-11 report |
| GET | `/api/admin/attribute-usage` | GOV-07 report |
| GET / POST / DELETE | `/api/admin/user-roles` | role assignments with brand scopes |
| GET | `/api/admin/telemetry` | GOV-04: job runs, adapter errors, AI spend |
| GET | `/api/jobs/runs?kind=` | job run list |
| POST | `/api/jobs/ingest/run` | trigger Style Master ingest (admin) |

```ts
interface ImageLink { id: string; asset_id: string; entity_id: string; shot_type?: string|null; tier: 1|2|3; confidence: number;
  status: "proposed"|"confirmed"|"rejected"; thumbnail_url?: string; filename: string; width?: number; height?: number; sort_order: number }
```

## Implementation notes (as built)

These refinements were agreed between the backend and the frontend during the build and are what the code does:

- `POST /api/products/query` `columns` takes grid field keys: core fields, `attr:<code>`, `completeness:<channel>`,
  `readiness:<channel>`. Only `attr:` keys cause attribute values to be resolved; readiness and completeness are always
  returned for the page. An explicit list with no `attr:` keys returns no attribute values (cheapest page).
- `GET /api/products/{id}` accepts `?channel=<code>` (alias of `channel_code`) and resolves that channel's overrides into `values`.
- Package rows carry both `reconcile_status` and `reconcile_result` (same value). `summary.by_field` and
  `summary.by_product` are lists of `{field|handle, count}`; `summary.skipped` rows carry `handle` (the product label),
  `entity_id`, `label`, and `reason`; `summary.intentional_clears` lists `{handle, field}`.
- `GET /api/images/queue` returns `{kind, total, rows}`. Candidate rows are `ImageLink` plus `proposed_label` and
  `proposed_entity_id`; missing rows carry `style_number`, `color_code`, `missing_shots`; unparsed rows carry `reason`.
- `GET /api/admin/erp-defects` rows include `issue` (same as `reason`), `seen_at`, `style_number`, `color_code`, plus `page` and `page_size`.
- `GET /api/admin/attribute-usage` rows include `total`, `used_by_channels`, `last_set_at` (aliases of `entities`, `mapped_channels`, `last_edit`). `fill_rate` is 0 to 100.
- `GET /api/admin/user-roles` returns an array of `{id, email, role, role_code, brand_scopes}`; `POST` accepts `role` or `role_code`;
  `DELETE /api/admin/user-roles` accepts a JSON body `{id?, email, role}`. The roles and brand scope catalog is at `GET /api/admin/roles`.
- `GET /api/admin/telemetry` returns `{job_runs, events, adapter_errors, ai_spend, ai}`.
- `PUT /api/metadata/groups` accepts the full `AttributeGroup[]`; `PUT /api/views/{id}` accepts partial fields.
- `GET /api/products/{id}/tree` returns `{root, nodes}` where `nodes` are the root's children (the root is rendered once).
- Multipart uploads use the form field `file`.
