# The Fitting Room PIM frontend

React 18 + TypeScript single-page app for the Swim USA PIM (Product Information Management) Databricks App.
Swim USA designs, manufactures, wholesales and retails women's fashion swimwear and apparel; the first brand served
is Vitamin A. The UI is metadata-driven (principle P5): columns, forms and filters come from
`/api/metadata/attributes` and `/api/metadata/groups`, never from hard-coded attribute names.

## Stack

- Vite 6, React 18.3, TypeScript 5.9
- react-router-dom 6 (BrowserRouter; the FastAPI app serves `index.html` for any non-API route)
- @tanstack/react-query 5, @tanstack/react-table 8, @tanstack/react-virtual 3
- One global stylesheet (`src/styles.css`), no UI framework

## Commands

```bash
cd frontend
npm install          # exact pinned versions in package.json
npm run dev          # Vite dev server on http://localhost:5173, proxies /api to http://localhost:8000
npm run build        # tsc -b && vite build, output goes to ../backend/pim/static
npm run lint         # eslint with typescript-eslint
npm run preview      # serve the production build locally
```

Run the FastAPI backend on port 8000 before `npm run dev` so `/api` calls resolve. In local development the
backend reads `PIM_DEV_USER_EMAIL` and `PIM_DEV_USER_ROLES` to stand in for the Databricks identity headers.

## Layout

```
src/
  api/        types.ts (contract interfaces), client.ts (typed fetch for every endpoint), hooks.ts (metadata hooks)
  components/ AppShell, NotificationBell, Common (Spinner, ErrorBox, Dialog, badges), ValueEditor (editors by data_type)
  grid/       product grid pieces: field catalog, filter builder, column chooser, saved views, edit batching, bulk actions dialog
  detail/     product detail pieces: tree, attribute form, images, history, comments, workflow panel, carryover, Ask AI panel, quality panel
  imports/    import wizard steps: shared helpers, Upload, Map (with value mappings and templates), Validate, Match, Review
  workflows/  workflow item actions (advance, reject, assign) shared by My Work and the detail panel
  admin/      admin tabs (including Rules, AI with BrandVoices and PromptTemplates, Quality); admin/channel/ holds the per-channel editor tabs (Phase 5: TransportTab)
  ai/         Phase 4 AI pieces shared by several screens: shared.tsx (task labels, status pills, diff view, 409 banner), OutputCard (review card), Evaluation tab
  exports/    pieces shared by the Exports pages: status pills, Dry run / Publish dialog, delta preview, Phase 5 delivery and Walmart feed cards (DeliveryCards)
  pages/      one file per route, each headed with the requirement IDs it implements
  lib/        format, validation, tsv helpers
```

## Routes

| Path | Page | Spec |
|---|---|---|
| `/` | Home dashboard | DM-10 |
| `/products` | Product grid with saved views and in-grid editing | DM-01, DM-02, DM-03, EXP-03 |
| `/products/:id` | Product detail (Phase 4: Ask AI tab, Quality section, `?attr=<code>` focuses an attribute row) | DM-01, DM-05, DM-06, DM-11, IMG-05, GOV-02, GOV-03, AI-03, AI-05, AI-06 |
| `/reference/:type`, `/reference/:type/:id` | Reference entities | DM-11 |
| `/approvals` | Approval queue (Phase 4: Run filter, run and template chips, Accept all in run) | DM-08, AI-04 |
| `/packages`, `/packages/:id` | Shopify update packages (Phase 5: file kinds including matrixify.xlsx, Shopify sandbox section with Plan only, Run against sandbox and the SandboxReport view) | EXP-13, D-03, D-13 |
| `/exports` | Exports: channel picker, Dry run, Publish, Delta preview, publish history with channel and kind filters | EXP-04, EXP-05, EXP-06 |
| `/exports/:id` | Publish detail: summary, payload preview, files, items with issues and errors, retailer feedback upload or adapter poll, package link (Phase 5: Delivery card with Deliver now, Walmart feeds card with Poll now, Listing quality column) | EXP-04, EXP-05, EXP-13, EXP-08, EXP-09 |
| `/images` | Image review queues: candidates, missing shots, unparsed (with Ask AI for candidates), failing rules per channel | IMG-03, IMG-05 |
| `/admin/:tab` | Metadata, roles, rules, AI (brand voice, prompt templates), quality settings and dashboard, reports, telemetry | 1.3, RBAC, IMP-11, GOV-01, GOV-03, GOV-04, GOV-07, AI-02 |
| `/admin/channels` | Channel list; each row expands into Target schema, Mapping, Image profile, Transport, Schedule and Health tabs | EXP-01, EXP-02, EXP-05, EXP-06, EXP-08, EXP-09, EXP-10, EXP-11, IMG-07 |
| `/admin/rules` | Rules engine: list, editor, preview on samples, activate, run now, runs | GOV-01, GOV-06 |
| `/imports` | Import history, mapping templates, import sources | IMP-07, IMP-02, IMP-01 |
| `/imports/new`, `/imports/:id` | Import wizard: Upload, Map, Validate, Match, Review and Commit | IMP-01 to IMP-08, IMP-12 |
| `/worksheets` | Keyed worksheet export | IMP-12 |
| `/bulk` | Bulk action history with reports and rollback (the dialog lives on `/products`) | DM-04 |
| `/workflows` | My Work: Mine / My role / All, Manager, Admin definitions | DM-07 |
| `/compare?a=&b=&channel=` | Compare two products, copy values across | DM-06 |
| `/ai`, `/ai/:tab` | AI page: Runs, Outputs, Metrics, Evaluation (eval cases and eval runs) | AI-04, AI-07 |
| `/ai/runs/:id` | Bulk AI run: header and progress, sample review cards, approve samples, cancel, outputs table, Accept all | AI-04 |

