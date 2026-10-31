# Setup and deployment guide

This guide takes the PIM from a fresh clone to a running Databricks App on the Swim USA Azure Databricks
workspace (East US, Unity Catalog, compliance security profile). Steps 1 and 2 are local; steps 3 to 9 are
on Databricks. Commands use the Databricks CLI (version 0.260 or newer). Where a UI path is given, it is the
path in the workspace as of October 2026; names move, so if a menu is not where this says, search the workspace
sidebar for the noun (for example "Lakebase").

Items marked **confirm** depend on workspace settings that only the Phase 0 spikes can verify
(docs/platform-findings.md).

---

## 1. Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.11 (Databricks Apps runtime) | backend, jobs, tests |
| Node.js and npm | 22.x (Databricks Apps runtime) | frontend build |
| Databricks CLI | 0.260 or newer, logged in | bundle deploy, secrets, jobs |
| PostgreSQL 16 client and server binaries | optional | local development and tests |
| Git | any | source control |

Workspace permissions you need: create Databricks Apps, create Lakebase instances, create jobs, create secret
scopes, `CREATE SCHEMA` and `CREATE VOLUME` on catalog `swim_data_whse`, `CAN USE` on a SQL warehouse, and
`SELECT` on `swim_data_whse.image_relay_view.vw_image_relay_export_style_master` (or wherever the Style Master lands).

---

## 2. Local development (optional but recommended before the first deploy)

```bash
git clone <this repo> && cd PIM
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -e ".[dev]"
scripts/dev_postgres.sh                      # local Postgres 16 on :5499 with databases pim and pim_test
cp .env.example .env                         # edit PIM_DATABASE_URL to postgresql+psycopg://pim@localhost:5499/pim
cd backend
python -m pim.cli init-db                    # creates all tables
python -m pim.cli seed                       # loads seeds/*.yml (metadata layer, roles, channels)
python -m pim.cli ingest --csv ../tests/fixtures/style_master_sample.csv   # a 15-row sample Style Master
cd ../frontend && npm ci && npm run build && cd ..
cd backend && python -m pim.serve            # open http://localhost:8000
```

- Sign-in locally is the `PIM_DEV_USER_EMAIL` user with `PIM_DEV_USER_ROLES` (default `pim_admin`).
- API docs: http://localhost:8000/api/docs
- Tests: `pytest` from the repo root (52 tests, about 30 seconds). Lint: `ruff check backend tests`.
- Frontend hot reload: `cd frontend && npm run dev` (Vite on :5173, proxies `/api` to :8000).

---

## 3. Create the platform resources on Databricks

### 3.1 Lakebase instance and database (ARC-02)

1. In the workspace: **Compute > Lakebase Postgres > Create instance**. Name `pim-lakebase`, the smallest
   capacity to start (one CU), East US. Wait until the instance is Available.
   CLI alternative: `databricks database create-database-instance --name pim-lakebase --capacity CU_1`
   (run `databricks database --help` to confirm the subcommand names in your CLI version).
2. Note the instance **host** (Connection details). You will put it in `databricks.yml` as `lakebase_host`.
3. Create the database `pim` inside the instance. Easiest: open the instance's SQL editor, or connect with psql
   using an OAuth token:
   ```bash
   export PGPASSWORD=$(databricks database generate-database-credential --instance-names pim-lakebase | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
   psql "host=<instance host> port=5432 dbname=databricks_postgres user=<your email> sslmode=require" -c "CREATE DATABASE pim;"
   ```
4. Grant the identities that run jobs. In **dev** the jobs run as you, so your workspace user already has a
   Lakebase role; grant it on the database: `GRANT ALL ON DATABASE pim TO "<your email>";`. In **prod** the jobs
   run as the service principal named in `databricks.yml`; add that SP as a Lakebase role on the instance
   (instance page > Roles, or `databricks database create-database-instance-role`) and grant the same.
   The **app's own** service principal is granted automatically when the Lakebase resource is bound to the app
   with `CAN_CONNECT_AND_CREATE` (step 5). **confirm** on the compliance-profile workspace (PLT-00 step 5).

### 3.2 SQL warehouse

