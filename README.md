# Swim USA PIM (Vitamin A first)

A Product Information Management app for Swim USA, built as a **Databricks App** (FastAPI + React) with
**Lakebase** (managed Postgres) as the working store and **Delta** as the analytical and history layer.
It implements the build specification `PIM_App_Build_Spec.md` v1.4. Requirement IDs (for example `DM-04`)
appear in code comments at each feature's entry point, in test names, and in commit messages.

Swim USA designs, manufactures, wholesales, and retails women's fashion swimwear and apparel. The PIM serves
the Vitamin A brand first and is brand-aware through configuration (RBAC-04), so other Swim USA brands join
without code changes.

## What is in this repository

| Path | Purpose |
|---|---|
| `backend/pim/` | FastAPI app, services, adapters, AI service, job entry points |
| `frontend/` | React 18 + TypeScript SPA (Vite), built into `backend/pim/static/` |
| `seeds/` | The starting metadata layer: groups, attributes, option lists, size scales, families, channels, roles, brand scopes, placeholders, shot types, workflows |
| `migrations/` | Alembic migrations for Lakebase |
| `resources/`, `databricks.yml`, `app.yaml` | Declarative Automation Bundle (app + Lakeflow Jobs) and the app runtime config |
| `tests/` | pytest suite against a real Postgres, with anonymized fixtures from the sample-file review (spec 1.4) |
| `docs/` | Setup and deploy guide, API contract, Phase 0 platform findings, open decisions, requirement coverage |
| `scripts/` | Local Postgres, deploy, Lakebase bootstrap |

## Quick start (local)

```bash
# 1. Python backend
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -e ".[dev]"
# 2. Local Postgres (Lakebase is Postgres; the same SQL runs in both)
scripts/dev_postgres.sh                # starts Postgres 16 on :5499 and creates databases pim and pim_test
cp .env.example .env                   # then set PIM_DATABASE_URL=postgresql+psycopg://pim@localhost:5499/pim
# 3. Schema, seed metadata, a sample Style Master load
cd backend && python -m pim.cli init-db && python -m pim.cli seed
python -m pim.cli ingest --csv ../tests/fixtures/style_master_sample.csv && cd ..
# 4. Frontend
cd frontend && npm ci && npm run build && cd ..
# 5. Run
cd backend && python -m pim.serve       # http://localhost:8000  (API docs at /api/docs)
```

Run the tests with `pytest` (needs the local Postgres), lint with `ruff check backend tests`, and build the
frontend with `npm run build` in `frontend/` (`npm run dev` gives hot reload with an API proxy).

## Deploying to Databricks

Follow **[docs/SETUP_AND_DEPLOY.md](docs/SETUP_AND_DEPLOY.md)**. In short: create the Lakebase instance,
secret scope, UC schema and volumes; fill in `databricks.yml`; run `scripts/deploy.sh dev`; run the bootstrap and
ingest jobs; assign roles.

## Where things stand

See **[docs/requirements-coverage.md](docs/requirements-coverage.md)** for the requirement-by-requirement status
and **[docs/platform-findings.md](docs/platform-findings.md)** for the Phase 0 spikes that must be run on the
Swim USA workspace before Phase 1 is considered complete. Open owner decisions are tracked in
**[docs/decisions.md](docs/decisions.md)**; code paths that depend on them carry `TODO(decision: D-xx)` markers.

## Principles baked into the code

- ERP (BlueCherry) values are read-only in the PIM, for every role including PIM Admin (P1).
- Every value carries provenance: source, who, when, AI flag, approval state, version (P2).
- Nothing reaches a channel without passing eligibility and readiness (P3, EXP-03, EXP-12).
- AI proposes, humans approve; AI output lands as a suggestion (P4, AI-03).
- Screens render from attribute metadata; the only hard-coded identifiers are style number, color code, size, SKU, UPC (P5).
- Long work runs as Lakeflow Jobs (P6, ARC-04).
- Permissions are enforced on the server; the UI only reflects them (P7).
- In Phase 1 the PIM never writes to Shopify. It produces a reviewable update package (EXP-13).