Phase 2 additions on existing pages: the product grid has a selection checkbox column and a Bulk actions button
(DM-04); the product detail page has a Comments tab (DM-09), a Workflow panel (DM-07), a Carryover action for
style-colors (DM-12) and a "Compare with..." link (DM-06); the top bar has a notification bell polled every 60
seconds (DM-09).

## Phase 2 contract assumptions

The frontend builds to `docs/api-contract-phase2.md`. Where the contract leaves a shape open, the client accepts
both likely forms or sends an extra optional field:

- `GET /api/bulk`, `GET /api/rules/runs`, `GET /api/products/{id}/workflow` may return a bare array or `{rows, total}`.
- `GET /api/workflows` rows are `{code, label, enabled, entry_rule, steps[]}`; steps may carry an `id` (used as `to_step_id` on reject, falling back to the position).
- `PUT /api/imports/batches/{id}/mapping` also sends `files: [{index, header_row, group_header_row, data_start_row}]` for header row edits (applied through PUT /api/imports/batches/{id}/files when leaving the Upload step) made on the Upload step.
- `POST /api/imports/templates` sends the template fields plus `batch_id` so the server can derive the structure signature.
- Review diff entries for `creates`, `adds` and `skipped` are rendered from whatever keys they carry.
- `GET /api/notifications` without `unread` is expected to return recent rows plus the `unread` count.

## Phase 3 additions

Built to `docs/api-contract-phase3.md`. The Phase 3 client lives in `src/api/client.ts` as `channelApi`, `publishApi`
and `eligibilityApi` (plus `api.images.*` and `api.metadata.shotTypes`); the interfaces are appended to
`src/api/types.ts`.

- Admin > Channels: each row has a Configure button that expands the `ChannelEditor` (EXP-02 target schema with
  refresh and diff, EXP-01 mapping with attribute picker, transforms, value-mappings summary and gaps, IMG-07 image
  profile, EXP-06 schedule with Run now, EXP-05 health). Mapping and image profile share one draft saved with
  `PUT /api/channels/{code}/mapping`; the editor is read only without the `edit_profile` channel right (`*` wildcard
  applies, admins always pass).
- Product detail: the Readiness detail panel ends with the Eligibility block (EXP-12): reasons per channel, and for
  admins (`admin_metadata`) an Override eligibility dialog with a required reason and optional expiry, plus a Remove
  action on existing overrides.
- Product images panel: confirmed links in sort order with up / down reordering (`PUT /images/order`, the first is
  Main), rule failure badges per channel, an AI generated toggle per asset, a Renditions expander with Create for
  channel, and Ask AI for candidates on candidate assets (tier 3, 409 shown as "feature off").

### Phase 3 contract assumptions

