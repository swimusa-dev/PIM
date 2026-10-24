// Route table. The FastAPI app serves index.html for every non-API path, so BrowserRouter works.

import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { HomePage } from "./pages/Home";
import { ProductGridPage } from "./pages/ProductGrid";
import { ProductDetailPage } from "./pages/ProductDetail";
import { ReferenceListPage, ReferenceDetailPage, ReferenceIndexPage } from "./pages/Reference";
import { ApprovalsPage } from "./pages/Approvals";
import { PackagesPage } from "./pages/Packages";
import { PackageDetailPage } from "./pages/PackageDetail";
import { ImagesPage } from "./pages/Images";
import { AdminPage } from "./pages/Admin";
import { ImportsPage } from "./pages/Imports";
import { ImportWizardPage } from "./pages/ImportWizard";
import { WorksheetsPage } from "./pages/Worksheets";
import { BulkPage } from "./pages/Bulk";
import { WorkflowsPage } from "./pages/Workflows";
import { ComparePage } from "./pages/Compare";
import { ExportsPage } from "./pages/Exports";
import { ExportDetailPage } from "./pages/ExportDetail";
import { Empty } from "./components/Common";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/products" element={<ProductGridPage />} />
        <Route path="/products/:id" element={<ProductDetailPage />} />
        <Route path="/reference" element={<ReferenceIndexPage />} />
        <Route path="/reference/:type" element={<ReferenceListPage />} />
        <Route path="/reference/:type/:id" element={<ReferenceDetailPage />} />
        <Route path="/approvals" element={<ApprovalsPage />} />
        <Route path="/packages" element={<PackagesPage />} />
        <Route path="/packages/:id" element={<PackageDetailPage />} />
        <Route path="/exports" element={<ExportsPage />} />
        <Route path="/exports/:id" element={<ExportDetailPage />} />
        <Route path="/images" element={<ImagesPage />} />
        <Route path="/imports" element={<ImportsPage />} />
        <Route path="/imports/new" element={<ImportWizardPage />} />
        <Route path="/imports/:id" element={<ImportWizardPage />} />
        <Route path="/worksheets" element={<WorksheetsPage />} />
        <Route path="/bulk" element={<BulkPage />} />
        <Route path="/workflows" element={<WorkflowsPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/admin/:tab" element={<AdminPage />} />
        <Route path="/index.html" element={<Navigate to="/" replace />} />
        <Route
          path="*"
          element={
            <Empty title="Page not found">Use the navigation on the left to open a section of the PIM.</Empty>
          }
        />
      </Route>
    </Routes>
  );
}
