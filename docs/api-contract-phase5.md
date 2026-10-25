# PIM API contract, Phase 5 additions (marketplaces, feeds, Shopify sandbox)

Extends the Phase 1 to 4 contracts. Phase 5 follows the 2026-10-25 owner decisions (docs/decisions.md): Nordstrom and
Target+ both go through Rithum (D-01, D-02) as template-based flat files; Walmart Marketplace is the one direct API
adapter (EXP-08) behind `PIM_FEATURE_CHANNEL_SEND`; the Shopify update package adds a Matrixify workbook (D-13); the
Shopify direct write path is exercised only against a sandbox store with the production flag still off (D-03); a
`merch_lead` role sees cost (D-05).

## Common shapes

```ts
interface FeedColumn { header: string; source: string;            // attribute code, ref path, core.<field>, erp.<field>, image:<n>, nrf_color, nrf_size, gtin
  always_include: boolean; case_transform: "as_is"|"title"|"sentence"|"upper"|"lower"; value_map: Record<string,string>; required: boolean }
interface ChannelTransport { transport: "download"|"sftp"|"email"|"api"; file_format: "csv"|"xlsx"|"json";
  feed_template_path?: string|null; feed_template_name?: string|null; header_row: number; feed_columns: FeedColumn[];
  sftp?: { host: string; port: number; path: string; username: string; secret_name: string; host_key: string }|null;   // secret_name = app secret resource holding the password or key; host_key = pinned server key (ssh-keyscan line, bare base64 key or "SHA256:<fp>"), required
  email?: { to: string[]; subject: string }|null;
  walmart?: { spec_version: string; product_type: string; max_items_per_feed: number; variant_attribute_names: string[] }|null;
  rithum?: { supplier_id?: string|null; vpn_prefix?: string|null; program: "nordstrom_dropship"|"targetplus"; family_rules: boolean }|null }
interface DeliveryResult { transport: string; status: "delivered"|"skipped"|"failed"; detail: string; at: string; files: string[] }
interface SandboxReport { store: string; mode: "plan"|"executed"; products: number; mutations: { kind: string; handle: string; fields: string[]; status: "planned"|"ok"|"error"; message?: string }[];
  protected_check: { handle: string; field: string; before: unknown; after: unknown; unchanged: boolean }[]; errors: string[]; at: string }
```

## Endpoints

### Transport and feed templates (EXP-09, EXP-10, EXP-11)

| Method | Path | Purpose |
|---|---|---|
| GET / PUT | `/api/channels/{code}/transport` | `ChannelTransport` (PUT requires edit_profile, RBAC-03; bumps channel version) |
| POST | `/api/channels/{code}/feed-template` | multipart `file` (XLSX or CSV template); stores it on the volume, reads the header row, returns `{feed_template_path, feed_template_name, columns: string[], schema_loaded: boolean}`; the target schema is loaded from the template when the channel has none and the mapping gets a `feed_columns` entry per header (unmapped) |
| GET | `/api/channels/{code}/feed-template` | downloads the stored template |
| POST | `/api/publishes/{id}/deliver` | (re)sends the publish's files through the channel transport (SFTP or email) → `DeliveryResult`; 409 when the transport is download or not configured, for a dry run, or while `PIM_FEATURE_CHANNEL_SEND` is false (publishes with SFTP or email transports record `summary.delivery.status = "skipped"` until the flag is on). `Publish.summary.delivery` carries the last `DeliveryResult` |

### Walmart Marketplace (EXP-08)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/channels/walmart-mp/publish` | existing publish; with `PIM_FEATURE_CHANNEL_SEND=true` and credentials bound it submits MP_ITEM feeds (one per `max_items_per_feed`), stores `external_batch_id` (first feed id) and `summary.walmart = {feed_ids: string[], status, next_poll_at, polls: n}` |
| POST | `/api/publishes/{id}/feedback` | no file: polls each feed status (15 min, 1 h, 2 h, then every 4 h), stores per-item ingestion errors (external) and the item status, and pulls the Listing Quality score per item into `summary.listing_quality: {[external_id]: number}` |
| GET | `/api/publishes/{id}/items` | items add `listing_quality?: number|null` |
| GET | `/api/channels/{code}/health` | Walmart channels only add `listing_quality_avg: number|null` and `feeds_in_progress: n`; other channels omit both keys |

### Shopify sandbox write path (D-03, EXP-07 mechanics, flag off)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/packages/{id}/sandbox-run` | body `{plan_only: boolean}`; builds the targeted-mutation plan (productUpdate, metafieldsSet in batches of 25, productVariantsBulkUpdate) from the package's included rows, never touching protected fields; `plan_only` returns the plan; otherwise runs it against the sandbox store (`PIM_SHOPIFY_SANDBOX_DOMAIN` and `PIM_SHOPIFY_SANDBOX_TOKEN`), reads the protected metafields before and after, and stores the report. 409 when the sandbox store is not configured. → `SandboxReport`; `GET /api/packages/{id}` adds `sandbox_report?: SandboxReport|null` |
| GET | `/api/packages/{id}` | `files` now include `matrixify.xlsx` (kind `matrixify`) beside the review workbook and the native CSVs (D-13) |

### Roles (D-05)

`merch_lead` role seeded with view rights on the `cost` group and the merchandising groups at approve; appears in Admin > User roles like any role.