- `GET /api/channels/{code}/mapping` is expected to echo `image_profile` (optional); when absent the editor falls back
  to `channel.config.image_profile`, then to an empty profile.
- `GET /api/metadata/shot-types` (present in the backend, not in the contracts) returns `{code, label, sort_order}[]`.
- Package transport is detected from `channel.config.transport === "package"`, or from a Shopify adapter when the
  key is absent; the publish result then links to `/packages/{summary.package_id}`.
- `ChannelHealth.health_score` is rendered as a percent whether the backend sends 0..1 or 0..100.
- The schedule form stores either `every_hours` or `at_hour` plus `at_minute`; the other is sent as `null`.
- The `failing_rules` image queue rows are expected to be `ImageLink` rows; the product label is read from `label`
  or `entity_label`, and the reasons from `rule_failures[channel]` (falling back to `reasons`).
- `GET /api/products/{id}/images` confirmed links are read from the `slots` array (Phase 1 shape); `rules` is
  rendered as key / value text per channel.
- The payload preview switches to a table when every preview object is flat and the publish has a CSV or XLSX file;
  JSON otherwise (a manual toggle is available).
- `GET /api/publishes/{id}/items` paging assumes 100 rows per page for the Next button; the first page is taken from
  the detail response's `items` until a status filter is set.
- `GET /api/channels/{code}/schema/diff` may 404 before the first refresh; the error is ignored.

## Phase 4 additions

Built to `docs/api-contract-phase4.md`. The client lives in `src/api/client.ts` as `aiApi` and `qualityApi`
(plus `api.approvals.queue(group, runId)`); the interfaces are appended to `src/api/types.ts`. Every AI result is an
`AiOutput` reviewed by a person: nothing on these screens writes a product value directly.

- Product detail: an Ask AI tab (hidden without the `run_ai` permission; admins pass) lists the product's applicable
  templates grouped by task type, takes a channel for adapt, free text, a document (base64) and confirmed image
  picks for extract, previews the rendered prompt with missing inputs, and shows each output as a review card
  (current versus proposed, word-level diff, grounding errors, NEEDS_INPUT chips that focus the attribute row,
  confidence for classify, check findings; Accept, Edit then accept, Regenerate, Reject with quick reasons). The
  readiness panel ends with the Quality section (GOV-03) listing each score's checks per channel.
- Product grid: `quality:overall` (in the default columns) and `quality:<channel>` computed columns render a grade
  pill with the score as tooltip; they sort, and the filter builder offers "is one of" over the grades A to E.
- Bulk actions > Run AI: picks an active template filtered to the grid level's target attributes plus an optional
  channel, calls `POST /api/ai/runs` with the current selection and opens `/ai/runs/{id}`.
- Approvals: Run filter from the response's `runs`, run and template chips on items, "Accept all in run" for users
  whose data rights give approve on every group the run writes (the server checks again).
- Admin > AI: Brand voice cards (tone, do and don't rules, blocked terms, trademark terms as key / value rows,
  punctuation rules, 5 to 10 examples, version shown; PUT bumps the version) and the Prompt templates manager
  (table, create and edit dialog with the placeholder helper, grouped input attributes, shot types, output
  attributes for extract and restructure, model task, max length; Preview on a product by entity id or style
  number search; Activate with the 409 eval-gate message; version history).
- Admin > Quality: settings (excluded groups, enabled checks and weights, grade bands), Recompute now, and the
  dashboard by family, season or channel with stacked grade bars and the average score. Home shows the family
  dashboard as a compact card.

### Phase 4 contract assumptions

- `GET /api/products/{id}/ai/templates` is "grouped by task type" in the contract; the client accepts a flat
  `PromptTemplate[]`, a `{task_type: PromptTemplate[]}` map or `{templates: PromptTemplate[]}` and groups client side.
- `GET /api/ai/outputs` also accepts `template_code=` (the Outputs tab filter); the backend may ignore it. List
  endpoints (`/api/ai/outputs`, `/api/ai/runs`) are assumed to page 50 rows; the Next button appears while a page
  is full.
- `POST /api/ai/runs` is expected to return the AiRun with `outputs` (the five samples); the run page re-reads the
  run and takes samples from `sample_entity_ids`, falling back to the first five outputs.