Pick (or create) a serverless SQL warehouse for Delta reads and note its **id** (the last path segment of the
warehouse URL). Put it in `databricks.yml` as `sql_warehouse_id`.

### 3.3 Unity Catalog schema and volumes (IMP-01, EXP-13, GOV-04)

Run in a SQL editor on that warehouse:

```sql
CREATE SCHEMA IF NOT EXISTS swim_data_whse.pim;
CREATE VOLUME IF NOT EXISTS swim_data_whse.pim.imports;
CREATE VOLUME IF NOT EXISTS swim_data_whse.pim.packages;
GRANT USE SCHEMA, READ VOLUME, WRITE VOLUME ON SCHEMA swim_data_whse.pim TO `<app service principal>`;   -- after step 5 creates it
GRANT SELECT ON TABLE swim_data_whse.image_relay_view.vw_image_relay_export_style_master TO `<app service principal>`;
```

If the Style Master lives at a different table name, change `PIM_STYLE_MASTER_TABLE` in `app.yaml` and the
`--table` parameter of the ingest job in `resources/jobs.yml`.

### 3.4 Secret scope (GOV-05)

```bash
databricks secrets create-scope pim-secrets
databricks secrets put-secret pim-secrets air-api-key            # paste the Air API key
databricks secrets put-secret pim-secrets shopify-read-token     # Shopify Admin API token with read_products scope only
```

Restrict **CAN MANAGE** on the app to IT, because bound secret values are visible in plaintext on the app's
Environment page to managers [D25]. If a secret is not available yet, create the key with a placeholder value;
the adapters raise a clear "not configured" error until a real value is present.

### 3.5 On-behalf-of-user authorization (RBAC-01, PLT-00 step 2) **confirm**

In the account console, confirm that user authorization for apps is enabled and that the admin scope allowlist
includes `sql`, `files`, and `model-serving` (names as listed under
`user_api_scopes` in `resources/app.yml`). If the workspace does not allow OBO, set `PIM_ROLE_SOURCE=table`
(the default in `app.yaml`) and manage roles in Admin > User roles.

### 3.6 Network policy (PLT-00 step 7) **confirm**

If the workspace's serverless egress policy is restricted, allowlist: `api.air.inc`, `*.myshopify.com`,
`marketplace.walmartapis.com`, the Mirakl host for Nordstrom (once D-01 is decided), `pypi.org`,
`files.pythonhosted.org`, and `registry.npmjs.org` (the last three only if the build runs on Databricks).

---

## 4. Configure the bundle

Edit `databricks.yml`:

```yaml
variables:
  sql_warehouse_id: { default: "<warehouse id>" }
  lakebase_host:    { default: "<instance host>" }
  lakebase_user:    { default: "<your email for dev>" }
targets:
  dev:
    workspace: { host: https://adb-<id>.<n>.azuredatabricks.net }
  prod:
    workspace: { host: https://adb-<id>.<n>.azuredatabricks.net, root_path: /Workspace/Shared/.bundle/swimusa-pim/prod }
    run_as: { service_principal_name: "<SP application id>" }
    variables: { lakebase_user: "<SP application id>" }
```

Optional: set `app_compute_size: LARGE` once PLT-00 step 1 confirms Large compute is available, and uncomment
`compute_size` in `resources/app.yml`.

Check the Shopify store domain in `app.yaml` (`PIM_SHOPIFY_STORE_DOMAIN`).

Phase 3 feature flags in `app.yaml`, all off by default:

| Variable | Default | Turn on when |
|---|---|---|
| `PIM_FEATURE_SHOPIFY_DIRECT_WRITE` | false | D-03 and owner approval for EXP-07; until then a Shopify publish builds an EXP-13 package |
| `PIM_FEATURE_CHANNEL_SEND` | false | Phase 5 marketplace credentials and sandbox tests exist; until then publishes validate, write the payload files and record history, and nothing is sent |
| `PIM_FEATURE_IMAGE_AI_MATCH` | false | PLT-00 step 8 confirms the vision endpoint and Air semantic search; enables tier 3 image candidates |

