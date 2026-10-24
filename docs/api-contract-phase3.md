# PIM API contract, Phase 3 additions

Extends `docs/api-contract.md` and `docs/api-contract-phase2.md`. Phase 3 covers channel exports (EXP-02 target
schemas, EXP-04 validation and dry runs, EXP-05 publish history and retailer feedback, EXP-06 delta and scheduled
exports, EXP-12 forced eligibility with approval) and images (IMG-03 tier 3 AI candidates, IMG-05 ordering and
technical checks, IMG-06 Air write-back and AI-generated flag, IMG-07 renditions). Direct Shopify writes (EXP-07)
stay behind `PIM_FEATURE_SHOPIFY_DIRECT_WRITE=false`; the `publish` path for that channel produces an EXP-13 package.

## Common shapes

```ts
interface TargetField { name: string; type: "string"|"number"|"integer"|"boolean"|"enum"|"array"|"object"|"date";
  required: boolean; enum?: string[]; max_length?: number; min?: number; max?: number; group?: string|null;
  description?: string|null; path?: string|null }   // path = JSON pointer inside the payload for API channels
interface TargetSchema { source: "walmart_spec"|"mirakl"|"shopify"|"retailer_xlsx"|"manual"; version?: string|null;
  loaded_at: string; product_type?: string|null; fields: TargetField[]; raw_available: boolean }
interface SchemaDiff { added: TargetField[]; removed: TargetField[]; required_changed: { name: string; before: boolean; after: boolean }[];
  enum_changed: { name: string; added: string[]; removed: string[] }[] }

interface ChannelTransform { target: string; op: "concatenate"|"format"|"unit_convert"|"conditional"|"case"|"truncate";
  args: Record<string, unknown> }   // concatenate {parts[], separator}; format {template "{{attr.x}} ..."}; unit_convert {from,to};
                                    // conditional {when: Condition, then: value, else?: value}; case {mode}; truncate {max_length}
interface ImageProfile { shot_types: string[]; width?: number; height?: number; format: "jpg"|"png"|"webp"; pad_to_ratio?: string|null;
  background?: "white"|"transparent"|null; naming?: string|null }   // naming template e.g. "{{style_number}}-{{color_code}}-{{seq}}"

interface PayloadIssue { entity_id: string; label: string; field?: string|null; attribute_code?: string|null; message: string;
  kind: "missing_required"|"invalid_type"|"enum"|"length"|"schema"|"transform"|"image"; severity: "error"|"warning" }
interface Publish { id: string; channel_code: string; channel_version: number; kind: "dry_run"|"package"|"publish"|"scheduled";
  mode: "delta"|"full"; status: "running"|"completed"|"failed"|"skipped"|"submitted"|"accepted"|"partial"|"rejected";
  created_by: string; created_at: string; finished_at?: string|null; product_count: number; valid_count: number; invalid_count: number;
  selection: Record<string, unknown>; files: { name: string; size: number; kind: string }[]; summary: Record<string, unknown>;
  external_batch_id?: string|null; error?: string|null }
interface PublishItem { id: string; entity_id: string; label: string; external_id?: string|null;
  status: "pending"|"valid"|"invalid"|"submitted"|"accepted"|"rejected"|"in_review"; issues: PayloadIssue[];
  errors: { message: string; field?: string|null; attribute_code?: string|null; kind: "internal"|"external" }[]; updated_at: string }
interface ChannelHealth { channel_code: string; publishes: number; products_sent: number; accepted: number; rejected: number; in_review: number;
  health_score: number|null; last_publish_at?: string|null; last_success_at?: string|null; open_rejections: number;
  top_errors: { message: string; count: number; kind: "internal"|"external" }[] }
interface ExportSchedule { enabled: boolean; mode: "delta"|"full"; every_hours?: number|null; at_hour?: number|null; at_minute?: number;
  timezone: string; view_id?: string|null; last_run_at?: string|null; last_result?: string|null }

interface EligibilityOverride { id: string; entity_id: string; channel_code: string; reason: string; approved_by: string; created_at: string; expires_at?: string|null }

interface ImageLink { /* Phase 1 shape plus */ rule_failures: Record<string, string[]>; ai_generated_image: boolean; evidence: Record<string, unknown> }
interface Rendition { asset_id: string; version_id?: string|null; channel_code: string; url: string; width?: number|null; height?: number|null;
  format: string; source: "air_cdn"|"job"; created_at: string }
```

## Endpoints

