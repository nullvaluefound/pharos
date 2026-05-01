import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bookmark,
  BookmarkCheck,
  ChevronLeft,
  ChevronRight,
  Code2,
  Copy,
  ExternalLink,
  Layers,
  X,
} from "lucide-react";

import { api } from "../lib/api";
import { useArticleNav } from "../lib/articleNav";
import { useArticleParam } from "../lib/useArticleParam";
import type { ArticleDetail, RelatedResponse } from "../lib/types";
import { hostFromUrl, severityClass, timeAgo } from "../lib/format";

/**
 * Right-hand slide-in panel that renders the full article view without
 * leaving the underlying list page. Driven by the `?article=<id>` URL
 * search param so it's deep-linkable and the browser back button closes
 * it naturally.
 */
export function ArticleDrawer() {
  const { id, replace, close } = useArticleParam();
  const open = id != null;

  // Esc to close, ArrowLeft / ArrowRight to paginate.
  const { prevId, nextId } = useArticleNav();
  const prev = prevId(id);
  const next = nextId(id);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      // Don't hijack keys while the user is typing in an input.
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) {
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      } else if (e.key === "ArrowLeft" && prev != null) {
        e.preventDefault();
        replace(prev);
      } else if (e.key === "ArrowRight" && next != null) {
        e.preventDefault();
        replace(next);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close, replace, prev, next]);

  return (
    <>
      {/* backdrop */}
      <div
        aria-hidden
        className={
          "fixed inset-0 z-40 bg-ink-900/30 backdrop-blur-[1px] transition-opacity duration-200 " +
          (open ? "opacity-100" : "pointer-events-none opacity-0")
        }
        onClick={close}
      />

      {/* panel */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Article details"
        className={
          "fixed right-0 top-0 z-50 flex h-full flex-col bg-white shadow-2xl " +
          "border-l border-ink-200 " +
          "w-full sm:w-[80%] md:w-[65%] lg:w-[55%] xl:w-[50%] " +
          "transition-transform duration-300 will-change-transform " +
          (open ? "translate-x-0" : "translate-x-full")
        }
      >
        {open && id != null && (
          <ArticleDrawerContent
            articleId={id}
            prevId={prev}
            nextId={next}
            onPrev={() => prev != null && replace(prev)}
            onNext={() => next != null && replace(next)}
            onClose={close}
          />
        )}
      </aside>
    </>
  );
}

interface ContentProps {
  articleId: number;
  prevId: number | null;
  nextId: number | null;
  onPrev: () => void;
  onNext: () => void;
  onClose: () => void;
}

