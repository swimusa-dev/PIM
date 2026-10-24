# Phase 0 platform findings (PLT-00)

Status key: **Open** = not yet run on the Swim USA workspace; **Pass** / **Fail** with the date and who ran it.
Every spike below has a code path ready to exercise it. Do not start Phase 1 feature work beyond what is in
this repository until each item is answered or explicitly waived by the owner (spec section 2).

These spikes need the real workspace (Azure Databricks, East US, compliance security profile). They could not be
run from the build environment, which has no workspace access, so every item is **Open** as of October 23, 2026.

| # | Spike | How to run it with this repo | Decides | Status |
|---|---|---|---|---|
| 1 | Deploy via bundle; confirm Large compute and horizontal scaling on the compliance-profile workspace | `scripts/deploy.sh dev`; then set `compute_size: LARGE` in `resources/app.yml` and redeploy; check the app's Compute page for scaling | whether `app_compute_size` stays MEDIUM; grid page size defaults | Open |
| 2 | OBO enabled; admin scope allowlist includes `sql`, `files`, `postgres`, `model-serving`; non-admin consent prompt | Open the app as a business user; the consent screen lists `user_api_scopes` from `resources/app.yml`; call `GET /api/me` and check `roles` | `PIM_ROLE_SOURCE` (groups vs table); whether UC row filters and column masks apply to app reads | Open |
| 3 | SCIM `/Me` with the OBO token returns Entra-synced groups | Set `PIM_ROLE_SOURCE=groups` and `PIM_GROUP_ROLE_MAP`; `GET /api/me` should show mapped roles; see `GroupRoleMapper` in `backend/pim/auth/identity.py` | RBAC-01 role mapping design | Open |
| 4 | Upload 25 MB and 115 MB files through the app proxy; record body-size and timeout behavior | `POST /api/packages/{id}/snapshot-upload` with a large CSV (same multipart path IMP-01 will use) | IMP-01 upload path: direct vs pre-signed Files API | Open |
| 5 | Lakebase provisioned; app SP connects; token rotation survives a 2-hour soak | Deploy, then poll `GET /api/health` every minute for 2 hours; `_TokenCache` refreshes at 50 minutes, `pool_recycle` matches | ARC-02 connection design | Open |
| 6 | Synced table from the Style Master Delta table into Lakebase; Triggered-mode refresh latency | Create a synced table (Catalog > table > Create synced table) targeting `pim-lakebase`; point `DeltaStyleMasterSource(table=...)` at it or read it directly through Postgres | whether the ingest reads Delta via the warehouse or the synced table | Open |
| 7 | Network policy mode; allowlist Shopify, Walmart, Mirakl, Air, PyPI, npm | Create a package with API snapshot mode; run `pim_air_poll`; failures appear in Admin > Telemetry as `adapter_error` | which egress rules IT must add | Open |
| 8 | Claude via Foundation Model APIs with an image input, through our endpoint and region settings | `python -c "from pim.ai.service import AIService, PromptTemplate, DEFAULT_VITAMIN_A_VOICE; ..."` from a notebook with `PIM_AI_ENDPOINT_COPY` set; pass an Air thumbnail URL as `image_urls` | IMG-03 tier 3, AI-05 extract-from-image; whether "Enforce data processing within workspace Geography" must change | Open |
| 9 | 105,000 SKU rows and 207 attributes in Lakebase; server-paged filtered grid under 1 s at p95 | Load a full Style Master; time `POST /api/products/query` with filters on an inherited attribute and on readiness (`tests/test_readiness_grid.py` shows the query shapes); add indexes to `product_value` if needed | DM-02 index strategy; whether readiness snapshots need a job instead of on-write refresh | Open |
| 10 | 1,000 Vitamin A Air assets: tier 1 and 2 match rate | Run `pim_air_poll` with `PIM_AIR_BOARDS` set to the Vitamin A boards; read `job_run.report` (`tier1`, `tier2`, `unparsed`) and Images > Unparsed filenames; adjust `filename_pattern` rows | size of the AI review queue for the initial backfill (D-10) | Open |

## Record results here

```
Spike 1   date: ____  by: ____  result: ____
Spike 2   date: ____  by: ____  result: ____
...
```

## Known platform facts the code already assumes (from spec 2.1)

- Bind `0.0.0.0:$DATABRICKS_APP_PORT`, no root, no apt-get: `backend/pim/serve.py`, `requirements.txt` only.
- Identity headers `X-Forwarded-Email`, `X-Forwarded-User`, `x-forwarded-access-token`: `backend/pim/auth/identity.py`.
- Lakebase OAuth tokens expire hourly: `backend/pim/db/session.py`.
- Lakebase synced tables are read-only: the ingest never writes to them; PIM-owned data lives in native tables.
- Lakebase CDF is Preview: history is written by `run_publish_history.py` from `value_history` unless `PIM_FEATURE_LAKEBASE_CDF` is on.
- Secrets arrive as env vars via `valueFrom`: `app.yaml`.
- Databricks embedding models are text-only: image embeddings (IMG-04) are behind `PIM_FEATURE_IMAGE_EMBEDDINGS`, not built.
- Lakeflow Connect Shopify connector does not cover metafields: EXP-13 reads Shopify through the Admin API or a CSV export instead.