`PIM_PUBLISH_VOLUME` is optional; publish payloads and job-rendered images default to the package volume.

---

## 5. Deploy

```bash
databricks auth login --host https://adb-<id>.<n>.azuredatabricks.net
scripts/deploy.sh dev
```

The script builds the frontend into `backend/pim/static/`, validates and deploys the bundle (thirteen jobs and the
app definition with its resources), and starts the app. The first start:

- creates the schema in Lakebase if it is empty (the app runs `create_all` on startup) and loads `seeds/*.yml`
  when the attribute table is empty, so the app is usable immediately;
- binds the Lakebase, warehouse, secret, and job resources as environment variables (see `app.yaml`).

Open the app URL printed by the deploy. You should see the home dashboard with a yellow banner saying the Style
Master has not been loaded yet.

No file in the bundle may exceed 10 MB [D1]; the frontend bundle is about 0.5 MB.

---

## 6. First data load

1. Run the bootstrap job once so Alembic applies the migrations (baseline, Phases 2, 3 and 4):
   `databricks bundle run pim_bootstrap -t dev`
2. Run the Style Master ingest: `databricks bundle run pim_style_master_ingest -t dev`, or in the app:
   **Admin > Telemetry > Run ingest now**. The run creates styles, style-colors, and SKUs, maps ERP option
   values, removes placeholder tokens (IMP-10), records ERP defects (IMP-11), starts the launch workflow for new
   style-colors, and computes channel readiness.
   The load reads the source in 16 slices and commits after each one, so a failure keeps the slices already loaded.
   Re-running the job resumes from the failed run (within 48 hours); add the `--fresh` job parameter to load
   everything again. The first load of the Image Relay view (about 207,000 rows) takes a few hours.
   The ingest is incremental. It fingerprints each style's source rows and skips a style that has not changed since the
   last load, so a scheduled run costs the read (a few minutes) plus the styles that changed. A style that changed is
   processed whole. The first run after a deploy that adds this (or after the fingerprint table is empty) processes every
   style, about 3 hours, and records the baseline. Add the `--full` job parameter to process every style again, for
   example after a change to the load logic itself. `--fresh` implies `--full`.
   The first successful load only builds the catalog and starts no launch workflows. Later loads start a launch
   workflow for each style-color that is new to the catalog. Bootstrap cancels the untouched launch tasks an earlier
   first load opened, so "My open tasks" holds real work.
   Families come from the Style Master's Body Type column (the view has no product type), through the rules in
   `seeds/families.yml`. After changing those rules, re-run bootstrap and then the `[PIM] Refresh product families`
   job: it re-reads only the style and body type and updates the loaded entities in bulk, so no full load is needed.
   It also recomputes readiness and quality for the style-colors that move family (they depend on it). Add the
   `--all-snapshots` job parameter to recompute every style-color.
3. Check **Admin > ERP defects**. Unmapped ERP values appear here; add value mappings in
   `seeds/value_mappings.yml` (then re-run bootstrap) or in Admin > Option lists, and re-run the ingest.
   Size values are the exception: after adding a value to a size scale in `seeds/option_lists.yml`, re-running
   bootstrap alone clears the matching SKUs' size flags and defects. No ingest re-run is needed.
4. Unpause the ingest schedule in the job's UI (every 2 hours by default) once the load is correct. The app header
   shows the last successful load and warns when it is older than `PIM_ERP_STALE_THRESHOLD_HOURS` (26).
5. Set which brands go to which channels (D-15), in the app, as a PIM Admin:
   - **Admin > Brand scopes**: a brand scope is a rule over division, brand and other ERP fields (a scope matches when any
     of its rules does; a rule matches when all its conditions do). Preview shows how many style-colors a rule matches.
   - **Admin > Channels > Eligibility**: choose the brand scopes a channel admits (or every brand) and what it never
     sends (classifications, lifecycle status, prepacks). Preview impact shows how many style-colors would become
     eligible before you save.
   - After either change, use **Apply to loaded products**. It runs the `[PIM] Apply eligibility changes (D-15)` job,
     which re-derives every product's brand scopes from its stored ERP fields and recomputes channel readiness and
     quality (a few minutes for the full catalog). No Style Master load is needed.