- "Accept all" on the run page checks approve rights against the attribute codes seen in the run's outputs; before
  any output exists the button stays disabled.
- Template create and update send the PromptTemplate fields without version, status and timestamps; update also
  sends `note` for the version history and `status: "retired"` for the Retire action.
- `PUT /api/ai/brand-voices/{code}` on an unknown code is used to create a brand voice (there is no POST in the
  contract).
- Quality settings: the checks list is the union of `weights` keys and `enabled_checks`; new check codes can be
  typed in and are sent with weight 1.
- Template preview search uses `POST /api/products/query` with a `style_number contains` filter at the target
  attribute's level (style-color when unknown).
- The `run_ai` permission is read from `/api/me` `permissions`; admins (`admin_metadata`) always see the AI screens.
- Rejecting from the run page's outputs table sends the fixed reason "Rejected from the run page"; the card view
  asks for a reason.

## Phase 5 additions

Built to `docs/api-contract-phase5.md` (marketplaces, feeds, Shopify sandbox). The client additions live in
`src/api/client.ts` as `channelApi.transport`, `channelApi.saveTransport`, `channelApi.uploadFeedTemplate`,
`channelApi.feedTemplateUrl`, `publishApi.deliver` and `api.packages.sandboxRun`; the interfaces (`FeedColumn`,
`ChannelTransport`, `FeedTemplateUpload`, `DeliveryResult`, `WalmartFeedSummary`, `SandboxReport`) are appended to
`src/api/types.ts`, and `PublishItem`, `ChannelHealth`, `PackageFile` and `PackageDetail` gained the optional Phase 5
fields.

- Admin > Channels > Transport (`src/admin/channel/TransportTab.tsx`, EXP-09, EXP-10, EXP-11): transport radio
  (download, SFTP, email, API), file format, feed template upload (`.xlsx` or `.csv`) with the stored name as a
  download link and the header columns returned by the upload, header row, and the feed columns table (header,
  source picker, Always include, case transform, value map as key / value rows, Required, add / remove / reorder,
  "Columns from template"). The source picker is metadata-driven: core identifiers as `core.<field>`, every attribute
  grouped by attribute group, a typed reference path (also used for `erp.<field>`), `image:1` to `image:6`,
  `nrf_color`, `nrf_size` and `gtin`. Conditional sections: SFTP (host, port, path, username, secret name), Email
  (recipients, subject), Walmart (spec version, product type, max items per feed, up to three variant attribute
  pickers) when the adapter is `walmart_mp`, Rithum (program, supplier id, VPN prefix, family rules) when the adapter
  contains `rithum`. The tab has its own Save / Discard; Save needs the `edit_profile` channel right (`*` wildcard,
  admins pass).
- Publish detail: a Delivery card renders `summary.delivery` (transport, status pill, detail, files, time) with
  "Deliver now" for SFTP and email channels (409 shown as a clear message pointing at the Transport tab); a Walmart
  feeds card renders `summary.walmart` (feed ids, status, next poll, poll count) with "Poll now" calling the feedback
  endpoint without a file; the items table gains a Listing quality column when any item carries a score.
- Channel Health tab: "Listing quality avg" pill and "Feeds in progress" count when the response carries them.
- Package detail: files show their kind (`matrixify` highlighted, D-13); the Shopify sandbox section offers "Plan
  only" and "Run against sandbox" (confirm dialog), shows 409 as "Sandbox store not configured" with the two env var
  names, and renders the SandboxReport (store, mode, product count, mutations table, protected-fields check table with
  changed rows in red, errors list, time). The stored `sandbox_report` is shown on load.

### Phase 5 contract assumptions

- `GET /api/channels/{code}/transport` is expected to return the full `ChannelTransport`; missing optional blocks
  (`sftp`, `email`, `walmart`, `rithum`) are treated as `null` and `feed_columns` as `[]`. The PUT sends the whole
  draft, including blocks for transports not currently selected, so switching transport does not lose settings.
- Feed column sources for the core identifiers are sent with the `core.` prefix (`core.style_number`, ...), as the
  Phase 5 contract lists; `erp.<field>` and dotted reference paths are typed through the "Reference path" option.
- The header columns of a stored template are only known after an upload in the current session (the GET does not
  return them); "Columns from template" keeps the source of existing rows whose header matches and adds the rest with
  an empty source.
