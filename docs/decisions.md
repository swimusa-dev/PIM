# Open decisions (spec section 11)

Code paths that depend on an open decision are stubbed behind an interface and carry a `TODO(decision: D-xx)`
marker (`grep -rn "TODO(decision" backend seeds`).

| ID | Decision | Status | Where it lands in code | Default built |
|---|---|---|---|---|
| D-01 | Nordstrom path: Mirakl marketplace, Rithum drop-ship, wholesale, or several | Open | `adapters/mirakl_seller.py`, `adapters/feed_file.py`, channel `nordstrom` in `seeds/channels.yml` | Channel disabled; requirement set seeded; both adapters stubbed |
| D-02 | Target+ integrator and item spec | Open | `adapters/target_plus.py`, channel `targetplus` | Channel disabled; family-as-a-unit validation stub; title limit 150 marked UNCONFIRMED |
| D-03 | Shopify field ownership | Partly settled (v1.4) | `seeds/channels.yml` `attribute_mapping` and `protected_fields`; `adapters/shopify_admin.py` write path | Phase 1 proposes only (EXP-13); price, inventory, compare-at price, and Layer's recommendation metafields protected |
| D-04 | Which manual fields move into the Style Master | Open | `seeds/attributes.yml` `source_of_truth` per attribute | Launch date and care instructions are PIM-owned; flip `source_of_truth` to `erp` and set `erp_column` when the ERP takes them |
| D-05 | Who sees cost and margin | Open | `cost` group, `view_cost` permission, `finance` role | Hidden for all roles except `finance`; UC column mask on gold tables still to be added by IT |
| D-06 | Enable Lakebase CDF (Preview) and the Shopify Lakeflow connector (Beta) | Open | `PIM_FEATURE_LAKEBASE_CDF`, `IMP-08` Shopify import preset | Both off; history via snapshot job; Shopify read via Admin API or CSV |
| D-07 | Image Relay lessons beyond the export | Partly answered (F1 to F10) | n/a | Attribute usage audit, placeholders, defaults, aliases built |
| D-08 | ERP vs PLM precedence | **Resolved: ERP wins** | `adapters/plm_source.py` stub; `bluecherry_source.canonicalize` drops `yplm*` columns | PLM not ingested |
| D-09 | What Layer is | **Resolved: Layer owns Shopify cross-sell data** | protected metafields in `seeds/channels.yml`; DM-13 relationships not seeded | Never written; EXP-13 excludes them from every diff |
| D-10 | `ir_matched` false everywhere | **Resolved: Image Relay was never mapped to Air** | `services/images.py` matching from scratch; PLT-00 step 10 | Backfill sized by the Air poll job report |
| D-11 | Vitamin A scope includes `TARGET VITAMIN A` and other exclusives | Open (recommendation built) | `seeds/roles.yml` brand scope rules; `eligibility` in `seeds/channels.yml` | Included in the Vitamin A scope for editing; eligible only for Target+ (`allow_classifications_for_subdivision`) |
| D-12 | "Ralph Lauren" in OmniChannel Brand | **Resolved: a real Swim USA brand, not Vitamin A** | brand scope `ralph_lauren_swim` disabled in `seeds/roles.yml` | Not seeded from Image Relay; scope ready to enable |
| D-13 | Shopify import tool | Open (default: native CSV importer) | `export/shopify_package.py` `build_import_csvs` | Shopify native product CSV rules; a second output format plugs in beside it |

## Decisions made during the build (not in the spec)

| Topic | Choice | Why |
|---|---|---|
| Readiness storage | `readiness_snapshot` table refreshed on every value write for the affected style-colors, and recomputable by job | EXP-03 asks for readiness in grids with filters; computing it per request over 100,000 SKUs would not meet the 1 s target |
| Shopify product grain | One Shopify product per style-color, variants per SKU | Matches the sample export; `product_level` is a channel config seam if a store uses one product per style |
| Empty PIM value in a mapped Shopify field | No change proposed (never an implicit clear); only an explicit Not applicable clears | Shopify overwrites blank cells [C39]; an absent PIM value must not delete live data |
| Role of `PIM_DEV_USER_ROLES` | Applies only when no identity header is present | A header-identified user must never inherit the local developer's roles |
| Reference entity values | Stored in `product_value` with `entity_level = ref:<type>` | Reuses the EAV, provenance, history, and rights machinery (DM-11 asks for the same attribute-definition machinery) |
