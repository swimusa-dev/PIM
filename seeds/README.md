# Seed metadata

These YAML files seed the metadata layer (spec section 1.3). They are the starting attribute model, not the final one:
the PIM Admin edits everything here in the Admin screens after the first load. Re-running the seed loader upserts by
code and never deletes.

| File | Contents | Spec |
|---|---|---|
| `groups.yml` | Attribute groups with owning role, survivorship default, read-only flag | 1.3, RBAC-02, IMP-06 |
| `attributes.yml` | Attribute definitions. `erp_column` maps an ERP-owned attribute to a Style Master column (IMP-09). | 1.3 |
| `option_lists.yml` | Option lists and size scales with per-channel mappings | 1.3, DM-14 |
| `families.yml` | Families and the groups that apply to each | 1.3 |
| `channels.yml` | Channel profiles, requirement sets, eligibility rules, protected fields | EXP-01, EXP-12, EXP-07 |
| `roles.yml` | Roles, feature permissions, data rights, channel rights, brand scopes | RBAC-01 to RBAC-04 |
| `placeholders.yml` | Placeholder tokens normalized to null | IMP-10 |
| `images.yml` | Shot types and filename patterns | IMG-02, IMG-03 |
| `workflows.yml` | The New style-color launch workflow | DM-07, IMP-09 |
| `value_mappings.yml` | ERP raw value to option mappings | IMP-11 |
| `ai.yml` | Brand voices and prompt templates | AI-02 |
| `relationships.yml` | Relationship types (no links seeded; Layer owns Shopify cross-sell data) | DM-13, D-09 |

Load with `python -m pim.cli seed` (uses `PIM_DATABASE_URL` or the bound Lakebase resource).
