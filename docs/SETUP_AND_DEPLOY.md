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
`SELECT` on `swim_data_whse.bluecherry.style_master` (or wherever the Style Master lands).

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
GRANT SELECT ON TABLE swim_data_whse.bluecherry.style_master TO `<app service principal>`;
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
includes `sql`, `files.files`, `serving.serving-endpoints`, and `iam.current-user:read` (names as listed under
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

---

## 5. Deploy

```bash
databricks auth login --host https://adb-<id>.<n>.azuredatabricks.net
scripts/deploy.sh dev
```

The script builds the frontend into `backend/pim/static/`, validates and deploys the bundle (five jobs and the
app definition with its resources), and starts the app. The first start:

- creates the schema in Lakebase if it is empty (the app runs `create_all` on startup) and loads `seeds/*.yml`
  when the attribute table is empty, so the app is usable immediately;
- binds the Lakebase, warehouse, secret, and job resources as environment variables (see `app.yaml`).

Open the app URL printed by the deploy. You should see the home dashboard with a yellow banner saying the Style
Master has not been loaded yet.

No file in the bundle may exceed 10 MB [D1]; the frontend bundle is about 0.5 MB.

---

## 6. First data load

1. Run the bootstrap job once so Alembic records the baseline revision:
   `databricks bundle run pim_bootstrap -t dev`
2. Run the Style Master ingest: `databricks bundle run pim_style_master_ingest -t dev`, or in the app:
   **Admin > Telemetry > Run ingest now**. The run creates styles, style-colors, and SKUs, maps ERP option
   values, removes placeholder tokens (IMP-10), records ERP defects (IMP-11), starts the launch workflow for new
   style-colors, and computes channel readiness.
3. Check **Admin > ERP defects**. Unmapped ERP values appear here; add value mappings in
   `seeds/value_mappings.yml` (then re-run bootstrap) or in Admin > Option lists, and re-run the ingest.
4. Unpause the ingest schedule in the job's UI (every 2 hours by default) once the load is correct. The app header
   shows the last successful load and warns when it is older than `PIM_ERP_STALE_THRESHOLD_HOURS` (26).

Column names: `seeds/attributes.yml` maps ERP attributes to Style Master columns through `erp_column`, using
the names seen in the Image Relay export and the VAS request sheet, normalized to lower snake case. Compare
them with the real table on the first run (`DESCRIBE swim_data_whse.bluecherry.style_master`) and adjust the
`erp_column` values; no code change is needed.

---

## 7. Users and roles (RBAC-01 to RBAC-04)

- **Table mode (default):** Admin > User roles. Add each user's email with one or more roles and, optionally,
  brand scopes (empty means all brands). `seeds/roles.yml` pre-assigns `dchristy@swimusa.com` as PIM Admin.
- **Group mode:** set `PIM_ROLE_SOURCE=groups` and `PIM_GROUP_ROLE_MAP="pim-admins=pim_admin;ecomm-team=ecommerce"`
  in `app.yaml`. Requires OBO with the `iam.current-user:read` scope so the app can read the user's groups.
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

## 9. Images from Air (IMG-01 to IMG-06)

Set `PIM_AIR_WORKSPACE_ID` and `PIM_AIR_BOARDS` (comma-separated board ids to poll) in `app.yaml`, keep the API
key in the secret scope, then unpause the `pim_air_poll` job. Tier 1 and 2 matches confirm automatically when the
filename or Air fields resolve a style-color and a shot type; everything else appears under **Images** for review.
Filename patterns are admin data (`seeds/images.yml`, table `filename_pattern`).

---

## 10. Upgrades

```bash
git pull
scripts/deploy.sh dev            # or prod
databricks bundle run pim_bootstrap -t dev   # applies Alembic migrations and re-seeds metadata (upsert, never delete)
```

Schema changes: edit the models, run `alembic revision --autogenerate -m "<message>"` against a local database,
review the file in `migrations/versions/`, commit it.

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
