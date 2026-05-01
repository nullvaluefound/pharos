import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FolderPlus,
  GripVertical,
  Pencil,
  Plus,
  RefreshCw,
  Rss,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import {
  closestCenter,
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  pointerWithin,
  rectIntersection,
  useDroppable,
  useSensor,
  useSensors,
  type CollisionDetection,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { Empty } from "../components/Empty";
import { PageHeader } from "../components/PageHeader";
import { api, apiBlob } from "../lib/api";
import type { FeedOut, FolderInfo } from "../lib/types";
import { hostFromUrl, timeAgo } from "../lib/format";

interface CatalogFeed {
  title: string | null;
  url: string;
  folder: string | null;
  tags: string[];
}
interface CatalogCategory {
  id: string;
  name: string;
  folder: string;
  description: string;
  enabled_by_default: boolean;
  feeds: CatalogFeed[];
}
interface CatalogResp {
  categories: CatalogCategory[];
  presets: { id: string; name: string; description: string; categories: string[] }[];
}

const UNSORTED = "Unsorted";

// --------- IDs used by dnd-kit -----------
// Folder draggables:  "folder:<name>"
// Feed draggables:    "feed:<id>"
// Folder droppables (also used as folder draggables): same id reused
const folderId = (n: string) => `folder:${n}`;
const feedId = (id: number) => `feed:${id}`;
const isFolderId = (id: string | number) =>
  typeof id === "string" && id.startsWith("folder:");
const isFeedId = (id: string | number) =>
  typeof id === "string" && id.startsWith("feed:");
const folderName = (id: string) => id.slice("folder:".length);
const feedNum = (id: string) => Number(id.slice("feed:".length));

export function FeedsPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"my" | "discover">("my");

  const feedsQ = useQuery<FeedOut[]>({
    queryKey: ["feeds"],
    queryFn: () => api<FeedOut[]>("/feeds"),
  });
  const foldersQ = useQuery<FolderInfo[]>({
    queryKey: ["folders"],
    queryFn: () => api<FolderInfo[]>("/feeds/folders"),
  });
  const catalogQ = useQuery<CatalogResp>({
    queryKey: ["catalog"],
    queryFn: () => api<CatalogResp>("/feeds/catalog"),
    enabled: tab === "discover",
  });

  // Local optimistic copy of the grouping the user is dragging through.
  // Reseeded any time the server query updates.
  const [order, setOrder] = useState<{
    folders: string[];
    byFolder: Record<string, FeedOut[]>;
  } | null>(null);

  useEffect(() => {
    if (!feedsQ.data || !foldersQ.data) return;
    const allFolderNames = new Set<string>([UNSORTED]);
    for (const f of foldersQ.data) allFolderNames.add(f.name);
    for (const f of feedsQ.data) allFolderNames.add(f.folder || UNSORTED);

    // Honor the order the API returned (server already applied user_folders.position
    // + sort_order in its query).
    const seenFolder = new Set<string>();
    const orderedFolders: string[] = [];
    for (const f of foldersQ.data) {
      if (!seenFolder.has(f.name)) {
        seenFolder.add(f.name);
        orderedFolders.push(f.name);
      }
    }
    for (const n of allFolderNames) {
      if (!seenFolder.has(n)) {
        seenFolder.add(n);
        orderedFolders.push(n);
      }
    }

    const byFolder: Record<string, FeedOut[]> = {};
    for (const n of orderedFolders) byFolder[n] = [];
    for (const f of feedsQ.data) {
      const k = f.folder || UNSORTED;
      (byFolder[k] = byFolder[k] || []).push(f);
    }

    setOrder({ folders: orderedFolders, byFolder });
  }, [feedsQ.data, foldersQ.data]);

  function refetchAll() {
    qc.invalidateQueries({ queryKey: ["feeds"] });
    qc.invalidateQueries({ queryKey: ["folders"] });
    window.dispatchEvent(new Event("pharos:folders-changed"));
  }

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const toggleSel = (id: number) =>
    setSelected((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  const clearSel = () => setSelected(new Set());

  // ----- DnD plumbing -----
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const [activeId, setActiveId] = useState<string | null>(null);

  // When dragging a feed, prefer the folder it would land in (droppable
  // target) over the underlying sortable feed; this lets us drop into an
  // empty folder. When dragging a folder, use closestCenter on folder ids.
  const collisionDetection: CollisionDetection = (args) => {
    const aid = String(args.active.id);
    if (isFolderId(aid)) {
      const onlyFolders = args.droppableContainers.filter((c) =>
        isFolderId(String(c.id)),
      );
      return closestCenter({ ...args, droppableContainers: onlyFolders });
    }
    // Dragging a feed: try pointer-within first (catches empty-folder drops),
    // then fall back to rect intersection for in-list reorders.
    const within = pointerWithin(args);
    if (within.length) return within;
    return rectIntersection(args);
  };

  function findFeedFolder(id: number): string | null {
    if (!order) return null;
    for (const [folder, list] of Object.entries(order.byFolder)) {
      if (list.some((f) => f.id === id)) return folder;
    }
    return null;
  }

  async function persistFeedOrder(byFolder: Record<string, FeedOut[]>) {
    const items: { feed_id: number; folder: string; sort_order: number }[] = [];
    for (const [folder, list] of Object.entries(byFolder)) {
      list.forEach((f, idx) => {
        items.push({
          feed_id: f.id,
          folder: folder === UNSORTED ? "" : folder,
          sort_order: idx,
        });
      });
    }
    await api("/feeds/reorder", {
      method: "POST",
      body: JSON.stringify({ items }),
    });
    // Don't refetchAll here -- the optimistic order already matches what we
    // just sent. Refetch in the background to catch out-of-band changes.
    qc.invalidateQueries({ queryKey: ["feeds"], refetchType: "none" });
    qc.invalidateQueries({ queryKey: ["folders"], refetchType: "none" });
  }

  async function persistFolderOrder(folders: string[]) {
    const order = folders.filter((f) => f !== UNSORTED);
    await api("/feeds/folders/reorder", {
      method: "POST",
      body: JSON.stringify({ order }),
    });
    qc.invalidateQueries({ queryKey: ["folders"], refetchType: "none" });
  }

  function onDragStart(e: DragStartEvent) {
    setActiveId(String(e.active.id));
  }

  async function onDragEnd(e: DragEndEvent) {
    setActiveId(null);
    const { active, over } = e;
    if (!over || !order) return;
    const aid = String(active.id);
    const oid = String(over.id);
    if (aid === oid) return;

    // ---------- folder reorder ----------
    if (isFolderId(aid) && isFolderId(oid)) {
      const from = order.folders.indexOf(folderName(aid));
      const to = order.folders.indexOf(folderName(oid));
      if (from === -1 || to === -1 || from === to) return;
      const next = arrayMove(order.folders, from, to);
      setOrder({ ...order, folders: next });
      try {
        await persistFolderOrder(next);
      } catch (err) {
        console.error("folder reorder failed", err);
        refetchAll();
      }
      return;
    }

    // ---------- feed move / reorder ----------
    if (!isFeedId(aid)) return;

    const fid = feedNum(aid);
    const fromFolder = findFeedFolder(fid);
    if (!fromFolder) return;

    let toFolder: string;
    let toIdx: number;

    if (isFolderId(oid)) {
      // Dropped onto a folder header / empty folder body
      toFolder = folderName(oid);
      toIdx = order.byFolder[toFolder]?.length ?? 0;
    } else if (isFeedId(oid)) {
      // Dropped onto another feed
      const tgtId = feedNum(oid);
      const tgtFolder = findFeedFolder(tgtId);
      if (!tgtFolder) return;
      toFolder = tgtFolder;
      toIdx = order.byFolder[tgtFolder].findIndex((f) => f.id === tgtId);
      if (toIdx === -1) toIdx = order.byFolder[tgtFolder].length;
    } else {
      return;
    }

    const next: Record<string, FeedOut[]> = {};
    for (const [k, v] of Object.entries(order.byFolder)) next[k] = v.slice();

    const fromList = next[fromFolder];
    const fromIdx = fromList.findIndex((f) => f.id === fid);
    if (fromIdx === -1) return;
    const [moved] = fromList.splice(fromIdx, 1);
    moved.folder = toFolder === UNSORTED ? "" : toFolder;

    const dest = (next[toFolder] = next[toFolder] || []);
    // If moving within the same list, account for the removed index.
    const adjustedIdx =
      fromFolder === toFolder && fromIdx < toIdx ? toIdx - 1 : toIdx;
    dest.splice(Math.max(0, Math.min(dest.length, adjustedIdx)), 0, moved);

    setOrder({ ...order, byFolder: next });

    try {
      await persistFeedOrder(next);
    } catch (err) {
      console.error("feed reorder failed", err);
      refetchAll();
    }
  }

  const folderNames = useMemo(
    () => (order ? order.folders : foldersQ.data?.map((f) => f.name) ?? [UNSORTED]),
    [order, foldersQ.data],
  );

  return (
    <div className="mx-auto max-w-5xl px-5 py-6">
      <PageHeader
        title="Feeds"
        subtitle="Drag to reorder. Drop a feed onto a group to move it."
        actions={
          <div className="flex gap-2">
            <OpmlExportBtn />
            <OpmlImportBtn onDone={refetchAll} />
          </div>
        }
      />

      <div className="mb-5 inline-flex rounded-lg border border-ink-200 bg-white p-0.5">
        {(["my", "discover"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={
              "rounded-md px-3 py-1.5 text-sm font-medium " +
              (tab === t ? "bg-ink-100 text-ink-900" : "text-ink-500 hover:text-ink-900")
            }
          >
            {t === "my" ? "My subscriptions" : "Discover"}
          </button>
        ))}
      </div>

      {tab === "my" ? (
        <>
          <AddFeedRow folders={folderNames} onAdded={refetchAll} />
          <ManageFoldersBar folders={foldersQ.data || []} onChanged={refetchAll} />

          {selected.size > 0 && (
            <BulkBar
              count={selected.size}
              folders={folderNames}
              onClear={clearSel}
              onMove={async (folder) => {
                await Promise.all(
                  [...selected].map((id) =>
                    api(`/feeds/${id}`, {
                      method: "PATCH",
                      body: JSON.stringify({ folder: folder === UNSORTED ? "" : folder }),
                    }),
                  ),
                );
                clearSel();
                refetchAll();
              }}
              onCreateFolder={async (name) => {
                await api("/feeds/folders", {
                  method: "POST",
                  body: JSON.stringify({ name }),
                });
                await Promise.all(
                  [...selected].map((id) =>
                    api(`/feeds/${id}`, {
                      method: "PATCH",
                      body: JSON.stringify({ folder: name }),
                    }),
                  ),
                );
                clearSel();
                refetchAll();
              }}
              onUnsubscribe={async () => {
                if (!confirm(`Unsubscribe from ${selected.size} feed(s)?`)) return;
                await Promise.all(
                  [...selected].map((id) => api(`/feeds/${id}`, { method: "DELETE" })),
                );
                clearSel();
                refetchAll();
              }}
            />
          )}

          {feedsQ.isLoading || !order ? (
            <div className="card h-40 animate-pulse bg-ink-100/50" />
          ) : (feedsQ.data || []).length === 0 ? (
            <Empty
              icon={Rss}
              title="No subscriptions yet"
              hint="Add a feed above, paste OPML, or browse Discover for curated sources."
            />
          ) : (
            <DndContext
              sensors={sensors}
              collisionDetection={collisionDetection}
              onDragStart={onDragStart}
              onDragEnd={onDragEnd}
            >
              <SortableContext
                items={order.folders.map(folderId)}
                strategy={verticalListSortingStrategy}
              >
                <div className="space-y-5">
                  {order.folders.map((name) => (
                    <SortableFolderBlock
                      key={name}
                      folder={name}
                      feeds={order.byFolder[name] || []}
                      allFolders={folderNames}
                      selected={selected}
                      toggle={toggleSel}
                      refresh={refetchAll}
                    />
                  ))}
                </div>
              </SortableContext>

              <DragOverlay>
                {activeId && isFeedId(activeId) ? (
                  <FeedRowGhost
                    feed={
                      order.byFolder[findFeedFolder(feedNum(activeId)) || UNSORTED]?.find(
                        (f) => f.id === feedNum(activeId),
                      ) || null
                    }
                  />
                ) : activeId && isFolderId(activeId) ? (
                  <div className="card border-2 border-beam-500 bg-white px-4 py-2 text-sm font-bold uppercase tracking-wider text-ink-500 shadow-card">
                    {folderName(activeId)}
                  </div>
                ) : null}
              </DragOverlay>
            </DndContext>
          )}
        </>
      ) : (
        <DiscoverPanel catalog={catalogQ.data} loading={catalogQ.isLoading} onSeeded={refetchAll} />
      )}
    </div>
  );
}

// ===========================================================================
// Add feed
// ===========================================================================
function AddFeedRow({
  folders,
  onAdded,
}: {
  folders: string[];
  onAdded: () => void;
}) {
  const [url, setUrl] = useState("");
  const [folder, setFolder] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api("/feeds", {
        method: "POST",
        body: JSON.stringify({ url, folder }),
      });
      setUrl("");
      onAdded();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card mb-4 flex flex-wrap items-center gap-2 p-3">
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://example.com/feed.xml"
        className="input flex-1"
        type="url"
        required
      />
      <select
        value={folder}
        onChange={(e) => setFolder(e.target.value)}
        className="input !w-44"
      >
        <option value="">Unsorted</option>
        {folders
          .filter((f) => f !== UNSORTED)
          .map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
      </select>
      <button type="submit" disabled={busy} className="btn-primary">
        <Plus className="h-4 w-4" /> {busy ? "Adding…" : "Add feed"}
      </button>
      {err && <div className="w-full text-xs text-danger-600">{err}</div>}
    </form>
  );
}

// ===========================================================================
// Manage folders bar (create / rename / delete chips)
// ===========================================================================
function ManageFoldersBar({
  folders,
  onChanged,
}: {
  folders: FolderInfo[];
  onChanged: () => void;
}) {
  const [name, setName] = useState("");

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    await api("/feeds/folders", {
      method: "POST",
      body: JSON.stringify({ name: name.trim() }),
    });
    setName("");
    onChanged();
  }
  async function rename(old: string) {
    const newName = prompt(`Rename folder "${old}" to:`, old);
    if (!newName || newName === old) return;
    await api("/feeds/folders/rename", {
      method: "POST",
      body: JSON.stringify({ old_name: old, new_name: newName }),
    });
    onChanged();
  }
  async function del(name: string) {
    if (!confirm(`Delete folder "${name}"? Feeds inside will move to Unsorted.`)) return;
    await api(`/feeds/folders/${encodeURIComponent(name)}`, { method: "DELETE" });
    onChanged();
  }

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <form onSubmit={create} className="flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New group name"
          className="input !w-56"
        />
        <button type="submit" className="btn-secondary">
          <FolderPlus className="h-4 w-4" /> Create group
        </button>
      </form>
      <div className="flex flex-wrap items-center gap-1 text-xs text-ink-500">
        {folders
          .filter((f) => f.name !== UNSORTED)
          .map((f) => (
            <span key={f.name} className="chip group">
              {f.name}
              <button
                onClick={() => rename(f.name)}
                className="ml-1 text-ink-400 hover:text-beam-600"
                title="Rename"
              >
                <Pencil className="inline h-3 w-3" />
              </button>
              <button
                onClick={() => del(f.name)}
                className="ml-0.5 text-ink-400 hover:text-danger-600"
                title="Delete"
              >
                <X className="inline h-3 w-3" />
              </button>
            </span>
          ))}
      </div>
    </div>
  );
}

