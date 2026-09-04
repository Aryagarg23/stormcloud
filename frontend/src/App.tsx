import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell, ProtectedRoute } from "./components/AppShell";
import { AcceptInvitePage, LoginPage } from "./pages/AuthPages";
import { HomePage } from "./pages/HomePage";
import { SubmitBundlePage, SubmitSignalPage } from "./pages/SubmitPages";
import { OperationPage } from "./pages/OperationPage";
import { SignalPage } from "./pages/SignalPage";
import { BundlePage, BundlesPage } from "./pages/BundlePages";
import { AdminPage } from "./pages/AdminPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/accept-invite" element={<AcceptInvitePage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="submit" element={<SubmitSignalPage />} />
          <Route path="signals/:id" element={<SignalPage />} />
          <Route path="operations/:id" element={<OperationPage />} />
          <Route path="bundles" element={<BundlesPage />} />
          <Route path="bundles/new" element={<SubmitBundlePage />} />
          <Route path="bundles/:id" element={<BundlePage />} />
          <Route path="admin" element={<AdminPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}
