import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { ArticleDrawer } from "./ArticleDrawer";
import { ErrorBoundary } from "./ErrorBoundary";

export function AppShell() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-auto bg-ink-50">
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      {/* Mounted once at the shell so it floats over any page. Wrapped in its
          own boundary so a single broken article can't blank the whole app. */}
      <ErrorBoundary>
        <ArticleDrawer />
      </ErrorBoundary>
    </div>
  );
}
