# Requirement coverage

Status: **Built** (implemented and tested here), **Partial** (core logic built, UI or integration pending),
**Seam** (interface, config, or stub in place; the full behavior is a later phase), **Not started**.
Phases follow spec section 12. Everything in this repository was tested against a local Postgres 16; nothing
has yet run on the Swim USA Databricks workspace (see docs/platform-findings.md).

## Phase 0

| ID | Status | Notes |
|---|---|---|
| PLT-00 | Seam | Bundle, app, and code paths for all 10 spikes exist; results must be recorded on the real workspace |

## Phase 1, foundation

| ID | Status | Where |
|---|---|---|
| ARC-01 FastAPI + React | Built | `backend/pim/main.py`, `frontend/` |
| ARC-02 Lakebase + Delta | Built / Seam | token-rotating pool; gold and history publish job; CDF behind a flag |
| ARC-03 EAV with provenance | Built | `models/product.py`, `services/values.py` |
| ARC-04 Lakeflow Jobs | Built | `resources/jobs.yml`, `jobs/*.py`, `services/jobs.py` enqueues from the app |
| ARC-05 Adapters | Built / Seam | bluecherry, air, shopify (read), feed_file built; walmart, mirakl, target_plus stubs |
| 1.3 Metadata layer | Built | seeds, admin API and screens, reference entity types, requirement sets |
| RBAC-01 to RBAC-04 | Built | roles, data rights, channel rights, brand scopes, server-side checks; group mapper needs PLT-00 step 3 |
| IMP-09 Style Master ingest | Built | `services/ingest.py` (CSV and Delta sources), launch workflow start, stale banner |
| IMP-10 Placeholders | Built | `normalization/core.py`, per-column report |
| IMP-11 ERP mapping and defects | Built | value mappings, `erp_defect`, Admin > ERP defects |
| DM-01 Hierarchy, aliases, prepacks | Built | strict ownership, inheritance, `identifier_alias`, prepack entities |
| DM-02 Grid and saved views | Built | server-side paging and filters incl. inherited attributes and readiness; views shared by role or everyone |
| DM-03 In-grid editing | Built | validation from definitions, keyboard navigation, TSV copy and paste, fill-down, undo |
| DM-04 Bulk actions as jobs | Not started | Phase 2 |
| DM-05 Product detail | Built | groups, completeness, missing-required toggle, provenance |
| DM-11 Reference entities | Built | Print, Fabric, Model profile; impact count before save |
| DM-14 Size scales | Built | scale order sort, channel mappings, unmapped flag |
| GOV-02 History and restore | Built | field-level history, single-attribute restore; change-set rollback as a unit is Partial |
| GOV-04 Telemetry | Partial | request ids, structured logs, app_event, admin page; enable UC app telemetry on the workspace |
| GOV-05 Secrets | Built | secret resources via `valueFrom`; never logged |
| GOV-06 Defaults | Built / Partial | defaults tagged and excluded from completeness; calculated-attribute preview and suspicious-constant check belong to GOV-01 (Phase 2) |
| GOV-07 Attribute usage | Built | Admin > Attribute usage with deprecate |

## Phase 2, collaboration and imports

| ID | Status | Where |
|---|---|---|
| DM-04 Bulk actions | Built | `services/bulk.py`: set, clear, add/remove option, find and replace, copy attribute, change family, assign workflow, run AI (as drafts), send for approval; preview of 20 and total; job or inline; report; single change set with rollback |
| DM-06 Compare and copy | Built | global vs channel on the detail page; product vs product at `/compare` with copy per row (`GET /api/products/compare`, `POST /api/products/{id}/copy-from`) |
| DM-07 Workflows | Built | definitions up to 20 steps, inbox (mine, role, all), overdue tags, manager view by step and age, advance, reject to an earlier step with per-attribute comments, assign; email digest is a logging seam until an email adapter exists |
| DM-08 Drafts and approval | Built | |
| DM-09 Comments and mentions | Built | per product and per attribute, `@first.last` or `@email` mentions, in-app notifications with a bell, digest seam |
| DM-10 Dashboards | Built | |
| DM-12 Carryover | Built | sibling colors with approved value counts; copy as drafts without overwriting; launch workflow skips steps whose groups are already approved |
| DM-13 Relationships | Not started | optional per v1.3 (Layer owns Shopify cross-sell data) |
| IMP-01 Import wizard | Built | Upload, Map, Validate, Match, Review and Commit; CSV and XLSX with multiple sheets, header row detection, merged group headers, text dates; files stored in the import volume; nothing touches product data before commit |
| IMP-02 Mapping templates | Built | templates per source auto-applied by structure signature; up to four sources per target; transforms trim, split, concat, regex extract, value replace, unit convert, HTML clean, date parse, case; header-similarity suggestions with confidence (AI suggester is a hook), hidden below 70 percent, never auto-accepted; required targets block progress |
| IMP-03 Value mapping | Built | distinct incoming values per select attribute with suggestions, remembered per source |
| IMP-04 Validation | Built | summary, error grid, error file in the source layout with an Errors column, skip row or skip value |
| IMP-05 Matching | Built | ordered keys through identifier aliases (UPC, SKU, style and color, style, vendor style, GMS), lift to the batch level, ambiguous detection, assisted fuzzy candidates confirmed by a person, keyless name extraction ("the Skylar Top"), create / update-only / create-under-match policies; match keys are never overwritten |
| IMP-06 Survivorship | Built | trusted source priority, fill empty only, most recent, never from import; per group with per-attribute override; conflicts queue with accept, reject, edit |
| IMP-07 Review and commit | Built | diff of creates, adds, changes, conflicts, skipped; commit as a job (inline locally); per-batch rollback restoring prior values and removing created entities unless touched later; import history |
| IMP-08 Presets | Built | supplier, retailer template, Shopify backfill from an API snapshot or product CSV, keyed worksheet; mixed files per batch with precedence |
| IMP-12 Keyed worksheets | Built | XLSX with group and field header rows, frozen panes, hidden locked key columns with checksum, dropdowns, shaded ERP context, Instructions tab; returned files recognized by id, matched by key, locked-column edits rejected |
| GOV-01 Rules engine | Built | condition/action rules by priority on save, on import, nightly; set, clear, copy, concatenate, calculate, set approval state, add to workflow, trigger AI (as a suggestion); GOV-06 preview on 20 samples across 3 brands with a suspicious-constant check before activation |