// ===========================================================================
// Bulk operations bar
// ===========================================================================
function BulkBar({
  count,
  folders,
  onClear,
  onMove,
  onCreateFolder,
  onUnsubscribe,
}: {
  count: number;
  folders: string[];
  onClear: () => void;
  onMove: (folder: string) => void;
  onCreateFolder: (name: string) => void;
  onUnsubscribe: () => void;
}) {
  const [moveTo, setMoveTo] = useState(UNSORTED);
  const [groupName, setGroupName] = useState("");

  return (
    <div className="card mb-4 flex flex-wrap items-center gap-2 p-3">
      <span className="text-sm font-medium">{count} selected</span>
      <select
        value={moveTo}
        onChange={(e) => setMoveTo(e.target.value)}
        className="input !w-44"
      >
        {folders.map((f) => (
          <option key={f} value={f}>
            {f}
          </option>
        ))}
      </select>
      <button onClick={() => onMove(moveTo)} className="btn-secondary">
        Move
      </button>
      <span className="text-ink-300">·</span>
      <input
        value={groupName}
        onChange={(e) => setGroupName(e.target.value)}
        placeholder="New group name"
        className="input !w-44"
      />
      <button
        onClick={() => {
          if (groupName.trim()) {
            onCreateFolder(groupName.trim());
            setGroupName("");
          }
        }}
        className="btn-secondary"
      >
        <FolderPlus className="h-4 w-4" /> Create & move
      </button>
      <button onClick={onUnsubscribe} className="btn-danger ml-auto">
        <Trash2 className="h-4 w-4" /> Unsubscribe
      </button>
      <button onClick={onClear} className="btn-ghost">
        Clear
      </button>
    </div>
  );
}

