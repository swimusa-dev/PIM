# PIM API contract, Phase 6 additions (closing phase)

Extends the Phase 1 to 5 contracts. Phase 6 closes the requirements the spec's build order left Partial, Seam or
Not started and that can be built without the Swim USA workspace: DM-13 product relationships, GOV-02 whole-product
restore and change-set rollback as a unit (with hot history retention), DM-07 and DM-09 digest email with a per-user
frequency, IMP-02 AI mapping suggestions behind a flag, GOV-04 adapter error rates, and the resolved ARC-05 stubs.
Layer still owns Shopify cross-sell data (D-09): relationships never write a Shopify field.

## Common shapes

```ts
interface RelationshipType { code: string; label: string; direction: "one_way"|"two_way"; level: "style"|"style_color";
  allows_quantity: boolean; enabled: boolean; sort_order: number; help_text?: string|null }
interface RelationshipTarget { entity_id: string; label: string|null; style_number: string|null; color_code: string|null;
  lifecycle_status: string|null }
interface Relationship { id: string; type_code: string; type_label: string; direction: "one_way"|"two_way"; inherited: boolean;
  quantity?: number|null; created_by: string; created_at: string; target: RelationshipTarget; broken: boolean }
  // inherited = set on the style and shown on its colors (read-only there); broken = target discontinued or gone
interface RelationshipAddResult { created: number; skipped: { token: string; reason: string }[]; rows: Relationship[] }

interface ChangeSet { id: string; kind: "edit"|"import"|"bulk"|"ai"|"ingest"|"rule"|"restore"|"rollback"|"approval"|string;
  created_by: string; created_at: string; description?: string|null; source_ref?: string|null; rolled_back_at?: string|null;
  changes?: number|null }
interface RestoreToResult { change_set_id: string; restored: number;
  results: { attribute_code: string; channel_code?: string|null; outcome: "approved"|"draft"|"rejected"|"unchanged"|"skipped"; message?: string|null }[] }
interface RollbackResult { restored: number; manual: { entity_id: string; attribute_code: string; reason: string }[]; [k: string]: unknown }

interface MeSettings { email: string; digest_frequency: "daily"|"weekly"|"off"; last_digest_at?: string|null }

interface AdapterErrorRate { adapter: string; window_days: number; calls: number; errors: number; error_rate: number|null;
  last_error_at?: string|null; last_error?: string|null }
```

## Endpoints

### Relationships (DM-13)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/relationship-types?include_disabled=` | `RelationshipType[]` in sort order (seeded: Goes Great With two-way, You May Also Like one-way, Set / Pairs With two-way with quantity, Replaced By one-way at the style level) |
| PUT | `/api/relationship-types/{code}` | admin (`admin_metadata`); body any of `{label, direction, level, allows_quantity, enabled, sort_order, help_text}`; creates the type when new |
| GET | `/api/products/{id}/relationships` | `{rows: Relationship[]}`: the product's own links plus, for a style-color, the links inherited from its style |
| POST | `/api/products/{id}/relationships` | body `{type_code, targets?: string[], paste?: string, quantity?: number}`. Targets are entity ids, style numbers (style-level types) or style-colors in any known format; `paste` is a comma-separated list as in the request sheet ("200809-FVP, 200809 ECB"). Needs edit rights on the style details group (or `admin_metadata`). Validates level, existence, lifecycle (discontinued targets are skipped with a reason) and brand scope; a two-way type writes both directions. → `RelationshipAddResult`; 400 for a wrong level, an unknown type or a quantity on a type that takes none |
| DELETE | `/api/relationships/{id}` | removes the link and, for a two-way type, its mirror → `{deleted: n}` |

Readiness (`EXP-03`) adds a warning per channel when a related product is discontinued or missing (never a blocker).
Feed columns (`EXP-09`) accept the source `related:<type_code>`, rendered as a comma-separated list of the related
style-colors (own and inherited, broken links left out); the transport PUT rejects an unknown type.

### History (GOV-02)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/products/{id}/restore-to` | body `{at?: ISO timestamp, history_id?: string, attribute_codes?: string[]}` (one of `at` or `history_id`; a history id restores to just before that change, its own row included): restores every attribute that changed after that point to the value it held then (a value that did not exist is cleared), as one change set of kind `restore`. Needs Approve rights per group; attributes without rights are reported `rejected`, nothing else is written. → `RestoreToResult` |
| GET | `/api/change-sets?kind=&entity_id=&page=&page_size=` | `{rows: ChangeSet[], total}` newest first; `changes` = history rows in the set |
| GET | `/api/change-sets/{id}` | `ChangeSet` |
| POST | `/api/change-sets/{id}/rollback` | rolls the set back as a unit (values touched since are listed under `manual`, not reverted); allowed for the author, `bulk_edit` or `admin_metadata`; 409 when already rolled back → `RollbackResult` |

History rows older than `PIM_HISTORY_HOT_YEARS` (default 2) leave Lakebase in the `pim_publish_history` job after
they are merged into the Delta `value_history` table; the History tab therefore shows the hot window.

### Digest (DM-07, DM-09)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/me/settings` | `MeSettings` (daily by default) |
| PUT | `/api/me/settings` | body `{digest_frequency: "daily"|"weekly"|"off"}` → `MeSettings`; 400 otherwise |

The nightly job emails one digest per user through the `PIM_SMTP_*` settings (links prefixed with `PIM_APP_BASE_URL`);
weekly users get one every seven days; a failed send leaves the notifications queued for the next run.

### Telemetry (GOV-04)

`GET /api/admin/telemetry` adds `adapter_error_rates: AdapterErrorRate[]` (30-day window: publish records per channel
plus `adapter_error` events per adapter, which publish failures, delivery failures, feedback polls and the Air poll now
record with credentials scrubbed).

### Imports (IMP-02)

`GET /api/imports/batches/{id}/suggest-mapping` folds in suggestions from the classify endpoint for columns the
header matcher could not place when `PIM_FEATURE_AI_MAPPING_SUGGEST=true` (template `import_mapping_suggest`);
the response shape is unchanged (`reason` carries the model's sentence) and nothing is applied without the person.

## Frontend scope for this phase

1. Product detail: a **Relationships** tab (count in the tab label) listing own and inherited links grouped by type with
   the target as a link to its product page, a broken badge, quantity when the type allows it, Remove on own links
   (never on inherited), and an add form: type select (types whose level matches the product's level), a product search
   picker (existing products query with `search`), a paste box for a comma-separated list, optional quantity, and a
   result summary that lists skipped tokens with reasons. Read-only when the user cannot edit the style details group.
2. History tab: a **Restore to this point** action per row (restores the whole product to just before that change,
   with a confirm dialog that shows what will change from `POST restore-to`'s results), and a **Change sets** panel
   (`GET /api/change-sets?entity_id=`) with kind, who, when, changes and Roll back (disabled when rolled back; the
   result's `manual` list shown when not empty).
3. Notification bell: a digest frequency selector (daily, weekly, off) backed by `GET/PUT /api/me/settings`.
4. Admin > Telemetry: an **Adapter error rates** table (adapter, calls, errors, rate pill, last error with time).
5. Readiness panels already render `warnings`; no change beyond showing them where they were hidden.