## Phase 3, Shopify and images

| ID | Status | Notes |
|---|---|---|
| EXP-01 Channel profiles | Built | versioned, mapping, protected fields, eligibility, config |
| EXP-02 Target schema import | Built | loaders for Walmart MP_ITEM JSON Schema (per product type), Mirakl H11/PM11/VL11 (CSV or ZIP), Shopify metafield definitions, retailer XLSX templates; diff on refresh (added, removed, required flips, enum changes); channel version bumps (`export/schema_loaders.py`, Admin > Channels > Target schema) |
| EXP-03 Readiness | Built | per channel with reasons, cached snapshots, grid filters |
| EXP-04 Validate and dry run | Built | payload per style-color from mapping plus transforms (concatenate, format, unit convert, conditional, case, truncate, value map), validation against the loaded schema (required, type, enum, length, range) and raw JSON Schema for Walmart, dry run writes the payload file and a validation report, issues link back to our attribute (`export/payloads.py`, Exports page) |
| EXP-05 Publish history | Built | `publish_record` plus one `publish_item` per product for every dry run, package, publish and scheduled run; retailer feedback from an error report file (CSV, JSON, XLSX) or adapter poll, mapped to attributes, tagged internal or external, rejections notify the owning role; health score and top errors per channel (`export/publishing.py`). Retailer API sends stay behind `PIM_FEATURE_CHANNEL_SEND=false` until Phase 5 credentials exist |
| EXP-06 Delta and full exports | Built | delta = values, images or readiness changed since the last successful publish (plus never sent); per-channel schedule (every N hours or daily at a time, saved view scope) run by the `pim_channel_export` job; a run in progress is skipped, never queued (`/api/channels/{code}/delta`, `/schedule`, `/schedule/run-now`) |
| EXP-07 Shopify direct writes | Built, flag off (D-03: sandbox test first) | targeted mutations (productUpdate, metafieldsSet in batches of 25, productVariantsBulkUpdate), protected fields never planned, a before and after check on Layer's recommendation metafields; runs only against the development store (`PIM_SHOPIFY_SANDBOX_DOMAIN`) from Packages > Shopify sandbox; production writes stay behind `PIM_FEATURE_SHOPIFY_DIRECT_WRITE=false` |
| EXP-12 Eligibility | Built | brand scope, classification, lifecycle, entity type; ineligible products are skipped from runs unless a PIM Admin records an override with a reason (and optional expiry), logged as an app event (`eligibility_override`, product detail readiness panel) |
| EXP-13 Shopify update package | Built | API or CSV snapshot, diff, workbook, import CSVs per Shopify rules, review round trip, reconcile |
| IMG-01 Air poll | Built | adapter with rate limiting and backoff; job |
| IMG-02 Shot types and image requirements | Built | shot types seeded; requirement sets carry shots and image rules |
| IMG-03 Matching | Built (tiers 1 and 2) / Built behind flag (tier 3) | tier 3 = Air semantic search for confirmed neighbors plus a vision call that reads visible codes and the shot type; proposes only, never confirms (P4); on demand per asset, 409 until `PIM_FEATURE_IMAGE_AI_MATCH=true` after PLT-00 step 8 |
| IMG-05 Review workspace | Built | slots, candidates, queues, confirm or reject, ordering (first confirmed link is the main image), technical rule checks per channel (min size, aspect ratio, format, AI generated) with a failing-rules queue |
| IMG-06 Write back to Air | Built | confirm writes Style Number, Color Code, Shot Type (and AI Generated) to Air custom fields best effort; `ai_generated_image` flag per asset; Air field names to confirm in PLT-00 step 7 |
| IMG-07 Derivatives at export | Built | per-channel image profile (shot types, size, format, pad ratio, background, naming); `image_rendition` cached per asset version and profile through Air CDN transforms, else queued for the `pim_renditions` Pillow job; payloads carry rendition URLs |