function ArticleDrawerContent({
  articleId,
  prevId,
  nextId,
  onPrev,
  onNext,
  onClose,
}: ContentProps) {
  const qc = useQueryClient();
  const navQueryKey = useArticleNav((s) => s.queryKey);
  const [showJson, setShowJson] = useState(false);

  const { data: article, isLoading, error } = useQuery<ArticleDetail>({
    queryKey: ["article", articleId],
    queryFn: () => api<ArticleDetail>(`/articles/${articleId}`),
  });

  const { data: related } = useQuery<RelatedResponse>({
    queryKey: ["related", articleId],
    queryFn: () => api<RelatedResponse>(`/articles/${articleId}/related`),
    enabled: !!article,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["article", articleId] });
    if (navQueryKey) qc.invalidateQueries({ queryKey: navQueryKey });
    qc.invalidateQueries({ queryKey: ["saved"] });
  };

  const toggleSave = useMutation({
    mutationFn: async () =>
      api(`/articles/${articleId}/state`, {
        method: "POST",
        body: JSON.stringify({ is_saved: !article?.is_saved }),
      }),
    onSuccess: invalidate,
  });

  const markRead = useMutation({
    mutationFn: async () =>
      api(`/articles/${articleId}/state`, {
        method: "POST",
        body: JSON.stringify({ is_read: true }),
      }),
    onSuccess: invalidate,
  });

  // Auto-mark-as-read once per article load, only if not already read.
  useEffect(() => {
    if (article && !article.is_read) markRead.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [article?.id]);

  // Reset transient UI when article changes
  useEffect(() => {
    setShowJson(false);
  }, [articleId]);

  const meta = useMemo(() => extractMeta(article?.enriched), [article?.enriched]);

  return (
    <>
      {/* header / toolbar — always shown */}
      <div className="flex items-center gap-1 border-b border-ink-200 bg-white/95 px-3 py-2 backdrop-blur">
        <button
          onClick={onClose}
          className="btn-ghost !py-1.5"
          title="Close (Esc)"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
        <div className="mx-1 h-5 w-px bg-ink-200" />
        <button
          onClick={onPrev}
          disabled={prevId == null}
          className="btn-ghost !py-1.5 disabled:opacity-40 disabled:hover:bg-transparent"
          title="Previous article (←)"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <button
          onClick={onNext}
          disabled={nextId == null}
          className="btn-ghost !py-1.5 disabled:opacity-40 disabled:hover:bg-transparent"
          title="Next article (→)"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
        <div className="ml-auto flex items-center gap-1">
          {article && (
            <>
              <a
                href={article.url}
                target="_blank"
                rel="noreferrer"
                className="btn-ghost !py-1.5"
                title="Open original in new tab"
              >
                <ExternalLink className="h-4 w-4" />
                <span className="hidden md:inline">Source</span>
              </a>
              <button
                onClick={() => toggleSave.mutate()}
                className={
                  article.is_saved ? "btn-secondary !py-1.5" : "btn-ghost !py-1.5"
                }
                title={article.is_saved ? "Unsave" : "Save"}
              >
                {article.is_saved ? (
                  <BookmarkCheck className="h-4 w-4 text-beam-600" />
                ) : (
                  <Bookmark className="h-4 w-4" />
                )}
                <span className="hidden md:inline">
                  {article.is_saved ? "Saved" : "Save"}
                </span>
              </button>
              <button
                onClick={() => setShowJson((v) => !v)}
                className="btn-ghost !py-1.5"
                title={showJson ? "Hide JSON" : "View JSON"}
              >
                <Code2 className="h-4 w-4" />
                <span className="hidden md:inline">{showJson ? "Hide JSON" : "JSON"}</span>
              </button>
              <button
                onClick={() =>
                  navigator.clipboard.writeText(JSON.stringify(meta, null, 2))
                }
                className="btn-ghost !py-1.5"
                title="Copy metadata JSON to clipboard"
              >
                <Copy className="h-4 w-4" />
              </button>
            </>
          )}
        </div>
      </div>

      {/* body */}
      <div className="flex-1 overflow-y-auto">
        {isLoading && (
          <div className="space-y-3 px-6 py-8">
            <div className="h-5 w-2/3 animate-pulse rounded bg-ink-100" />
            <div className="h-9 w-full animate-pulse rounded bg-ink-100" />
            <div className="h-9 w-5/6 animate-pulse rounded bg-ink-100" />
            <div className="mt-6 h-32 w-full animate-pulse rounded bg-ink-100" />
          </div>
        )}

        {!isLoading && (error || !article) && (
          <div className="px-6 py-10 text-center">
            <div className="text-base font-medium text-ink-700">
              Couldn't load this article.
            </div>
            <div className="mt-1 text-sm text-ink-500">
              {error instanceof Error ? error.message : "Article not found."}
            </div>
            <button onClick={onClose} className="btn-secondary mt-4">
              Close
            </button>
          </div>
        )}

        {article && (
          <article className="mx-auto max-w-2xl px-6 py-7">
            <header className="mb-3 flex flex-wrap items-center gap-2 text-xs text-ink-500">
              <span className="font-medium text-ink-700">
                {article.feed_title || hostFromUrl(article.url)}
              </span>
              <span className="text-ink-300">·</span>
              <span>{timeAgo(article.published_at)}</span>
              {article.severity_hint && (
                <span className={severityClass(article.severity_hint) + " uppercase"}>
                  {article.severity_hint}
                </span>
              )}
              {article.author && (
                <>
                  <span className="text-ink-300">·</span>
                  <span>by {article.author}</span>
                </>
              )}
            </header>

            <h1 className="text-2xl font-bold leading-tight tracking-tight text-ink-900">
              {article.title || article.url}
            </h1>

            {article.overview && (
              <div className="mt-5">
                <h2 className="text-xs font-bold uppercase tracking-wider text-ink-400">
                  Pharos overview
                </h2>
                <p className="mt-2 whitespace-pre-line text-base leading-relaxed text-ink-800">
                  {article.overview}
                </p>
              </div>
            )}

            {Array.isArray(article.enriched?.key_points) &&
              article.enriched!.key_points.length > 0 && (
                <div className="mt-6">
                  <h2 className="text-xs font-bold uppercase tracking-wider text-ink-400">
                    Key points
                  </h2>
                  <ul className="mt-2 list-disc pl-6 text-sm leading-relaxed text-ink-700">
                    {article.enriched!.key_points.map((p: string, i: number) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ul>
                </div>
              )}

            <EntitySection enriched={article.enriched} />

            {showJson && (
              <pre className="mt-6 max-h-[24rem] overflow-auto rounded-lg bg-ink-900 p-4 text-[11px] leading-relaxed text-ink-100">
                {JSON.stringify(meta, null, 2)}
              </pre>
            )}

            {related && related.members.length > 0 && (
              <section className="mt-8">
                <h2 className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-ink-400">
                  <Layers className="h-3.5 w-3.5" /> Other sources covering this story
                </h2>
                <div className="space-y-2">
                  {related.members.map((m) => (
                    <button
                      key={m.id}
                      onClick={() => {
                        // Open the related article inside the drawer too.
                        const sp = new URLSearchParams(window.location.search);
                        sp.set("article", String(m.id));
                        window.history.replaceState(
                          null,
                          "",
                          window.location.pathname + "?" + sp.toString(),
                        );
                        // Kick react-router by triggering a popstate.
                        window.dispatchEvent(new PopStateEvent("popstate"));
                      }}
                      className="card block w-full p-4 text-left transition-shadow hover:shadow-card"
                    >
                      <div className="text-xs text-ink-500">
                        <span className="font-medium text-ink-700">
                          {m.feed_title || hostFromUrl(m.url)}
                        </span>
                        <span className="text-ink-300"> · </span>
                        {timeAgo(m.published_at)}
                        <span className="text-ink-300"> · </span>
                        {(m.similarity * 100).toFixed(0)}% match
                      </div>
                      <div className="mt-1 font-medium text-ink-900">{m.title}</div>
                      {m.shared_tokens && m.shared_tokens.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {m.shared_tokens.slice(0, 6).map((t) => (
                            <span key={t} className="chip text-[10px]">
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              </section>
            )}
          </article>
        )}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Entities + JSON helpers
// ---------------------------------------------------------------------------
//
// The backend (see backend/pharos/lantern/schema.py) emits this shape:
//
//   enriched.entities.threat_actors  : [{name, confidence, role, mitre_group_id}]
//   enriched.entities.malware        : [{name, confidence, role, mitre_software_id}]
//   enriched.entities.tools          : [{name, confidence, role}]
//   enriched.entities.vendors        : [{name, confidence, role}]
//   enriched.entities.companies      : [{name, confidence, role}]
//   enriched.entities.products       : [{name, confidence, role, version}]
//   enriched.entities.cves           : ["CVE-2024-XXXXX", ...]
//   enriched.entities.mitre_groups   : ["G0016", ...]
//   enriched.entities.ttps_mitre     : ["T1566.001", ...]
//   enriched.entities.mitre_software : ["S0154", ...]
//   enriched.entities.mitre_tactics  : ["TA0001", ...]
//   enriched.entities.iocs           : { ipv4:[], ipv6:[], domains:[], ... }
//   enriched.entities.sectors        : [string, ...]
//   enriched.entities.countries      : [string, ...]
//
// We must NOT trust a specific shape blindly — older articles in cold storage
// may have been enriched against a slightly different schema. So every value
// is normalized through `toChip()` which accepts both string and object forms.

interface Chip {
  text: string;
  /** raw mitre id (G####, S####, T####, TA####) extracted from this chip,
   *  for linking out to attack.mitre.org. */
  mitreId?: string;
}

function asChip(v: unknown): Chip | null {
  if (v == null) return null;
  if (typeof v === "string") {
    const text = v.trim();
    return text ? { text, mitreId: extractMitreId(text) } : null;
  }
  if (typeof v === "number" || typeof v === "boolean") {
    return { text: String(v) };
  }
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    const name = typeof o.name === "string" ? o.name.trim() : "";
    const mitreGroup =
      typeof o.mitre_group_id === "string" ? o.mitre_group_id : "";
    const mitreSw =
      typeof o.mitre_software_id === "string" ? o.mitre_software_id : "";
    const version = typeof o.version === "string" ? o.version : "";
    const mitreId = mitreGroup || mitreSw || "";

    if (name) {
      let text = name;
      if (mitreId) text = `${name} (${mitreId})`;
      else if (version) text = `${name} ${version}`;
      return { text, mitreId: mitreId || extractMitreId(name) };
    }
    // unknown shape -> last resort: stringify it small so we never crash
    return { text: JSON.stringify(o).slice(0, 60) };
  }
  return null;
}

function extractMitreId(s: string): string | undefined {
  const m = s.match(/\b(G\d{4}|S\d{4}|T\d{4}(?:\.\d{3})?|TA\d{4})\b/);
  return m ? m[1] : undefined;
}

function toChips(values: unknown): Chip[] {
  if (!Array.isArray(values)) return [];
  const out: Chip[] = [];
  for (const v of values) {
    const c = asChip(v);
    if (c) out.push(c);
  }
  return out;
}

function findMitreLink(
  label: string,
  chip: Chip,
  links: Record<string, Record<string, string>> | null | undefined,
): string | null {
  if (!links || !chip.mitreId) return null;
  const id = chip.mitreId;
  if (label.includes("Group") || label.includes("Threat")) {
    return links.groups?.[id] || null;
  }
  if (label.includes("Software") || label.includes("Malware")) {
    return links.software?.[id] || null;
  }
  if (label.includes("Technique") || label.includes("TTP")) {
    return links.techniques?.[id] || null;
  }
  if (label.includes("Tactic")) {
    return links.tactics?.[id] || null;
  }
  // generic fallback by id prefix
  if (id.startsWith("G")) return links.groups?.[id] || null;
  if (id.startsWith("S")) return links.software?.[id] || null;
  if (id.startsWith("TA")) return links.tactics?.[id] || null;
  if (id.startsWith("T")) return links.techniques?.[id] || null;
  return null;
}

function EntitySection({ enriched }: { enriched: any }) {
  if (!enriched || typeof enriched !== "object") return null;
  const e = enriched.entities || {};
  const iocs = (e.iocs || {}) as Record<string, unknown>;

  const sections: { label: string; chips: Chip[]; tone: string }[] = [
    { label: "Threat actors", chips: toChips(e.threat_actors), tone: "chip-red" },
    { label: "Malware", chips: toChips(e.malware), tone: "chip-amber" },
    { label: "Tools", chips: toChips(e.tools), tone: "chip" },
    { label: "Vendors", chips: toChips(e.vendors), tone: "chip-blue" },
    { label: "Products", chips: toChips(e.products), tone: "chip-blue" },
    { label: "Companies", chips: toChips(e.companies), tone: "chip-violet" },
    { label: "CVEs", chips: toChips(e.cves), tone: "chip-red" },
    { label: "MITRE Groups", chips: toChips(e.mitre_groups), tone: "chip-blue" },
    { label: "MITRE Software", chips: toChips(e.mitre_software), tone: "chip-blue" },
    { label: "MITRE Techniques", chips: toChips(e.ttps_mitre), tone: "chip-blue" },
    { label: "MITRE Tactics", chips: toChips(e.mitre_tactics), tone: "chip-blue" },
    { label: "Sectors", chips: toChips(e.sectors), tone: "chip-green" },
    { label: "Countries", chips: toChips(e.countries), tone: "chip" },
    { label: "Domains", chips: toChips(iocs.domains), tone: "chip" },
    { label: "IPv4", chips: toChips(iocs.ipv4), tone: "chip" },
    { label: "IPv6", chips: toChips(iocs.ipv6), tone: "chip" },
    { label: "URLs", chips: toChips(iocs.urls), tone: "chip" },
    { label: "SHA256", chips: toChips(iocs.sha256), tone: "chip" },
    { label: "SHA1", chips: toChips(iocs.sha1), tone: "chip" },
    { label: "MD5", chips: toChips(iocs.md5), tone: "chip" },
  ].filter((s) => s.chips.length > 0);

  if (sections.length === 0) return null;
  const links = (e.mitre_links || null) as Record<
    string,
    Record<string, string>
  > | null;

  return (
    <div className="mt-6 space-y-3">
      <h2 className="text-xs font-bold uppercase tracking-wider text-ink-400">
        Entities
      </h2>
      {sections.map((s) => (
        <div key={s.label} className="flex flex-wrap items-baseline gap-2">
          <span className="w-32 flex-shrink-0 text-xs font-semibold text-ink-500">
            {s.label}
          </span>
          <div className="flex flex-wrap gap-1.5">
            {s.chips.map((chip, i) => {
              const url = findMitreLink(s.label, chip, links);
              const cls = `${s.tone}${url ? " hover:underline" : ""}`;
              return url ? (
                <a
                  key={`${s.label}-${i}-${chip.text}`}
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className={cls}
                >
                  {chip.text}
                </a>
              ) : (
                <span
                  key={`${s.label}-${i}-${chip.text}`}
                  className={s.tone}
                >
                  {chip.text}
                </span>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function extractMeta(enriched: any | null | undefined) {
  if (!enriched || typeof enriched !== "object") return {};
  const e = enriched.entities || {};
  return {
    overview: enriched.overview || null,
    severity_hint: enriched.severity_hint || null,
    content_type: enriched.content_type || null,
    language: enriched.language || null,
    topics: Array.isArray(enriched.topics) ? enriched.topics : [],
    key_points: Array.isArray(enriched.key_points) ? enriched.key_points : [],
    threat_actors: e.threat_actors || [],
    malware: e.malware || [],
    tools: e.tools || [],
    vendors: e.vendors || [],
    products: e.products || [],
    companies: e.companies || [],
    cves: e.cves || [],
    mitre_groups: e.mitre_groups || [],
    mitre_software: e.mitre_software || [],
    mitre_techniques: e.ttps_mitre || [],
    mitre_tactics: e.mitre_tactics || [],
    sectors: e.sectors || [],
    countries: e.countries || [],
    iocs: e.iocs || {},
  };
}
