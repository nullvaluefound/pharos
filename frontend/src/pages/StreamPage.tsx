import { useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Inbox, Layers, Loader2, Rows3 } from "lucide-react";

import { ArticleCard } from "../components/ArticleCard";
import { Empty } from "../components/Empty";
import { PageHeader } from "../components/PageHeader";
import { api } from "../lib/api";
import { useArticleNav } from "../lib/articleNav";
import type {
  ArticleSummary,
  ConstellationItem,
  FeedOut,
  StreamPage as StreamPageT,
  WatchOut,
} from "../lib/types";

const PAGE_SIZE = 30;

export function StreamPage() {
  const [params] = useSearchParams();
  const feedId = params.get("feed_id");
  const folder = params.get("folder");
  const watchId = params.get("watch");
  const onlyUnread = params.get("unread") === "1";
  const [view, setView] = useState<"grouped" | "flat">(
    () => (localStorage.getItem("pharos.view") as "grouped" | "flat") || "grouped",
  );

  function setViewPersist(v: "grouped" | "flat") {
    localStorage.setItem("pharos.view", v);
    setView(v);
  }

  const { data: feeds } = useQuery<FeedOut[]>({
    queryKey: ["feeds"],
    queryFn: () => api<FeedOut[]>("/feeds"),
    enabled: !!feedId,
  });

  const { data: watches } = useQuery<WatchOut[]>({
    queryKey: ["watches"],
    queryFn: () => api<WatchOut[]>("/watches"),
    enabled: !!watchId,
  });

  const watch = useMemo(
    () => (watchId && watches ? watches.find((w) => String(w.id) === watchId) : null),
    [watchId, watches],
  );

  const baseQs = useMemo(() => {
    const sp = new URLSearchParams();
    sp.set("view", view);
    sp.set("limit", String(PAGE_SIZE));
    if (feedId) sp.set("feed_id", feedId);
    if (folder) sp.set("folder", folder);
    if (watchId) sp.set("watch_id", watchId);
    if (onlyUnread) sp.set("only_unread", "1");
    return sp.toString();
  }, [view, feedId, folder, watchId, onlyUnread]);

  const stream = useInfiniteQuery<StreamPageT>({
    queryKey: ["stream", baseQs],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const sp = new URLSearchParams(baseQs);
      if (pageParam) sp.set("cursor", pageParam as string);
      return api<StreamPageT>(`/stream?${sp.toString()}`);
    },
    getNextPageParam: (last) => last.next_cursor || undefined,
  });

  const items: (ArticleSummary | ConstellationItem)[] = useMemo(() => {
    return (stream.data?.pages || []).flatMap((p) => p.items as any[]);
  }, [stream.data]);

  const title = (() => {
    if (watch) return watch.name;
    if (folder) return folder;
    if (feedId && feeds) {
      const f = feeds.find((x) => String(x.id) === feedId);
      return f?.custom_title || f?.title || "Feed";
    }
    return "All articles";
  })();

  const subtitle = (() => {
    if (watch) return "Watch results";
    if (folder) return "Folder";
    if (feedId) return "Single feed";
    return "Latest from all your feeds";
  })();

  // Keep the article-drawer's prev/next list in sync with what's on screen.
  const setNavList = useArticleNav((s) => s.setList);
  useEffect(() => {
    const ids: number[] = [];
    for (const it of items as any[]) {
      if (typeof it?.id === "number") ids.push(it.id);
      if (it?.representative?.id) ids.push(it.representative.id);
      for (const o of it?.other_sources || []) if (o?.id) ids.push(o.id);
    }
    setNavList(ids, ["stream", baseQs] as unknown[]);
  }, [items, baseQs, setNavList]);

  // Infinite-scroll sentinel: load next page when it enters viewport.
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (
          entries[0].isIntersecting &&
          stream.hasNextPage &&
          !stream.isFetchingNextPage
        ) {
          stream.fetchNextPage();
        }
      },
      { rootMargin: "200px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [stream.hasNextPage, stream.isFetchingNextPage, stream.fetchNextPage]);

  const isLoading = stream.isLoading && items.length === 0;

  return (
    <div className="mx-auto max-w-3xl px-5 py-6">
      <PageHeader
        title={title}
        subtitle={subtitle}
        actions={
          <div className="inline-flex rounded-lg border border-ink-200 bg-white p-0.5">
            <button
              onClick={() => setViewPersist("grouped")}
              className={
                "inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium " +
                (view === "grouped"
                  ? "bg-ink-100 text-ink-900"
                  : "text-ink-500 hover:text-ink-900")
              }
            >
              <Layers className="h-3.5 w-3.5" /> Constellations
            </button>
            <button
              onClick={() => setViewPersist("flat")}
              className={
                "inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium " +
                (view === "flat"
                  ? "bg-ink-100 text-ink-900"
                  : "text-ink-500 hover:text-ink-900")
              }
            >
              <Rows3 className="h-3.5 w-3.5" /> Flat
            </button>
          </div>
        }
      />

      {isLoading && (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card h-32 animate-pulse bg-ink-100/50" />
          ))}
        </div>
      )}

      {!isLoading && items.length === 0 && (
        <Empty
          icon={Inbox}
          title="No articles yet"
          hint={
            watch
              ? "Nothing matches this watch yet. New matches will arrive automatically."
              : "Subscribe to a few feeds, or come back in a few minutes — the lantern is enriching."
          }
        />
      )}

      <div className="space-y-3">
        {items.map((item: ArticleSummary | ConstellationItem | any, i: number) => (
          <ArticleCard
            key={(item.id ?? item.cluster_id ?? i).toString() + ":" + i}
            item={item}
          />
        ))}
      </div>

      {/* Infinite-scroll sentinel + footer state */}
      <div ref={sentinelRef} className="h-12" />
      {stream.isFetchingNextPage && (
        <div className="flex justify-center py-4 text-xs text-ink-500">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading more…
        </div>
      )}
      {!stream.hasNextPage && items.length > 0 && !stream.isFetchingNextPage && (
        <div className="py-6 text-center text-xs text-ink-400">
          You've reached the end of the hot archive. Older items are in{" "}
          <a href="/archive" className="text-beam-600 hover:underline">
            Archive Search
          </a>
          .
        </div>
      )}
    </div>
  );
}