## Phase 4, AI

| ID | Status | Notes |
|---|---|---|
| AI-01 Unity Gateway routing | Built | `ai/service.py`: endpoints per task from config (`PIM_AI_ENDPOINT_COPY`, `PIM_AI_ENDPOINT_CLASSIFY`), multimodal invocation for images, every call logged as an `ai_call` app event with product, task, template version, model, tokens and latency (Admin > Telemetry) |
| AI-02 Brand voice and templates | Built | `brand_voice` and versioned `prompt_template` tables seeded from `seeds/ai.yml`, Admin > AI editors, placeholders `{{attr.x}}`, `{{attr.ref.inner}}`, `{{core.x}}`, `{{input.text}}`, `{{channel.max_length}}`, `{{options}}`; length from the template, else the channel requirement, else the attribute; every output records the template version |
| AI-03 Generate, review, apply | Built | Ask AI panel on the product page; every output is an `ai_output` plus a proposed `value_draft` (`ai_generated=true`); side-by-side with a word-level diff; accept, edit then accept (edit distance recorded, AI origin kept), regenerate, reject with a reason; accepted values stay `ai_generated` until a person edits them |
| AI-04 Bulk with sample preview | Built | `POST /api/ai/runs` generates 5 samples synchronously; approve samples starts the `pim_ai_bulk` job (inline locally); results land in the approval queue grouped by run; accept all needs Approve rights on the target group; cancel honored between batches |
| AI-05 Task types | Built | generate, adapt (channel override with the channel's length limit), extract (supplier text, document via pypdf locally or `ai_parse_document` on the warehouse, product images as multimodal parts), classify (option code with confidence; below the threshold it is shown, not drafted), check (findings only), restructure (legacy Fit Details into features, measurements and a model note), expand (ERP abbreviations to customer-facing text); all as templates in `seeds/ai.yml` |
| AI-06 Grounding | Built | NEEDS_INPUT detection, material, percentage, certification checks, certificate requirement on the Fabric, blocked terms, em dash check; a failed check never creates a draft; the same certificate rule runs as a readiness warning and a GOV-03 quality check on human copy |
| AI-07 Evaluation set | Built | `ai_eval_case` built from approved human-written values (50 by default), `ai_eval_run` scores token overlap, length, grounding and brand voice; a composite drop beyond `PIM_AI_EVAL_THRESHOLD` against the last passed run blocks the template (activation refused); MLflow logging when `PIM_MLFLOW_EXPERIMENT` is set; per-template acceptance rate, edit distance and rejection reasons at `/api/ai/metrics` |
| GOV-03 Quality score | Built | `services/quality.py`: casing, spelling heuristics, length within attribute and channel limits, blocked terms, duplicate copy, image technical rules, unsupported certification claims; admin-excluded groups, weights and grade bands; A to E per channel plus overall in `quality_snapshot`; grid columns and filters, product panel, dashboard by family, season and channel; nightly `pim_quality_score` job and refresh on value change |

## Phase 5, marketplaces and feeds

| ID | Status | Notes |
|---|---|---|
| EXP-08 Walmart Marketplace | Built behind `PIM_FEATURE_CHANNEL_SEND` | OAuth token, MP_ITEM feeds batched at the profile's item limit with the spec version pinned, variant groups (stable id, up to 3 attribute names, one primary, swatch check), MP_MAINTENANCE feed, feed and item status polling on the 15 minute, 1 hour, 2 hour, then 4 hour cadence with PROCESSED-but-INPROGRESS handling, ingestion errors into the feedback loop, Listing Quality per item into channel health (`adapters/walmart_mp.py`); credentials from `walmart-client-id` and `walmart-client-secret` secrets |
| EXP-09 Retailer data feeds | Built | feed columns per channel (always include even if empty, case transform, value map, required), XLSX template fill preserving formatting, one row per SKU with GTIN and NRF color and size codes from option value mappings, delivery by download, SFTP (paramiko, secret from an app resource) or email (SMTP), Admin > Channels > Transport (`adapters/feed_file.py`, `services/delivery.py`) |
| EXP-10 Nordstrom | Built (D-01: Rithum drop-ship) | `adapters/rithum.py` program `nordstrom_dropship`: template-based flat file on the feed renderer, VPN-SupplierColorName-01 image naming, AI imagery disclosure column; the default column set is UNCONFIRMED until the Rithum account template is uploaded; the Mirakl path is not built |
| EXP-11 Target+ | Built (D-02: Rithum) | same adapter, program `targetplus` with family rules: title of 150 or less, GS1 GTIN, 1:1 main image of 1200 px or more, one invalid child fails the family (all UNCONFIRMED [C17]) |
| IMG-04 Image embeddings | Not built | by design: tiers 1 and 2 plus Air semantic search first; revisit if unmatched images remain |
| D-13 Matrixify | Built | `matrixify.xlsx` beside the native CSVs in every Shopify package (Products and Variants sheets, Command UPDATE, metafield columns typed from the bulk snapshot) |
| D-05 merch lead | Built | `merch_lead` role with `view_cost` and view on the cost group |