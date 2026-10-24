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
  components/ AppShell, Common (Spinner, ErrorBox, Dialog, badges), ValueEditor (editors by data_type)
  grid/       product grid pieces: field catalog, filter builder, column chooser, saved views, edit batching
  detail/     product detail pieces: tree, attribute form, images, history
  admin/      admin tabs
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
| `/admin/:tab` | Metadata, roles, reports, telemetry | 1.3, RBAC, IMP-11, GOV-04, GOV-07 |

## Grid keyboard reference (DM-03)

- Arrow keys move the active cell, Shift+Arrow extends the selection, Tab / Shift+Tab move horizontally.
- Enter or F2 or double-click edits the active cell; typing a character starts an edit with that character.
- While editing: Enter commits and moves down, Tab commits and moves right, Escape cancels.
- Ctrl+C copies the selected rectangle as TSV, Ctrl+V pastes a TSV block starting at the active cell (Excel compatible).
- Ctrl+D fills the top row of the selection down, Delete clears the selected editable cells, Ctrl+Z undoes the last batch.
