# Swim USA PIM frontend

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
  detail/     product detail pieces: tree, attribute form, images, history, comments, workflow panel, carryover
  imports/    import wizard steps: shared helpers, Upload, Map (with value mappings and templates), Validate, Match, Review
  workflows/  workflow item actions (advance, reject, assign) shared by My Work and the detail panel
  admin/      admin tabs (including Rules)
  pages/      one file per route, each headed with the requirement IDs it implements
  lib/        format, validation, tsv helpers
```

## Routes

| Path | Page | Spec |
|---|---|---|
| `/` | Home dashboard | DM-10 |
| `/products` | Product grid with saved views and in-grid editing | DM-01, DM-02, DM-03, EXP-03 |
| `/products/:id` | Product detail | DM-01, DM-05, DM-06, DM-11, IMG-05, GOV-02 |
| `/reference/:type`, `/reference/:type/:id` | Reference entities | DM-11 |
| `/approvals` | Approval queue | DM-08 |
| `/packages`, `/packages/:id` | Shopify update packages | EXP-13 |
| `/images` | Image review queues | IMG-05 |
| `/admin/:tab` | Metadata, roles, rules, reports, telemetry | 1.3, RBAC, IMP-11, GOV-01, GOV-04, GOV-07 |
| `/admin/rules` | Rules engine: list, editor, preview on samples, activate, run now, runs | GOV-01, GOV-06 |
| `/imports` | Import history, mapping templates, import sources | IMP-07, IMP-02, IMP-01 |
| `/imports/new`, `/imports/:id` | Import wizard: Upload, Map, Validate, Match, Review and Commit | IMP-01 to IMP-08, IMP-12 |
| `/worksheets` | Keyed worksheet export | IMP-12 |
| `/bulk` | Bulk action history with reports and rollback (the dialog lives on `/products`) | DM-04 |
| `/workflows` | My Work: Mine / My role / All, Manager, Admin definitions | DM-07 |
| `/compare?a=&b=&channel=` | Compare two products, copy values across | DM-06 |

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

## Grid keyboard reference (DM-03)

- Arrow keys move the active cell, Shift+Arrow extends the selection, Tab / Shift+Tab move horizontally.
- Enter or F2 or double-click edits the active cell; typing a character starts an edit with that character.
- While editing: Enter commits and moves down, Tab commits and moves right, Escape cancels.
- Ctrl+C copies the selected rectangle as TSV, Ctrl+V pastes a TSV block starting at the active cell (Excel compatible).
- Ctrl+D fills the top row of the selection down, Delete clears the selected editable cells, Ctrl+Z undoes the last batch.
