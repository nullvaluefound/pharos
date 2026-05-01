import { Bookmark, BookmarkCheck, ExternalLink, Layers } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { ArticleSummary, ConstellationItem } from "../lib/types";
import { hostFromUrl, severityClass, timeAgo } from "../lib/format";
import { api } from "../lib/api";
import { useArticleParam } from "../lib/useArticleParam";

interface Props {
  item: ArticleSummary | ConstellationItem;
}

export function ArticleCard({ item }: Props) {
  const isCluster = "representative" in item;
  const a = (isCluster ? item.representative : item) as ArticleSummary;
  const others = isCluster ? item.other_sources : [];
  const qc = useQueryClient();
  const { id: openId, open } = useArticleParam();
  const isActive = openId === a.id;

  const toggleSave = useMutation({
    mutationFn: async () =>
      api(`/articles/${a.id}/state`, {
        method: "POST",
        body: JSON.stringify({ is_saved: !a.is_saved }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["stream"] });
      qc.invalidateQueries({ queryKey: ["saved"] });
      qc.invalidateQueries({ queryKey: ["article", a.id] });
    },
  });

  return (
    <article
      className={
        "card group p-5 transition-shadow hover:shadow-card animate-fade-in " +
        (isActive ? "ring-2 ring-beam-500 shadow-card" : "")
      }
    >
      <header className="mb-2 flex items-center gap-2 text-xs text-ink-500">
        <span className="font-medium text-ink-700">
          {a.feed_title || hostFromUrl(a.url)}
        </span>
        <span className="text-ink-300">·</span>
        <span>{timeAgo(a.published_at)}</span>
        {a.severity_hint && (
          <>
            <span className="text-ink-300">·</span>
            <span className={severityClass(a.severity_hint) + " uppercase"}>
              {a.severity_hint}
            </span>
          </>
        )}
        {isCluster && (item as ConstellationItem).member_count > 1 && (
          <span className="chip-blue ml-auto">
            <Layers className="h-3 w-3" />
            {(item as ConstellationItem).member_count} sources
            {typeof (item as ConstellationItem).avg_similarity === "number" &&
              ` · ${Math.round(((item as ConstellationItem).avg_similarity || 0) * 100)}% match`}
          </span>
        )}
      </header>

      <button
        type="button"
        onClick={() => open(a.id)}
        className="block w-full text-left text-lg font-semibold leading-snug text-ink-900 hover:text-beam-700 focus:outline-none focus-visible:text-beam-700"
      >
        {a.title || a.url}
      </button>

      {a.overview && (
        <button
          type="button"
          onClick={() => open(a.id)}
          className="mt-2 line-clamp-3 cursor-pointer text-left text-sm leading-relaxed text-ink-600 hover:text-ink-800"
        >
          {a.overview}
        </button>
      )}

      {isCluster &&
        ((item as ConstellationItem).shared_keywords?.length || 0) > 0 && (
          <div className="mt-3 flex flex-wrap gap-1">
            {(item as ConstellationItem).shared_keywords!
              .slice(0, 6)
              .map((kw) => (
                <span
                  key={kw}
                  className="rounded-md bg-beam-50 px-1.5 py-0.5 text-[10px] font-medium text-beam-700"
                  title="Shared across the articles in this constellation"
                >
                  {kw}
                </span>
              ))}
          </div>
        )}

      {isCluster && others.length > 0 && (
        <ul className="mt-3 space-y-1 border-l-2 border-ink-100 pl-3 text-xs">
          {others.slice(0, 3).map((o) => (
            <li key={o.id} className="flex items-center gap-2 text-ink-500">
              <span className="font-medium text-ink-700">
                {o.feed_title || hostFromUrl(o.url)}
              </span>
              <span className="text-ink-300">·</span>
              <span>{timeAgo(o.published_at)}</span>
            </li>
          ))}
          {others.length > 3 && (
            <li className="text-[11px] italic text-ink-400">
              +{(item as ConstellationItem).member_count - others.length - 1} more
            </li>
          )}
        </ul>
      )}

      <footer className="mt-3 flex items-center gap-2">
        <button
          onClick={() => toggleSave.mutate()}
          className={a.is_saved ? "btn-secondary !py-1" : "btn-ghost !py-1"}
          title={a.is_saved ? "Unsave" : "Save"}
        >
          {a.is_saved ? (
            <BookmarkCheck className="h-4 w-4 text-beam-600" />
          ) : (
            <Bookmark className="h-4 w-4" />
          )}
        </button>
        <a
          href={a.url}
          target="_blank"
          rel="noreferrer"
          className="btn-ghost !py-1"
          title="Open original"
          onClick={(e) => e.stopPropagation()}
        >
          <ExternalLink className="h-4 w-4" />
          <span className="hidden sm:inline">Source</span>
        </a>
        <button
          type="button"
          onClick={() => open(a.id)}
          className="btn-ghost !py-1 ml-auto text-beam-600"
        >
          Read more →
        </button>
      </footer>
    </article>
  );
}