// ===========================================================================
// Sortable folder block (containing sortable feeds)
// ===========================================================================
function SortableFolderBlock({
  folder,
  feeds,
  allFolders,
  selected,
  toggle,
  refresh,
}: {
  folder: string;
  feeds: FeedOut[];
  allFolders: string[];
  selected: Set<number>;
  toggle: (id: number) => void;
  refresh: () => void;
}) {
  const id = folderId(folder);
  const {
    setNodeRef: setSortableRef,
    transform,
    transition,
    isDragging,
    attributes,
    listeners,
  } = useSortable({ id, data: { type: "folder", name: folder } });

  // Same node also acts as a drop target so feeds can be dropped onto an
  // empty folder body.
  const { setNodeRef: setDroppableRef, isOver } = useDroppable({ id });
  const setRef = (node: HTMLElement | null) => {
    setSortableRef(node);
    setDroppableRef(node);
  };

  const allSelected = feeds.length > 0 && feeds.every((f) => selected.has(f.id));
  const someSelected = feeds.some((f) => selected.has(f.id));

  function toggleAll() {
    feeds.forEach((f) => {
      const has = selected.has(f.id);
      if ((allSelected && has) || (!allSelected && !has)) toggle(f.id);
    });
  }

  return (
    <section
      ref={setRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : 1,
      }}
      className={
        "rounded-xl border-2 border-transparent transition-colors " +
        (isOver ? "border-beam-500 bg-beam-50/60" : "")
      }
    >
      <header className="mb-2 flex items-center gap-2 px-1">
        <button
          {...attributes}
          {...listeners}
          className="cursor-grab rounded p-1 text-ink-300 hover:bg-ink-100 hover:text-ink-700 active:cursor-grabbing"
          title="Drag to reorder group"
        >
          <GripVertical className="h-4 w-4" />
        </button>
        <input
          type="checkbox"
          checked={allSelected}
          ref={(el) => {
            if (el) el.indeterminate = !allSelected && someSelected;
          }}
          onChange={toggleAll}
          className="h-4 w-4 rounded border-ink-300 text-beam-600"
        />
        <h3 className="text-sm font-bold uppercase tracking-wider text-ink-500">
          {folder}
        </h3>
        <span className="text-xs text-ink-400">{feeds.length}</span>
      </header>

      <SortableContext
        items={feeds.map((f) => feedId(f.id))}
        strategy={verticalListSortingStrategy}
      >
        {feeds.length === 0 ? (
          <p className="rounded-lg border border-dashed border-ink-200 px-4 py-3 text-xs italic text-ink-400">
            Empty group — drop a feed here to add it.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {feeds.map((f) => (
              <SortableFeedRow
                key={f.id}
                feed={f}
                selected={selected.has(f.id)}
                toggle={() => toggle(f.id)}
                folders={allFolders}
                refresh={refresh}
              />
            ))}
          </ul>
        )}
      </SortableContext>
    </section>
  );
}