Column names: `seeds/attributes.yml` maps ERP attributes to Style Master columns through `erp_column`, using
the names seen in the Image Relay export and the VAS request sheet, normalized to lower snake case. Compare
them with the real table on the first run (`DESCRIBE swim_data_whse.image_relay_view.vw_image_relay_export_style_master`) and adjust the
`erp_column` values; no code change is needed.

---

## 7. Users and roles (RBAC-01 to RBAC-04)

- **Table mode (default):** Admin > User roles. Add each user's email with one or more roles and, optionally,
  brand scopes (empty means all brands). `seeds/roles.yml` pre-assigns `dchristy@swimusa.com` as PIM Admin.
- **Group mode:** set `PIM_ROLE_SOURCE=groups` and `PIM_GROUP_ROLE_MAP="pim-admins=pim_admin;ecomm-team=ecommerce"`
  in `app.yaml`. Requires OBO; Databricks adds the `iam.current-user:read` scope to every app by default, so the app can read the user's groups.
  Table assignments still apply on top.

ERP attributes are view-only for everyone, and cost attributes are hidden unless the role has `view_cost`
(the `finance` role), per D-05. For direct data access outside the app, also add a UC column mask on the cost
columns of the gold tables.

---

## 8. Shopify update packages (EXP-13)

1. Store the read-only Admin API token in the secret scope (step 3.4). If Shopify API read access is not
   approved yet, choose snapshot mode **CSV upload** when creating a package and upload the store's product CSV
   export; the diff and files are identical.
2. In the app: **Packages > New package**, choose the Vitamin A Shopify channel and a selection (a saved view,
   pasted entity ids, or changed since a date). Only products that are eligible and ready are included; the
   summary lists the rest with reasons.
3. Download the review workbook, mark rows N that should not go, upload it back to regenerate the CSVs.
4. Import the CSV files with Shopify's product CSV importer with "Overwrite products with matching handles" on.
   Variant metafield rows cannot be imported by CSV and are marked in the workbook.
5. After the import, **Reconcile** (fresh API snapshot or a fresh CSV upload) marks each change applied, not
   applied, or changed differently in Shopify.

Files are stored under `/Volumes/swim_data_whse/pim/packages/<package id>/v<n>/`. Direct API writes (EXP-07)
stay behind `PIM_FEATURE_SHOPIFY_DIRECT_WRITE=false` until the owner approves them.

---

## 8a. Imports, worksheets, bulk actions, workflows, rules (Phase 2)

- **Imports** run from the Imports page. Sources are seeded (`seeds/import_sources.yml`); add vendors as sources in
  Imports > Sources so their mapping templates and value mappings are remembered per vendor (IMP-02, IMP-03).
  Uploaded files land in `/Volumes/swim_data_whse/pim/imports/<batch id>/`. Commit runs the `pim_import_commit` job
  on Databricks (inline locally); rollback is available on every committed batch.
- **Keyed worksheets** (IMP-12) are generated from Worksheets and come back through Imports with source
  "Keyed worksheet". Files are stored under the packages volume at `worksheets/<id>/`.
- **Bulk actions** (DM-04) start from the product grid selection or a saved view, always preview first, and run
  through the `pim_bulk_action` job (inline locally). Every action can be rolled back from Bulk history.
- **Workflows** (DM-07): the seeded launch workflow starts on new style-colors from the ingest. Edit definitions in
  Workflows > Admin. The notification digest and nightly rules run in `pim_rules_nightly`; unpause its schedule.
- **Rules** (GOV-01) live in Admin > Rules. A rule stays a draft until a preview passes the GOV-06 checks (20 sample
  products across at least 3 brand scopes, no suspicious constants) or an admin forces activation with a reason.
  On-save rules run inside the save request; on-import rules after each commit; nightly rules in the job.

## 8b. Channel exports (EXP-02, EXP-04, EXP-05, EXP-06, EXP-12)

