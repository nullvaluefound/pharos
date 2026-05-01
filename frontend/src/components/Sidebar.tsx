import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  Bookmark,
  ChevronDown,
  ChevronRight,
  Archive,
  Eye,
  FileText,
  FolderClosed,
  FolderOpen,
  Inbox,
  Plus,
  Rss,
  Search,
  Settings,
  Trash2,
} from "lucide-react";

import { api } from "../lib/api";
import type { FeedOut, FolderInfo, WatchOut } from "../lib/types";
import { hostFromUrl } from "../lib/format";

const COLLAPSED_KEY = "pharos.sidebar.collapsed";

function useCollapsed() {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem(COLLAPSED_KEY) || "{}");
    } catch {
      return {};
    }
  });
  useEffect(() => {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify(collapsed));
  }, [collapsed]);
  const toggle = (k: string) =>
    setCollapsed((c) => ({ ...c, [k]: !c[k] }));
  return { collapsed, toggle };
}

export function Sidebar() {
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const activeFeed = params.get("feed_id");
  const activeFolder = params.get("folder");
  const activeWatch = params.get("watch");
  const { collapsed, toggle } = useCollapsed();

  const { data: feeds } = useQuery<FeedOut[]>({
    queryKey: ["feeds"],
    queryFn: () => api<FeedOut[]>("/feeds"),
  });
  const { data: allFolders } = useQuery<FolderInfo[]>({
    queryKey: ["folders"],
    queryFn: () => api<FolderInfo[]>("/feeds/folders"),
  });
  const { data: watches } = useQuery<WatchOut[]>({
    queryKey: ["watches"],
    queryFn: () => api<WatchOut[]>("/watches"),
  });

  // Group feeds by folder, honoring the order returned by the API
  // (which already applies user_folders.position + sort_order).
  const grouped = useMemo(() => {
    const m = new Map<string, FeedOut[]>();
    for (const fo of allFolders || []) m.set(fo.name, []);
    for (const f of feeds || []) {
      const k = f.folder || "Unsorted";
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(f);
    }
    // Preserve API-supplied folder ordering; just append any folders that
    // appeared via subscriptions but not in the folders list.
    return [...m.entries()];
  }, [feeds, allFolders]);

  async function deleteFolder(name: string) {
    if (!confirm(`Delete group "${name}"? Feeds inside will move to Unsorted.`)) {
      return;
    }
    await api(`/feeds/folders/${encodeURIComponent(name)}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["folders"] });
    qc.invalidateQueries({ queryKey: ["feeds"] });
    window.dispatchEvent(new Event("pharos:folders-changed"));
  }

  const [showNewGroup, setShowNewGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [creatingGroup, setCreatingGroup] = useState(false);

  async function createGroup(e: React.FormEvent) {
    e.preventDefault();
    const name = newGroupName.trim();
    if (!name) return;
    setCreatingGroup(true);
    try {
      await api("/feeds/folders", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      setNewGroupName("");
      setShowNewGroup(false);
      // refetch folders
      window.dispatchEvent(new Event("pharos:folders-changed"));
    } finally {
      setCreatingGroup(false);
    }
  }

  // Refetch on cross-component folder changes (e.g. ManageFolders).
  useEffect(() => {
    const handler = () => {
      qc.invalidateQueries({ queryKey: ["folders"] });
      qc.invalidateQueries({ queryKey: ["feeds"] });
    };
    window.addEventListener("pharos:folders-changed", handler);
    return () => window.removeEventListener("pharos:folders-changed", handler);
  }, [qc]);

  return (
    <aside className="hidden w-64 flex-shrink-0 flex-col border-r border-ink-200 bg-white md:flex dark:border-pharos-navy-500 dark:bg-pharos-navy-700">
      <Link
        to="/"
        className="flex items-center gap-2 px-5 py-4 transition-opacity hover:opacity-80"
        title="Pharos — back to stream"
      >
        <img
          src="/logo.png"
          alt="Pharos"
          className="h-9 w-9 rounded-lg shadow-sm ring-1 ring-ink-200/40 dark:ring-pharos-navy-500"
        />
        <div>
          <div className="font-semibold leading-none">Pharos</div>
          <div className="text-[11px] text-ink-400">A beam through the noise</div>
        </div>
      </Link>

      <nav className="flex-1 overflow-y-auto px-3 pb-4">
        <NavLink
          to="/stream"
          end
          className={({ isActive }) =>
            navItemClass(isActive && !activeFeed && !activeFolder && !activeWatch)
          }
        >
          <Inbox className="h-4 w-4" /> All articles
        </NavLink>
        <NavLink to="/saved" className={({ isActive }) => navItemClass(isActive)}>
          <Bookmark className="h-4 w-4" /> Saved
        </NavLink>
        <NavLink to="/search" className={({ isActive }) => navItemClass(isActive)}>
          <Search className="h-4 w-4" /> Search
        </NavLink>
        <NavLink to="/archive" className={({ isActive }) => navItemClass(isActive)}>
          <Archive className="h-4 w-4" /> Archive
        </NavLink>
        <NavLink to="/reports" className={({ isActive }) => navItemClass(isActive)}>
          <FileText className="h-4 w-4" /> Reports
        </NavLink>
        <NavLink to="/metrics" className={({ isActive }) => navItemClass(isActive)}>
          <BarChart3 className="h-4 w-4" /> Insights
        </NavLink>

        {/* Watches */}
        <SectionHeader
          label="Watches"
          collapsed={!!collapsed["watches"]}
          onToggle={() => toggle("watches")}
          action={
            <Link to="/watches" className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700">
              <Plus className="h-3.5 w-3.5" />
            </Link>
          }
        />
        {!collapsed["watches"] && (
          <div className="space-y-0.5">
            {watches && watches.length > 0 ? (
              watches.map((w) => (
                <Link
                  key={w.id}
                  to={`/stream?watch=${w.id}`}
                  className={navItemClass(String(w.id) === activeWatch)}
                >
                  <Eye className="h-4 w-4 flex-shrink-0 text-ink-400" />
                  <span className="truncate">{w.name}</span>
                </Link>
              ))
            ) : (
              <div className="px-3 py-2 text-xs text-ink-400">
                No watches yet.{" "}
                <Link to="/watches" className="text-beam-600 hover:underline">
                  Create one
                </Link>
              </div>
            )}
          </div>
        )}

        {/* Feed groups */}
        <SectionHeader
          label="Feed groups"
          collapsed={false}
          onToggle={() => {}}
          showChevron={false}
          action={
            <button
              onClick={() => setShowNewGroup((v) => !v)}
              className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
              title="Create empty group"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          }
        />
        {showNewGroup && (
          <form onSubmit={createGroup} className="mb-2 flex gap-1 px-3">
            <input
              autoFocus
              value={newGroupName}
              onChange={(e) => setNewGroupName(e.target.value)}
              placeholder="Group name"
              className="input !py-1 !text-xs"
            />
            <button
              type="submit"
              disabled={creatingGroup || !newGroupName.trim()}
              className="btn-primary !py-1 !text-xs"
            >
              Add
            </button>
          </form>
        )}

        <div className="space-y-0.5">
          {grouped.map(([folder, list]) => {
            const key = `folder:${folder}`;
            const isCollapsed = collapsed[key] !== false; // default collapsed
            const canDelete = folder !== "Unsorted";
            return (
              <div key={folder}>
                <div className="group flex items-center">
                  <button
                    onClick={() => toggle(key)}
                    className="rounded p-1 text-ink-400 hover:bg-ink-100"
                  >
                    {isCollapsed ? (
                      <ChevronRight className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronDown className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <Link
                    to={`/stream?folder=${encodeURIComponent(folder)}`}
                    className={`flex-1 ${navItemClass(activeFolder === folder)}`}
                  >
                    {isCollapsed ? (
                      <FolderClosed className="h-4 w-4 text-ink-400" />
                    ) : (
                      <FolderOpen className="h-4 w-4 text-beam-500" />
                    )}
                    <span className="truncate">{folder}</span>
                    <span className="ml-auto text-[10px] text-ink-400">{list.length}</span>
                  </Link>
                  {canDelete && (
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        deleteFolder(folder);
                      }}
                      className="ml-0.5 rounded p-1 text-ink-300 opacity-0 hover:bg-danger-50 hover:text-danger-600 group-hover:opacity-100"
                      title={`Delete group "${folder}"`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  )}
                </div>
                {!isCollapsed && (
                  <div className="ml-6 space-y-0.5">
                    {list.length === 0 && (
                      <div className="px-3 py-1 text-[11px] italic text-ink-400">
                        No feeds yet
                      </div>
                    )}
                    {list.map((f) => (
                      <Link
                        key={f.id}
                        to={`/stream?feed_id=${f.id}`}
                        className={navItemClass(String(f.id) === activeFeed) + " !py-1.5"}
                      >
                        <Rss className="h-3.5 w-3.5 flex-shrink-0 text-ink-300" />
                        <span className="truncate">
                          {f.custom_title || f.title || hostFromUrl(f.url)}
                        </span>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </nav>

      <div className="border-t border-ink-100 px-3 py-2">
        <NavLink to="/feeds" className={({ isActive }) => navItemClass(isActive) + " !text-xs"}>
          <Rss className="h-4 w-4" /> Manage feeds
        </NavLink>
        <NavLink to="/settings" className={({ isActive }) => navItemClass(isActive) + " !text-xs"}>
          <Settings className="h-4 w-4" /> Settings
        </NavLink>
      </div>
    </aside>
  );
}

function navItemClass(active: boolean): string {
  return [
    "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors",
    active
      ? "bg-beam-50 text-beam-700 font-medium"
      : "text-ink-700 hover:bg-ink-100",
  ].join(" ");
}

function SectionHeader({
  label,
  collapsed,
  onToggle,
  action,
  showChevron = true,
}: {
  label: string;
  collapsed: boolean;
  onToggle: () => void;
  action?: React.ReactNode;
  showChevron?: boolean;
}) {
  return (
    <div className="mt-4 flex items-center px-2">
      <button
        onClick={onToggle}
        className="flex flex-1 items-center gap-1 rounded px-1 py-1 text-[11px] font-bold uppercase tracking-wider text-ink-400 hover:text-ink-700"
      >
        {showChevron &&
          (collapsed ? (
            <ChevronRight className="h-3 w-3" />
          ) : (
            <ChevronDown className="h-3 w-3" />
          ))}
        <span>{label}</span>
      </button>
      {action}
    </div>
  );
}