- `Publish.summary.delivery`, `summary.walmart` and `summary.listing_quality` are read with type guards from the
  untyped summary; `listing_quality` per item falls back to `summary.listing_quality[external_id]` when the items
  endpoint does not carry it.
- "Deliver now" is offered when the channel transport (from GET transport, falling back to `channel.config.transport`)
  is `sftp` or `email`, or when a previous delivery used one of them; the server's 409 is shown inline otherwise.
- The Walmart adapter is detected as `adapter === "walmart_mp"` (or containing "walmart"); Rithum as the adapter
  containing "rithum". A section is also shown when the server already returns the matching block.
- `POST /api/packages/{id}/sandbox-run` is allowed from the UI only when the package is `ready` or `reconciled`;
  executed runs refetch the package to pick up the stored `sandbox_report`.

## Phase 6 additions

Built to `docs/api-contract-phase6.md` (relationships, whole-product restore and change sets, digest settings,
adapter error rates). The client additions live in `src/api/client.ts` as `relationshipApi`, `changeSetApi`,
`settingsApi` and `api.products.restoreTo`; the interfaces (`RelationshipType`, `Relationship`,
`RelationshipAddResult`, `ChangeSet`, `RestoreToResult`, `RollbackResult`, `MeSettings`, `AdapterErrorRate`) are
appended to `src/api/types.ts`, `Readiness` gained the optional `warnings` list and `Telemetry` the optional
`adapter_error_rates`.

- New file `src/detail/RelationshipsTab.tsx` (DM-13): the product detail Relationships tab (count in the tab label)
  lists own and inherited links grouped by type, the target as a link to its product page, "Inherited from style"
  and amber "Broken" badges, quantity when present, Remove on own links, and an add form with a type select limited
  to the product's level, a debounced product search picker over `POST /api/products/query`, a paste box for a
  comma-separated list, a quantity input when the type allows it, and the skipped tokens with reasons after an add.
  The form and Remove are hidden without edit on the `style_details` group (the `*` wildcard applies, admins pass).
- `src/detail/HistoryTab.tsx` (GOV-02): "Restore to this point" per row opens a confirm dialog, posts
  `POST /api/products/{id}/restore-to` with the row's `set_at` and shows the restored count and per-attribute
  outcomes; the Change sets panel below the table lists `GET /api/change-sets?entity_id=` with a kind badge, who,
  when, description, changes and Roll back (replaced by the rolled back date once `rolled_back_at` is set); the
  rollback result shows the restored count and the `manual` list when not empty.
- `src/components/NotificationBell.tsx` (DM-07, DM-09): the dropdown ends with an Email digest select (daily,
  weekly, off) backed by `GET/PUT /api/me/settings`, with a toast on save.
- `src/admin/Telemetry.tsx` (GOV-04): an Adapter error rates table (adapter, calls, errors, rate pill green under
  5 percent, amber under 20, red otherwise, "no calls" for null, last error with time) above the Adapter errors list.
- Readiness `warnings` are rendered in the product detail Readiness panel (amber list) and in the readiness pill
  tooltip used by the grid and the detail header.

### Phase 6 contract assumptions

- Relationship types are filtered to `enabled` ones whose `level` equals the product's level; SKUs get a note
  instead of the form. The first matching type is preselected.
- `POST .../relationships` is sent with `targets` (entity ids from the picker) and `paste` together when both are
  filled; `quantity` is only sent for a type with `allows_quantity`.
- `GET /api/change-sets` is paged 50 rows per page; the rollback result's extra keys are ignored.
- `GET /api/me/settings` is only requested while the bell dropdown is open; the select shows `daily` until it loads.

## Grid keyboard reference (DM-03)

- Arrow keys move the active cell, Shift+Arrow extends the selection, Tab / Shift+Tab move horizontally.
- Enter or F2 or double-click edits the active cell; typing a character starts an edit with that character.
- While editing: Enter commits and moves down, Tab commits and moves right, Escape cancels.
- Ctrl+C copies the selected rectangle as TSV, Ctrl+V pastes a TSV block starting at the active cell (Excel compatible).
- Ctrl+D fills the top row of the selection down, Delete clears the selected editable cells, Ctrl+Z undoes the last batch.