### Target schemas and mappings (EXP-01, EXP-02)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/channels/{code}/schema` | `TargetSchema` (empty `fields` when none loaded) |
| POST | `/api/channels/{code}/schema/refresh` | multipart optional `file` (Walmart spec JSON, Mirakl H11/PM11/VL11 CSV or ZIP, retailer XLSX template, Shopify metafield definitions JSON) or no file to pull from the adapter (Walmart spec API, Shopify Admin API). Query `product_type` for Walmart. Returns `{schema: TargetSchema, diff: SchemaDiff}` against the previously loaded schema; the channel version increments |
| GET | `/api/channels/{code}/schema/diff` | last refresh diff |
| GET | `/api/channels/{code}/mapping` | `{attribute_mapping: Record<string,string> (PIM source such as `product_title`, `fabric.fabric_story` or `core.style_number` -> target field name, as the Phase 1 seeds), transforms: ChannelTransform[], value_mappings: {attribute_code, list_code, mapped: number, unmapped: string[]}[], gaps: {required_fields_unmapped: string[], mapped_fields_missing_in_schema: string[]}}` |
| PUT | `/api/channels/{code}/mapping` | body `{attribute_mapping, transforms, image_profile?: ImageProfile}` (requires edit_profile right, RBAC-03); bumps channel version |

### Validation, dry runs, publishes (EXP-04, EXP-05, EXP-06)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/channels/{code}/dry-run` | body `{selection: {view_id?, entity_ids?, changed_since?}, mode: "delta"|"full", preview: number (default 5)}` → `Publish` (kind dry_run) with files (payload in the channel file format, validation report CSV) and `summary.preview: object[]` (first N payloads) |
| POST | `/api/channels/{code}/publish` | same body; requires run right. For `transport: package` channels this creates an EXP-13 package and returns a `Publish` whose `summary.package_id` points to it; for API adapters with `send` enabled it validates, writes the payload, calls the adapter, and stores `external_batch_id` |
| GET | `/api/publishes?channel=&kind=&page=` | `{rows: Publish[], total}` |
| GET | `/api/publishes/{id}` | `Publish` plus `items: PublishItem[]` (first 500) |
| GET | `/api/publishes/{id}/items?status=&page=` | `{rows: PublishItem[], total}` |
| GET | `/api/publishes/{id}/files/{name}` | download |
| POST | `/api/publishes/{id}/feedback` | multipart `file` (retailer error report CSV, JSON, or XLSX with a product id column and a message column) or no file to poll the adapter. Maps messages to attributes through the channel mapping, tags each `internal` or `external`, updates item statuses, notifies the owning role's users for rejections. Returns `{updated: n, accepted: n, rejected: n, in_review: n}` |
| GET | `/api/channels/{code}/health` | `ChannelHealth` |
| GET | `/api/channels/{code}/delta?view_id=` | `{changed: n, sample: {entity_id, label, reasons: string[]}[]}` products that would go in a delta run (values, images, or readiness changed since the last successful publish) |
| GET / PUT | `/api/channels/{code}/schedule` | `ExportSchedule` (PUT requires edit_profile) |
| POST | `/api/channels/{code}/schedule/run-now` | runs the scheduled export once; `{status: "started"|"skipped", reason?}` (skipped when a run is in progress, EXP-06) |

### Eligibility (EXP-12)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/products/{id}/eligibility` | `{channels: {channel_code: {eligible: boolean, reasons: string[], override?: EligibilityOverride|null}}}` |
| POST | `/api/products/{id}/eligibility-override` | body `{channel_code, reason, expires_at?}` (PIM Admin only; logged) → `EligibilityOverride` |
| DELETE | `/api/eligibility-overrides/{id}` | |

### Images (IMG-03, IMG-05, IMG-06, IMG-07)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/products/{id}/images` | Phase 1 shape; links now include `rule_failures` per channel and `ai_generated_image`; response adds `rules: {channel_code: image_rules}` |
| PUT | `/api/products/{id}/images/order` | body `{link_ids: string[]}` sets sort order; the first confirmed link is the main image |
| POST | `/api/images/links/{id}/confirm` | as before; also triggers the Air write-back (IMG-06) best-effort and reports `written_back: boolean` |
| PUT | `/api/images/assets/{asset_id}` | body `{ai_generated_image: boolean}` |
| POST | `/api/images/assets/{asset_id}/ai-candidates` | IMG-03 tier 3 on demand for one asset → `{candidates: ImageLink[]}` (proposed, never confirmed); 409 when `PIM_FEATURE_IMAGE_AI_MATCH` is off |
| GET | `/api/images/queue?kind=candidates|missing|unparsed|failing_rules&channel=` | adds `failing_rules`: confirmed links whose asset fails the channel's technical rules |
| GET | `/api/images/assets/{asset_id}/renditions?channel=` | `Rendition[]` (created on demand through Air CDN transforms, else queued for the resize job) |
| POST | `/api/images/renditions/refresh` | body `{entity_ids?: string[], channel_code}` → `{created: n, queued: n}` |