1. **Admin > Channels > Configure > Target schema**: upload the retailer's spec and press **Refresh schema**.
   Walmart takes the MP_ITEM spec JSON for one product type (set the product type), Nordstrom takes the Mirakl
   PM11 and VL11 exports (CSV files or one ZIP), Shopify takes a saved `metafieldDefinitions` query result (the
   fixed product CSV columns load without a file), retailer feeds take the XLSX template (header row, optional
   hint row with `required`, `number`, `date` or `A|B|C` choices). The diff panel shows what changed since the last
   load; required additions and removals are flagged.
2. **Mapping**: map each target field to an attribute (or `core.<field>` / `erp.<field>`), add transforms, and
   save. The gaps box lists required fields without a mapping and mapped fields the schema no longer has.
   Select values use the option value's per-channel wording (Admin > Option lists, DM-14) before the label.
3. **Exports page**: pick the channel, run a **Dry run** on a saved view, pasted ids or changed-since; open the
   run for the payload preview, the validation report and the item list (issues link to the product and
   attribute). **Publish** needs the channel's run right: for Shopify it creates an EXP-13 package; for feed
   channels it writes the file for download; for API channels it stays validate-only until
   `PIM_FEATURE_CHANNEL_SEND` is on.
4. **Feedback**: on a publish, upload the retailer's error report (CSV, JSON or XLSX with a product id column and
   a message column) or press **Poll adapter**. Messages are mapped to attributes through the channel mapping and
   tagged internal (fix in the PIM) or external (retailer side); rejections notify the channel's owning role
   (`config.owner_role`, default `ecommerce`). **Health** shows the 30-day acceptance score and top errors.
5. **Schedule**: enable delta or full runs every N hours or daily at a time (scoped to a saved view), then
   unpause the `pim_channel_export` job (hourly check; it also polls feedback for submitted batches). A channel
   with a run in progress is skipped. **Run now** triggers the job or, locally, runs inline.
6. **Eligibility override** (EXP-12): an ineligible product is skipped from every run. A PIM Admin can force it
   from the product's readiness panel with a reason and optional expiry; the override is logged.

---

## 8c. AI enrichment (AI-01 to AI-07) and the quality score (GOV-03)

1. **Endpoints (AI-01)**: set `PIM_AI_ENDPOINT_COPY` (Sonnet class) and `PIM_AI_ENDPOINT_CLASSIFY` (Haiku class) in
   `app.yaml` to Unity Gateway endpoints with usage tracking, rate limits and inference tables enabled (D19). The
   app's service principal needs CAN_QUERY on both. Image extraction needs the classify endpoint to accept image
   parts. Until an endpoint answers, Ask AI returns a clear "AI endpoint not configured" message and nothing else
   changes.
2. **Brand voice and templates (AI-02)**: `seeds/ai.yml` seeds the Vitamin A voice and eleven templates (one per
   task type plus the copy set). Edit them under **Admin > AI**; a body change creates a new version and clears the
   evaluation gate. Templates reference attributes by code and never name a field in code.
3. **Ask AI (AI-03)**: on a product, pick a template, preview the prompt, run, then accept, edit then accept,
   regenerate or reject with a reason. Accepting needs Approve rights on the attribute group; otherwise the
   suggestion stays in the approval queue (DM-08). Accepted values keep the AI badge until a person edits them.
4. **Bulk (AI-04)**: from the grid's Bulk actions choose **Run AI**, pick a template; five samples run at once.
   Approve the samples to start the `pim_ai_bulk` job for the rest (no job bound locally: runs inline). The run page
   and the approval queue group the results by run; **Accept all** needs Approve rights.
5. **Evaluation (AI-07)**: under **AI > Evaluation**, build the set from approved human-written copy (50 products),
   then run the evaluation for a template. The run is blocked when the composite score drops more than
   `PIM_AI_EVAL_THRESHOLD` (0.05) below the last passed run, and a blocked template cannot be activated. Set
   `PIM_MLFLOW_EXPERIMENT` to also log each run to MLflow. Run `pim_ai_eval` after every endpoint change.
6. **Quality score (GOV-03)**: **Admin > Quality** holds the excluded groups (ERP and cost by default), enabled
   checks, weights and grade bands. Grades show in the grid (`Quality` columns per channel), on the product page and
   on the dashboard by family, season and channel. Scores refresh with readiness on every value change and nightly
   through `pim_quality_score`; press **Recompute now** after changing the settings.

