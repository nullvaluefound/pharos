import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bell, Check, LogOut, Moon, Search, Settings, Sun, User } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { effectiveDark, useTheme } from "../lib/theme";
import type { NotificationList } from "../lib/types";
import { timeAgo } from "../lib/format";

export function TopBar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const theme = useTheme((s) => s.theme);
  const toggleTheme = useTheme((s) => s.toggle);
  const isDark = effectiveDark(theme);
  const [q, setQ] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const bellRef = useRef<HTMLDivElement>(null);
  const qc = useQueryClient();

  const { data: notifs } = useQuery<NotificationList>({
    queryKey: ["notifications"],
    queryFn: () => api<NotificationList>("/notifications?limit=15"),
    refetchInterval: 60_000,
  });

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node))
        setMenuOpen(false);
      if (bellRef.current && !bellRef.current.contains(e.target as Node))
        setBellOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    if (q.trim()) navigate(`/search?q=${encodeURIComponent(q.trim())}`);
  }

  async function markRead(id: number) {
    await api(`/notifications/${id}/read`, { method: "POST" });
    qc.invalidateQueries({ queryKey: ["notifications"] });
  }

  async function markAllRead() {
    await api("/notifications/read-all", { method: "POST" });
    qc.invalidateQueries({ queryKey: ["notifications"] });
  }

  return (
    <header className="flex items-center gap-3 border-b border-ink-200 bg-white px-5 py-2.5 dark:border-pharos-navy-500 dark:bg-pharos-navy-700">
      <form onSubmit={submitSearch} className="relative flex-1 max-w-xl">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search articles, threat actors, CVEs…"
          className="input !pl-9 !py-2"
        />
      </form>

      <div className="ml-auto flex items-center gap-1">
        <button
          onClick={toggleTheme}
          className="btn-ghost !py-1.5"
          aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
          title={isDark ? "Switch to light mode" : "Switch to dark mode"}
        >
          {isDark ? (
            <>
              <Sun className="h-4 w-4 text-pharos-gold-400" />
              <span className="hidden text-xs font-medium sm:inline">Light</span>
            </>
          ) : (
            <>
              <Moon className="h-4 w-4" />
              <span className="hidden text-xs font-medium sm:inline">Dark</span>
            </>
          )}
        </button>

        <div ref={bellRef} className="relative">
          <button
            className="btn-ghost relative !p-2"
            onClick={() => setBellOpen((v) => !v)}
            aria-label="Notifications"
          >
            <Bell className="h-5 w-5" />
            {notifs && notifs.unread_count > 0 && (
              <span className="absolute right-1 top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-beam-600 px-1 text-[10px] font-bold text-white">
                {notifs.unread_count > 9 ? "9+" : notifs.unread_count}
              </span>
            )}
          </button>
          {bellOpen && (
            <div className="absolute right-0 top-full z-30 mt-1 w-96 rounded-xl border border-ink-200 bg-white shadow-card animate-slide-up">
              <div className="flex items-center justify-between border-b border-ink-100 px-4 py-2.5">
                <span className="text-sm font-semibold">Notifications</span>
                {notifs && notifs.unread_count > 0 && (
                  <button onClick={markAllRead} className="text-xs text-beam-600 hover:underline">
                    Mark all read
                  </button>
                )}
              </div>
              <div className="max-h-[26rem] overflow-y-auto">
                {!notifs || notifs.items.length === 0 ? (
                  <div className="px-4 py-8 text-center text-sm text-ink-400">
                    No notifications yet
                  </div>
                ) : (
                  notifs.items.map((n) => (
                    <Link
                      key={n.id}
                      to={n.article_id ? `/article/${n.article_id}` : "/watches"}
                      onClick={() => {
                        if (!n.is_read) markRead(n.id);
                        setBellOpen(false);
                      }}
                      className={`block border-b border-ink-100 px-4 py-3 last:border-0 hover:bg-ink-50 ${
                        n.is_read ? "" : "bg-beam-50/50"
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        {!n.is_read && (
                          <span className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-beam-500" />
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-ink-900 truncate">
                            {n.title}
                          </div>
                          {n.body && (
                            <div className="mt-0.5 text-xs text-ink-500 line-clamp-2">
                              {n.body}
                            </div>
                          )}
                          <div className="mt-1 text-[11px] text-ink-400">
                            {timeAgo(n.created_at)}
                          </div>
                        </div>
                      </div>
                    </Link>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        <div ref={menuRef} className="relative">
          <button
            className="btn-ghost flex items-center gap-2 !py-1.5"
            onClick={() => setMenuOpen((v) => !v)}
          >
            <span className="grid h-7 w-7 place-items-center rounded-full bg-beam-100 text-xs font-bold text-beam-700 dark:bg-pharos-gold-500/20 dark:text-pharos-gold-300">
              {(user?.username || "?").slice(0, 1).toUpperCase()}
            </span>
            <span className="hidden text-sm font-medium md:inline">{user?.username}</span>
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full z-30 mt-1 w-56 rounded-xl border border-ink-200 bg-white shadow-card animate-slide-up">
              <div className="border-b border-ink-100 px-4 py-3">
                <div className="text-sm font-semibold">{user?.username}</div>
                <div className="text-xs text-ink-500">
                  {user?.is_admin ? "Administrator" : "User"}
                </div>
              </div>
              <Link
                to="/settings"
                onClick={() => setMenuOpen(false)}
                className="flex items-center gap-2 px-4 py-2 text-sm hover:bg-ink-50"
              >
                <Settings className="h-4 w-4" /> Settings
              </Link>
              <Link
                to="/feeds"
                onClick={() => setMenuOpen(false)}
                className="flex items-center gap-2 px-4 py-2 text-sm hover:bg-ink-50"
              >
                <Check className="h-4 w-4" /> Manage feeds
              </Link>
              <button
                onClick={logout}
                className="flex w-full items-center gap-2 border-t border-ink-100 px-4 py-2 text-sm text-danger-600 hover:bg-danger-50"
              >
                <LogOut className="h-4 w-4" /> Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

export const TopBarUser = User; // re-export for tree-shaking convenience
