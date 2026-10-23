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

| ID | Status | Notes |
|---|---|---|
| DM-06 Compare and copy | Partial | global vs channel compare with copy on the detail page; product vs product not built |
| DM-07 Workflows | Seam | definitions, steps, items, launch workflow started by ingest; inbox and manager views not built |
| DM-08 Drafts and approval | Built | drafts, queue grouped by submitter, approve or reject |
| DM-09 Comments | Not started | |
| DM-10 Dashboards | Built | counts, blocking launches, readiness by channel, recent ingest and packages |
| DM-12 Carryover | Not started | inheritance covers style-level values; sibling-color copy as drafts not built |
| DM-13 Relationships | Not started | optional per v1.3 |
| IMP-01 to IMP-08 Import wizard | Not started | parsers for the setup-file layout have a fixture; staging tables and wizard pending |
| IMP-12 Keyed worksheets | Not started | `feed_file` XLSX writer is the base |
| GOV-01 Rules engine | Not started | |

## Phase 3, Shopify and images

| ID | Status | Notes |
|---|---|---|
| EXP-01 Channel profiles | Built | versioned, mapping, protected fields, eligibility, config |
| EXP-02 Target schema import | Seam | `target_schema` column and adapter hooks; loaders not built |
| EXP-03 Readiness | Built | per channel with reasons, cached snapshots, grid filters |
| EXP-04 Validate and dry run | Seam | adapter `validate` and `dry_run` on stubs; Walmart JSON Schema validation pending |
| EXP-05 Publish history | Partial | `publish_record` written per package; retailer status polling pending |
| EXP-06 Delta and full exports | Partial | changed-since selection; schedules pending |
| EXP-07 Shopify direct writes | Seam | feature flag off; read path built; write path raises until D-03 and owner approval |
| EXP-12 Eligibility | Built | brand scope, classification, lifecycle, entity type; forced export with approval not built |
| EXP-13 Shopify update package | Built | API or CSV snapshot, diff, workbook, import CSVs per Shopify rules, review round trip, reconcile |
| IMG-01 Air poll | Built | adapter with rate limiting and backoff; job |
| IMG-02 Shot types and image requirements | Built | shot types seeded; requirement sets carry shots and image rules |
| IMG-03 Matching | Built (tiers 1 and 2) / Seam (tier 3) | tier 3 needs PLT-00 step 8 |
| IMG-05 Review workspace | Built | slots, candidates, queues, confirm or reject |
| IMG-06 Write back to Air | Partial | function built, not yet wired to the confirm endpoint (needs PLT-00 step 7 and Air field names) |
| IMG-07 Derivatives at export | Seam | `AirClient.cdn_url` |

## Phase 4, AI

| ID | Status | Notes |
|---|---|---|
| AI-01 Unity Gateway routing | Built | `ai/service.py`, endpoints from config, call logging |
| AI-02 Brand voice and templates | Partial | objects and rendering built; admin UI and DB persistence pending |
| AI-03 Generate, review, apply | Partial | drafts with `ai_generated` and the approval queue exist; the Ask AI panel is not built |
| AI-04 Bulk with sample preview | Not started | |
| AI-05 Task types | Seam | task type list and template shape |
| AI-06 Grounding | Built | NEEDS_INPUT detection, material, percentage, certification checks, certificate requirement, blocked terms, em dash check |
| AI-07 Evaluation set | Not started | |
| GOV-03 Quality score | Not started | |

## Phase 5, marketplaces

| ID | Status |
|---|---|
| EXP-08 Walmart | Seam (feed shape, variant-group validation, polling cadence constants) |
| EXP-09 Retailer feeds | Partial (`feed_file` adapter with always-include, case transform, value maps; delivery and templates pending) |
| EXP-10 Nordstrom | Seam (D-01) |
| EXP-11 Target+ | Seam (D-02) |
| IMG-04 Image embeddings | Seam (flag) |