// ===========================================================================
// Sortable feed row
// ===========================================================================
function SortableFeedRow({
  feed,
  selected,
  toggle,
  folders,
  refresh,
}: {
  feed: FeedOut;
  selected: boolean;
  toggle: () => void;
  folders: string[];
  refresh: () => void;
}) {
  const {
    setNodeRef,
    transform,
    transition,
    isDragging,
    attributes,
    listeners,
  } = useSortable({ id: feedId(feed.id), data: { type: "feed", id: feed.id } });

  const [busy, setBusy] = useState(false);

  async function move(e: React.ChangeEvent<HTMLSelectElement>) {
    setBusy(true);
    try {
      await api(`/feeds/${feed.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          folder: e.target.value === UNSORTED ? "" : e.target.value,
        }),
      });
      refresh();
    } finally {
      setBusy(false);
    }
  }
  async function poll() {
    setBusy(true);
    try {
      await api(`/feeds/${feed.id}/poll`, { method: "POST" });
      refresh();
    } finally {
      setBusy(false);
    }
  }
  async function unsubscribe() {
    if (!confirm(`Unsubscribe from "${feed.title || feed.url}"?`)) return;
    await api(`/feeds/${feed.id}`, { method: "DELETE" });
    refresh();
  }

  return (
    <li
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : 1,
      }}
      className="card flex items-center gap-2 p-3"
    >
      <button
        {...attributes}
        {...listeners}
        className="cursor-grab rounded p-1 text-ink-300 hover:bg-ink-100 hover:text-ink-700 active:cursor-grabbing"
        title="Drag to reorder / move group"
      >
        <GripVertical className="h-4 w-4" />
      </button>
      <input
        type="checkbox"
        checked={selected}
        onChange={toggle}
        className="h-4 w-4 rounded border-ink-300 text-beam-600"
      />
      <StatusBadge status={feed.last_status} errorCount={feed.error_count} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-ink-900">
          {feed.custom_title || feed.title || hostFromUrl(feed.url)}
        </div>
        <div className="truncate text-[11px] text-ink-400">
          {feed.url} · last polled {timeAgo(feed.last_polled_at) || "never"}
        </div>
      </div>
      <select
        value={feed.folder || UNSORTED}
        onChange={move}
        disabled={busy}
        className="input !w-36 !py-1 !text-xs"
      >
        {folders.map((f) => (
          <option key={f} value={f}>
            {f}
          </option>
        ))}
      </select>
      <button onClick={poll} className="btn-ghost !py-1" title="Force re-poll">
        <RefreshCw className="h-4 w-4" />
      </button>
      <button onClick={unsubscribe} className="btn-ghost !py-1 text-danger-600">
        <Trash2 className="h-4 w-4" />
      </button>
    </li>
  );
}

function FeedRowGhost({ feed }: { feed: FeedOut | null }) {
  if (!feed) return null;
  return (
    <div className="card flex items-center gap-2 border-2 border-beam-500 bg-white p-3 shadow-card">
      <GripVertical className="h-4 w-4 text-ink-300" />
      <Rss className="h-4 w-4 text-ink-400" />
      <div className="truncate text-sm font-medium text-ink-900">
        {feed.custom_title || feed.title || hostFromUrl(feed.url)}
      </div>
    </div>
  );
}

function StatusBadge({
  status,
  errorCount,
}: {
  status: string | null;
  errorCount: number;
}) {
  if (status === "ok" || status === "200" || status?.startsWith("304")) {
    return (
      <span title={status || "Healthy"}>
        <CheckCircle2 className="h-4 w-4 text-good-500" />
      </span>
    );
  }
  if (errorCount > 0 || (status && status !== "ok")) {
    return (
      <span title={status || "errors"}>
        <AlertCircle className="h-4 w-4 text-danger-500" />
      </span>
    );
  }
  return <span className="h-4 w-4 rounded-full bg-ink-200" title="Not yet polled" />;
}

// ===========================================================================
// Discover panel (curated catalog)
// ===========================================================================
function DiscoverPanel({
  catalog,
  loading,
  onSeeded,
}: {
  catalog?: CatalogResp;
  loading: boolean;
  onSeeded: () => void;
}) {
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  function toggle(id: string) {
    setPicked((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }

  async function subscribe() {
    setBusy(true);
    try {
      await api("/feeds/seed", {
        method: "POST",
        body: JSON.stringify({ category_ids: [...picked] }),
      });
      setPicked(new Set());
      onSeeded();
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="card h-40 animate-pulse bg-ink-100/50" />;
  if (!catalog) return <Empty title="Catalog unavailable" />;

  return (
    <div>
      <p className="mb-4 text-sm text-ink-600">
        Curated feeds, hand-picked by category. Tick the categories you want and click
        Subscribe.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        {catalog.categories.map((c) => (
          <label
            key={c.id}
            className={
              "card cursor-pointer p-4 transition " +
              (picked.has(c.id) ? "ring-2 ring-beam-500" : "hover:shadow-card")
            }
          >
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 rounded border-ink-300 text-beam-600"
                checked={picked.has(c.id)}
                onChange={() => toggle(c.id)}
              />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-ink-900">{c.name}</span>
                  <span className="chip">{c.feeds.length}</span>
                  {c.enabled_by_default && <span className="chip-blue">recommended</span>}
                </div>
                <p className="mt-1 text-xs text-ink-500">{c.description}</p>
                <ul className="mt-2 max-h-24 overflow-y-auto text-xs text-ink-500">
                  {c.feeds.slice(0, 6).map((f) => (
                    <li key={f.url} className="truncate">
                      • {f.title || hostFromUrl(f.url)}
                    </li>
                  ))}
                  {c.feeds.length > 6 && (
                    <li className="italic">+{c.feeds.length - 6} more</li>
                  )}
                </ul>
              </div>
            </div>
          </label>
        ))}
      </div>
      <div className="sticky bottom-4 mt-6 flex justify-end">
        <button
          onClick={subscribe}
          disabled={busy || picked.size === 0}
          className="btn-primary !px-5 !py-2 shadow-card"
        >
          <Plus className="h-4 w-4" />
          {busy ? "Subscribing…" : `Subscribe to ${picked.size} categor${picked.size === 1 ? "y" : "ies"}`}
        </button>
      </div>
    </div>
  );
}

// ===========================================================================
// OPML
// ===========================================================================
function OpmlExportBtn() {
  async function go() {
    const blob = await apiBlob("/opml/export");
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "pharos-feeds.opml";
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <button onClick={go} className="btn-secondary">
      <Download className="h-4 w-4" /> Export OPML
    </button>
  );
}

function OpmlImportBtn({ onDone }: { onDone: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  async function pick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    await api("/opml/import", { method: "POST", body: fd });
    onDone();
  }
  return (
    <>
      <input
        ref={ref}
        type="file"
        accept=".opml,.xml,application/xml,text/xml"
        className="hidden"
        onChange={pick}
      />
      <button onClick={() => ref.current?.click()} className="btn-secondary">
        <Upload className="h-4 w-4" /> Import OPML
      </button>
    </>
  );
}
