# Open decisions (spec section 11)

Code paths that depend on an open decision are stubbed behind an interface and carry a `TODO(decision: D-xx)`
marker (`grep -rn "TODO(decision" backend seeds`).

| ID | Decision | Status | Where it lands in code | Default built |
|---|---|---|---|---|
| D-01 | Nordstrom path: Mirakl marketplace, Rithum drop-ship, wholesale, or several | **Resolved (2026-10-25): Rithum drop-ship** | `adapters/rithum.py` (Phase 5), channel `nordstrom` in `seeds/channels.yml`; `adapters/mirakl_seller.py` stays a stub | Phase 5 builds a Rithum product feed adapter; the Mirakl path is not built |
| D-02 | Target+ integrator and item spec | **Resolved (2026-10-25): Rithum, the same connection as Nordstrom** | `adapters/rithum.py` (Phase 5), channel `targetplus`; `adapters/target_plus.py` becomes the Target+ item rules on top of the Rithum feed | One Rithum adapter serves both retailers; the title limit of 150 is still to be confirmed against Rithum's Target+ template |
| D-03 | Shopify field ownership and direct writes | Field ownership settled (v1.4); **direct writes: decide after a sandbox test (2026-10-25)** | `seeds/channels.yml` `attribute_mapping` and `protected_fields`; `adapters/shopify_admin.py` write path; `PIM_FEATURE_SHOPIFY_DIRECT_WRITE` | Packages remain the Shopify output; the write path is built and run against a development store and the results shown before the flag is considered |
| D-04 | Which manual fields move into the Style Master | **Resolved (2026-10-25): none; the PIM keeps them** | `seeds/attributes.yml` `source_of_truth` per attribute | Launch date, care instructions and customer-facing color name stay PIM-owned; the ERP flip stays available per attribute if this changes |
| D-05 | Who sees cost and margin | **Resolved (2026-10-25): finance plus merchandising leads** | `cost` group, `view_cost` permission, `finance` role, new `merch_lead` role in `seeds/roles.yml` (Phase 5) | Add a merch lead role with view rights on the cost group; product merchandisers, ecommerce and viewers stay hidden; UC column mask on gold tables still to be added by IT |
| D-06 | Enable Lakebase CDF (Preview) and the Shopify Lakeflow connector (Beta) | **Resolved (2026-10-25): neither for now** | `PIM_FEATURE_LAKEBASE_CDF`, `IMP-08` Shopify import preset | Both stay off until general availability on the Swim USA workspace; history via snapshot job; Shopify read via Admin API or CSV |
| D-07 | Image Relay lessons beyond the export | Partly answered (F1 to F10) | n/a | Attribute usage audit, placeholders, defaults, aliases built |
| D-08 | ERP vs PLM precedence | **Resolved: ERP wins** | `adapters/plm_source.py` stub; `bluecherry_source.canonicalize` drops `yplm*` columns | PLM not ingested |
| D-09 | What Layer is | **Resolved: Layer owns Shopify cross-sell data** | protected metafields in `seeds/channels.yml`; DM-13 relationships not seeded | Never written; EXP-13 excludes them from every diff |
| D-10 | `ir_matched` false everywhere | **Resolved: Image Relay was never mapped to Air** | `services/images.py` matching from scratch; PLT-00 step 10 | Backfill sized by the Air poll job report |
| D-11 | Vitamin A scope includes `TARGET VITAMIN A` and other exclusives | **Resolved (2026-10-25): keep as built** | `seeds/roles.yml` brand scope rules; `eligibility` in `seeds/channels.yml` | Included in the Vitamin A scope for editing; eligible only for their own retailer (Target exclusives: Target+ only) |
| D-12 | "Ralph Lauren" in OmniChannel Brand | **Resolved: a real Swim USA brand, not Vitamin A** | brand scope `ralph_lauren_swim` disabled in `seeds/roles.yml` | Not seeded from Image Relay; scope ready to enable |
| D-13 | Shopify import tool | **Resolved (2026-10-25): Matrixify** | `export/shopify_package.py` `build_import_csvs` plus a Matrixify workbook builder (Phase 5) | The package adds a Matrixify-format workbook (sheet per object, ID columns, metafield columns) beside the native CSVs, which stay as a fallback |

## Phase 5 scope that follows from the 2026-10-25 answers

1. One Rithum adapter (`adapters/rithum.py`): product feed in Rithum's format for the Nordstrom drop-ship and
   Target+ channels, with the Target+ item rules layered on top; feedback from Rithum's error reports into the EXP-05 loop.
2. Walmart Marketplace (EXP-08) as the one direct API adapter, behind `PIM_FEATURE_CHANNEL_SEND` until credentials exist.
3. Matrixify workbook output for the Shopify update package (D-13), beside the native CSVs.
4. Shopify direct write path exercised against a development store with a report, flag still off (D-03).
5. `merch_lead` role with cost visibility (D-05).

## Phase 6 scope (the closing phase, 2026-10-25)

The spec's build order ends at Phase 5. Phase 6 closes every requirement still marked Partial, Seam or Not started
that can be finished without the Swim USA workspace: DM-13 relationships (for retailer feeds only; Shopify cross-sell
stays with Layer per D-09), GOV-02 whole-product restore, change-set rollback for any set and hot history retention,
the DM-07 and DM-09 digest actually emailed, the IMP-02 AI suggester behind a flag, GOV-04 adapter error rates, and the
Mirakl and Target+ stubs rewritten for the resolved D-01 and D-02. Items that need the workspace (PLT-00 spikes, the
group role mapper, UC app telemetry, credentials) stay open and are listed in `docs/requirements-coverage.md`.

## Decisions made during the build (not in the spec)

| Topic | Choice | Why |
|---|---|---|
| Readiness storage | `readiness_snapshot` table refreshed on every value write for the affected style-colors, and recomputable by job | EXP-03 asks for readiness in grids with filters; computing it per request over 100,000 SKUs would not meet the 1 s target |
| Shopify product grain | One Shopify product per style-color, variants per SKU | Matches the sample export; `product_level` is a channel config seam if a store uses one product per style |
| Empty PIM value in a mapped Shopify field | No change proposed (never an implicit clear); only an explicit Not applicable clears | Shopify overwrites blank cells [C39]; an absent PIM value must not delete live data |
| Role of `PIM_DEV_USER_ROLES` | Applies only when no identity header is present | A header-identified user must never inherit the local developer's roles |
| Reference entity values | Stored in `product_value` with `entity_level = ref:<type>` | Reuses the EAV, provenance, history, and rights machinery (DM-11 asks for the same attribute-definition machinery) |
