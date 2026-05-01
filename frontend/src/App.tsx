import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { useAuth } from "./lib/auth";
import { useTheme } from "./lib/theme";

import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { StreamPage } from "./pages/StreamPage";
import { ArticlePage } from "./pages/ArticlePage";
import { SearchPage } from "./pages/SearchPage";
import { ArchiveSearchPage } from "./pages/ArchiveSearchPage";
import { WatchesPage } from "./pages/WatchesPage";
import { FeedsPage } from "./pages/FeedsPage";
import { SavedPage } from "./pages/SavedPage";
import { MetricsPage } from "./pages/MetricsPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export function App() {
  const { user, ready, bootstrap } = useAuth();
  const initTheme = useTheme((s) => s.initialize);
  const hydrateTheme = useTheme((s) => s.hydrateFromServer);

  useEffect(() => {
    bootstrap();
    initTheme();
  }, [bootstrap, initTheme]);

  // Once we know who the user is, pull their saved theme preference
  // from the server (so a dark-mode pick on one device follows them
  // to a fresh browser on another).
  useEffect(() => {
    if (user) hydrateTheme();
  }, [user, hydrateTheme]);

  if (!ready) {
    return (
      <div className="flex h-full items-center justify-center text-ink-400">
        <div className="animate-pulse text-sm">Loading Pharos…</div>
      </div>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/register" element={user ? <Navigate to="/" replace /> : <RegisterPage />} />

      <Route element={user ? <AppShell /> : <Navigate to="/login" replace />}>
        <Route index element={<Navigate to="/stream" replace />} />
        <Route path="/stream" element={<StreamPage />} />
        <Route path="/article/:id" element={<ArticlePage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/archive" element={<ArchiveSearchPage />} />
        <Route path="/saved" element={<SavedPage />} />
        <Route path="/watches" element={<WatchesPage />} />
        <Route path="/feeds" element={<FeedsPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/metrics" element={<MetricsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