---

## 8d. Marketplaces and retailer feeds (EXP-08 to EXP-11), Matrixify and the Shopify sandbox (Phase 5)

1. **Secrets**: add `walmart-client-id`, `walmart-client-secret` and `shopify-sandbox-token` to the secret scope;
   the bundle binds them as app resources. SFTP passwords or private keys for retailer deliveries are app secret
   resources too, named on the channel transport (`secret_name`). Every SFTP transport also pins the retailer
   server's host key (`host_key`: the `ssh-keyscan <host>` line or the `SHA256:` fingerprint from the retailer's
   onboarding sheet); a server presenting a different key is refused before any credential is sent. SFTP and email
   deliveries, like API sends, stay off until `PIM_FEATURE_CHANNEL_SEND=true`: publishes record the delivery as
   skipped and **Deliver now** answers 409 until then.
2. **Rithum (Nordstrom drop-ship and Target+, D-01 and D-02)**: under **Admin > Channels > Transport** upload the
   program's catalog template from the Rithum account (XLSX or CSV); the header columns become feed columns. Map
   each column to an attribute, a core field, `image:1..n`, `gtin`, `nrf_color` or `nrf_size` (GS1 NRF codes ride on
   the option value's `nrf` channel mapping, Admin > Option lists), set case transforms and always-include flags, and
   choose the transport (download, SFTP or email). Target+ keeps `family_rules` on: one invalid child fails the
   family. Until the real templates are uploaded the default columns are placeholders marked UNCONFIRMED.
3. **Walmart (EXP-08)**: load the MP_ITEM spec for the product type (Admin > Channels > Target schema), set the spec
   version, item limit and up to three variant attribute names on the Transport tab, and keep
   `PIM_FEATURE_CHANNEL_SEND=false` until the sandbox account answers. Publishes then build and validate the feeds
   without sending. With the flag on, the `pim_channel_export` job polls feed status on Walmart's cadence and pulls
   Listing Quality scores into the channel health view.
4. **Matrixify (D-13)**: every Shopify package now includes `matrixify.xlsx`; the native CSVs remain.
5. **Shopify sandbox (D-03)**: set `PIM_SHOPIFY_SANDBOX_DOMAIN` to the development store and bind its token. On a
   package, **Shopify sandbox > Plan only** shows the targeted mutations; **Run against sandbox** executes them on
   the development store and reports the protected metafields before and after. Production writes stay off until the
   owner decides on the report.
6. **Roles (D-05)**: assign `merch_lead` to merchandising leads who may see cost and margin.

---

## 8e. Closing phase: relationships, restore, digest email, AI mapping suggestions (Phase 6)

1. **Migration**: the bootstrap job (or `alembic upgrade head`) adds `relationship_type`, `product_relationship` and
   `user_setting`; the seed loader adds the four relationship types from `seeds/relationships.yml` with no links.
2. **Relationships (DM-13)**: on a product page the Relationships tab links other products by type; Replaced By is
   set on the style and inherited by its colors. Retailer feeds can carry a `related:<type>` column (Transport tab).
   Shopify cross-sell metafields stay protected: Layer owns them (D-09).
3. **Restore and retention (GOV-02)**: the History tab restores a whole product to a point in time and rolls any
   change set back as a unit. Set `PIM_HISTORY_HOT_YEARS` (default 2) to choose how long history stays in Lakebase;
   the `pim_publish_history` job prunes older rows only after they are merged into the Delta `value_history` table.
4. **Digest email (DM-07, DM-09)**: with `PIM_SMTP_HOST` (and user, password, from) set, the nightly job emails each
   user their unread notifications; set `PIM_APP_BASE_URL` to the app URL so the links resolve. Users choose daily,
   weekly or off from the bell menu. Without SMTP the job logs the digest as before.
5. **AI mapping suggestions (IMP-02)**: set `PIM_FEATURE_AI_MAPPING_SUGGEST=true` once the classify endpoint is bound
   (section 8c); the import wizard then shows model suggestions with a confidence for columns the header matcher
   missed. Nothing is applied without the person.
6. **Telemetry (GOV-04)**: Admin > Telemetry shows adapter error rates over 30 days; publish failures, delivery
   failures, feedback polls and the Air poll record `adapter_error` events with credentials scrubbed.

---

## 9. Images from Air (IMG-01 to IMG-07)

Set `PIM_AIR_WORKSPACE_ID` and `PIM_AIR_BOARDS` (comma-separated board ids to poll) in `app.yaml`, keep the API
key in the secret scope, then unpause the `pim_air_poll` job. Tier 1 and 2 matches confirm automatically when the
filename or Air fields resolve a style-color and a shot type; everything else appears under **Images** for review.
Filename patterns are admin data (`seeds/images.yml`, table `filename_pattern`).

Phase 3 additions:

- **Ordering and rules (IMG-05)**: reorder confirmed links on the product's images panel (the first is the main
  image). Each link shows the channels whose technical rules it fails (`image_rules` on the requirement set:
  `min_width`, `min_height`, `max_width`, `aspect_ratio` such as `4:5`, `max_aspect_delta`, `formats`,
  `reject_ai_generated`). **Images > Failing rules** lists them per channel.
