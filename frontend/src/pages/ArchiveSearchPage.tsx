import { useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Archive, Loader2, Search } from "lucide-react";

import { PageHeader } from "../components/PageHeader";
import { Empty } from "../components/Empty";
import { ArticleCard } from "../components/ArticleCard";
import { api } from "../lib/api";
import { useArticleNav } from "../lib/articleNav";
import {
  ENTITY_TYPES,
  HAS_METADATA_OPTIONS,
  type SearchResponse,
} from "../lib/types";

const PAGE_SIZE = 30;

export function ArchiveSearchPage() {
  const [text, setText] = useState("");
  const [type, setType] = useState<string>("threat_actor");
  const [name, setName] = useState("");
  const [since, setSince] = useState<number | "">("");
  const [hasTypes, setHasTypes] = useState<string[]>([]);
  const [terms, setTerms] = useState<{ type: string; name: string }[]>([]);
  const [submittedAt, setSubmittedAt] = useState(0);

  function addTerm() {
    if (!name.trim()) return;
    setTerms((t) => [...t, { type, name: name.trim() }]);
    setName("");
  }
  function removeTerm(i: number) {
    setTerms((t) => t.filter((_, idx) => idx !== i));
  }
  function toggleHas(v: string) {
    setHasTypes((s) => (s.includes(v) ? s.filter((x) => x !== v) : [...s, v]));
  }

  function buildQuery(cursor: string | null) {
    const any_of: Record<string, string[]> = {};
    for (const t of terms) {
      any_of[t.type] = [...(any_of[t.type] || []), t.name];
    }
    return {
      any_of,
      has_entity_types: hasTypes,
      text: text.trim() || null,
      since_days: since === "" ? null : Number(since),
      tier: "cold" as const,
      limit: PAGE_SIZE,
      cursor,
    };
  }

  const queryKey = useMemo(
    () => ["archive-search", submittedAt, terms, text, since, hasTypes] as const,
    [submittedAt, terms, text, since, hasTypes],
  );

  const q = useInfiniteQuery<SearchResponse>({
    queryKey: [...queryKey],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<SearchResponse>("/search", {
        method: "POST",
        body: JSON.stringify(buildQuery(pageParam as string | null)),
      }),
    getNextPageParam: (last) => last.next_cursor || undefined,
    enabled: submittedAt > 0,
  });

  const hits = useMemo(
    () => (q.data?.pages || []).flatMap((p) => p.hits),
    [q.data],
  );

  const setNavList = useArticleNav((s) => s.setList);
  useEffect(() => {
    const ids = hits.map((h: any) => h?.id).filter((n: any) => typeof n === "number");
    setNavList(ids, ["archive-search", submittedAt]);
  }, [hits, submittedAt, setNavList]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmittedAt(Date.now());
  }

  // Infinite scroll sentinel
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (
          entries[0].isIntersecting &&
          q.hasNextPage &&
          !q.isFetchingNextPage
        ) {
          q.fetchNextPage();
        }
      },
      { rootMargin: "200px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [q.hasNextPage, q.isFetchingNextPage, q.fetchNextPage]);

  return (
    <div className="mx-auto max-w-4xl px-5 py-6">
      <PageHeader
        title="Archive Search"
        subtitle="Search the cold tier (older than ~3 months). Slower than the hot stream, but covers the full history."
      />

      <div className="card mb-4 flex items-start gap-3 border-warm-100 bg-warm-50 p-3 text-xs text-warm-600">
        <Archive className="h-4 w-4 flex-shrink-0" />
        <div>
          <strong>You're searching the archive.</strong> These results come
          from <code>cold.db</code>, which can grow large -- queries may
          take a few seconds. For recent articles, use the regular{" "}
          <a href="/search" className="font-semibold underline">
            Search
          </a>{" "}
          page or the stream.
        </div>
      </div>

      <form onSubmit={submit} className="card mb-5 space-y-4 p-5">
        <div>
          <label className="mb-1 block text-xs font-semibold text-ink-700">
            Free text
          </label>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. supply chain"
            className="input"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-semibold text-ink-700">
            Filter by entity (any of these match)
          </label>
          <div className="flex gap-2">
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="input !w-44"
            >
              {ENTITY_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addTerm();
                }
              }}
              placeholder="e.g. apt29 / cve-2024-12345"
              className="input"
            />
            <button type="button" onClick={addTerm} className="btn-secondary">
              Add
            </button>
          </div>
          {terms.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {terms.map((t, i) => (
                <span key={i} className="chip-blue">
                  {ENTITY_TYPES.find((x) => x.value === t.type)?.label}: {t.name}
                  <button
                    type="button"
                    onClick={() => removeTerm(i)}
                    className="-mr-1 ml-1 text-beam-700 hover:text-beam-900"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
        <div>
          <label className="mb-1 block text-xs font-semibold text-ink-700">
            Must have metadata
          </label>
          <div className="flex flex-wrap gap-2">
            {HAS_METADATA_OPTIONS.map((o) => (
              <label
                key={o.value}
                className={
                  "cursor-pointer select-none rounded-full border px-2.5 py-1 text-xs " +
                  (hasTypes.includes(o.value)
                    ? "border-beam-500 bg-beam-50 text-beam-700"
                    : "border-ink-200 text-ink-600 hover:border-ink-400")
                }
              >
                <input
                  type="checkbox"
                  className="hidden"
                  checked={hasTypes.includes(o.value)}
                  onChange={() => toggleHas(o.value)}
                />
                {o.label}
              </label>
            ))}
          </div>
        </div>
        <div className="flex items-end gap-3">
          <div>
            <label className="mb-1 block text-xs font-semibold text-ink-700">
              Within (days)
            </label>
            <input
              type="number"
              min={1}
              max={3650}
              value={since}
              onChange={(e) =>
                setSince(e.target.value === "" ? "" : Number(e.target.value))
              }
              className="input !w-32"
              placeholder="any"
            />
          </div>
          <button type="submit" className="btn-primary">
            <Search className="h-4 w-4" /> Search archive
          </button>
        </div>
      </form>

      {submittedAt === 0 ? (
        <Empty
          icon={Archive}
          title="Search the archive"
          hint="The archive holds enriched articles older than ~3 months. Use the same filters as the regular search."
        />
      ) : q.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card h-28 animate-pulse bg-ink-100/50" />
          ))}
        </div>
      ) : hits.length === 0 ? (
        <Empty
          title="No archive matches"
          hint="Try broadening your filters or removing one."
        />
      ) : (
        <>
          <div className="mb-3 text-sm text-ink-500">
            {hits.length}
            {q.hasNextPage ? "+" : ""} archive results
          </div>
          <div className="space-y-3">
            {hits.map((h) => (
              <ArticleCard
                key={h.id}
                item={{
                  ...h,
                  author: null,
                  is_read: false,
                  is_saved: false,
                }}
              />
            ))}
          </div>

          <div ref={sentinelRef} className="h-12" />
          {q.isFetchingNextPage && (
            <div className="flex justify-center py-4 text-xs text-ink-500">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading more from the archive…
            </div>
          )}
          {!q.hasNextPage && hits.length > 0 && !q.isFetchingNextPage && (
            <div className="py-6 text-center text-xs text-ink-400">
              End of archive results.
            </div>
          )}
        </>
      )}
    </div>
  );
}