- **Write-back (IMG-06)**: confirming a link writes Style Number, Color Code and Shot Type to the asset's Air
  custom fields, best effort (no Air key, no block). Confirm the field names in PLT-00 step 7 and adjust
  `write_back_to_air` if they differ. The **AI generated** toggle per asset also writes `AI Generated`.
- **Tier 3 candidates (IMG-03)**: **Ask AI for candidates** on an unparsed asset runs Air semantic search for
  confirmed neighbors and a vision call that reads visible codes; results are proposals only. Needs
  `PIM_FEATURE_IMAGE_AI_MATCH=true` and a vision-capable classify endpoint (`PIM_AI_ENDPOINT_CLASSIFY`).
- **Renditions (IMG-07)**: set the channel's image profile (Admin > Channels > Image profile), then
  **Create for channel** on a link or **Refresh renditions** from the API. Air CDN transforms serve the
  derivative without storing a copy; when Air is unavailable the row is queued and the `pim_renditions` job
  resizes with Pillow into the publish volume.

---

## 10. Upgrades

```bash
git pull
scripts/deploy.sh dev            # or prod
databricks bundle run pim_bootstrap -t dev   # applies Alembic migrations and re-seeds metadata (upsert, never delete)
```

Schema changes: edit the models, run `alembic revision --autogenerate -m "<message>"` against a local database,
review the file in `migrations/versions/`, commit it. Phase 3 is migration `f2ec7848d5b7` (new tables
`publish_item`, `eligibility_override`, `image_rendition`; new columns on `channel` and `publish_record` with
server defaults so existing rows upgrade in place). Phase 4 is migration `3065a9ada0dc` (nine new tables for brand
voices, templates and versions, AI runs and outputs, the evaluation set, quality settings and snapshots).

---

## 11. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| App starts but every request returns 401 | The app is being reached without the Databricks proxy headers. Open it through its Databricks URL. |
| `Set PIM_DATABASE_URL or bind a Lakebase resource` on startup | The Lakebase resource is not bound; check the app's Resources tab and `valueFrom: lakebase` in `app.yaml`. |
| Postgres `password authentication failed` after about an hour | Token rotation. The pool refreshes tokens at 50 minutes and recycles connections; check that the app SP still has a Lakebase role. PLT-00 step 5 soak test. |
| Ingest job fails with `PIM_SQL_WAREHOUSE_ID is required` | Set `sql_warehouse_id` in `databricks.yml` and redeploy. |
| Header banner says Style Master data is stale | The ingest schedule is paused or failing; see Admin > Telemetry. |
| Package creation returns 409 "not configured" | No Shopify read token; use CSV upload snapshot mode or add the secret. |
| Frontend shows the JSON "Frontend build missing" page | `npm run build` was not run before deploy; `scripts/deploy.sh` does it for you. |
| Logs disappear after the app restarts | Enable app telemetry to Unity Catalog on the app (GOV-04) [D1]. |
