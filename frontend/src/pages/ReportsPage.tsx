import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Eye,
  FileText,
  Loader2,
  Plus,
  Send,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { PageHeader } from "../components/PageHeader";
import { Empty } from "../components/Empty";
import { api } from "../lib/api";
import {
  ENTITY_TYPES,
  HAS_METADATA_OPTIONS,
  type ReportDetail,
  type ReportListItem,
  type ReportPreview,
  type ReportRequest,
} from "../lib/types";
import { timeAgo } from "../lib/format";

interface FormState {
  name: string;
  keywords: string;        // raw comma/newline separated
  since_days: number;
  rows: { type: string; name: string }[];
  has_types: string[];
  structure_kind: "BLUF" | "custom";
  sections: string;        // raw newline separated
  audience: "executive" | "technical" | "both";
  length: "short" | "medium" | "long";
  scope_note: string;
}

const DEFAULT_FORM: FormState = {
  name: "Weekly Threat Briefing",
  keywords: "",
  since_days: 7,
  rows: [],
  has_types: [],
  structure_kind: "BLUF",
  sections: "",
  audience: "both",
  length: "short",
  scope_note: "",
};

function toRequest(f: FormState): ReportRequest {
  const keywords = f.keywords
    .split(/[\n,]+/g)
    .map((s) => s.trim())
    .filter(Boolean);
  const any_of: Record<string, string[]> = {};
  for (const r of f.rows) {
    if (!r.name.trim()) continue;
    (any_of[r.type] = any_of[r.type] || []).push(r.name.trim());
  }
  const sections = f.sections
    .split(/\n+/g)
    .map((s) => s.trim())
    .filter(Boolean);
  return {
    name: f.name,
    keywords,
    since_days: f.since_days,
    any_of,
    all_of: {},
    has_entity_types: f.has_types,
    structure_kind: f.structure_kind,
    sections,
    audience: f.audience,
    length: f.length,
    scope_note: f.scope_note,
  };
}

export function ReportsPage() {
  const qc = useQueryClient();
  const [view, setView] = useState<"list" | "create" | "view">("list");
  const [openId, setOpenId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const listQ = useQuery<ReportListItem[]>({
    queryKey: ["reports"],
    queryFn: () => api<ReportListItem[]>("/reports"),
  });

  const detailQ = useQuery<ReportDetail>({
    queryKey: ["reports", openId],
    queryFn: () => api<ReportDetail>(`/reports/${openId}`),
    enabled: openId !== null && view === "view",
  });

  // ---- mutations ----
  const previewM = useMutation({
    mutationFn: (req: ReportRequest) =>
      api<ReportPreview>("/reports/preview", {
        method: "POST",
        body: JSON.stringify(req),
      }),
    onSuccess: (p) => {
      setPreview(p);
      setError(null);
    },
    onError: (e: any) => setError(e.message),
  });

  const generateM = useMutation({
    mutationFn: (req: ReportRequest) =>
      api<ReportDetail>("/reports/generate", {
        method: "POST",
        body: JSON.stringify(req),
      }),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      setOpenId(d.id);
      setView("view");
      setError(null);
    },
    onError: (e: any) => setError(e.message),
  });

  const deleteM = useMutation({
    mutationFn: (id: number) =>
      api(`/reports/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      if (view === "view") setView("list");
    },
  });

  // Re-preview when form filter changes (debounced)
  useEffect(() => {
    if (view !== "create") return;
    const t = setTimeout(() => previewM.mutate(toRequest(form)), 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    view,
    form.keywords,
    form.since_days,
    form.rows,
    form.has_types,
    form.length,
  ]);

  function startNew() {
    setForm(DEFAULT_FORM);
    setPreview(null);
    setError(null);
    setView("create");
  }

  function openReport(id: number) {
    setOpenId(id);
    setView("view");
  }

  return (
    <div className="mx-auto max-w-6xl px-5 py-6">
      {view === "list" && (
        <>
          <PageHeader
            title="Reports"
            subtitle="Generate threat-intel briefings from filtered articles."
            actions={
              <button onClick={startNew} className="btn-primary">
                <Plus className="h-4 w-4" /> New report
              </button>
            }
          />
          <ReportList
            list={listQ.data || []}
            loading={listQ.isLoading}
            onOpen={openReport}
            onDelete={(id) => {
              if (confirm("Delete this report?")) deleteM.mutate(id);
            }}
          />
        </>
      )}

      {view === "create" && (
        <CreateView
          form={form}
          setForm={setForm}
          preview={preview}
          previewing={previewM.isPending}
          generating={generateM.isPending}
          error={error}
          onCancel={() => setView("list")}
          onGenerate={() => {
            setError(null);
            generateM.mutate(toRequest(form));
          }}
        />
      )}

      {view === "view" && (
        <ReportView
          detail={detailQ.data}
          loading={detailQ.isLoading}
          onBack={() => setView("list")}
          onDelete={() => {
            if (openId && confirm("Delete this report?")) {
              deleteM.mutate(openId);
            }
          }}
        />
      )}
    </div>
  );
}

// =============================================================================
// History list
// =============================================================================
function ReportList({
  list,
  loading,
  onOpen,
  onDelete,
}: {
  list: ReportListItem[];
  loading: boolean;
  onOpen: (id: number) => void;
  onDelete: (id: number) => void;
}) {
  if (loading) return <div className="card h-40 animate-pulse bg-ink-100/50" />;
  if (list.length === 0) {
    return (
      <Empty
        icon={FileText}
        title="No reports yet"
        hint="Click 'New report' to generate your first threat-intel briefing."
      />
    );
  }
  return (
    <ul className="space-y-2">
      {list.map((r) => (
        <li
          key={r.id}
          className="card group flex items-center gap-3 p-3 transition hover:shadow-card"
        >
          <FileText className="h-5 w-5 flex-shrink-0 text-beam-500" />
          <button
            onClick={() => onOpen(r.id)}
            className="min-w-0 flex-1 cursor-pointer text-left"
          >
            <div className="truncate text-sm font-medium text-ink-900">
              {r.name}
            </div>
            <div className="mt-0.5 truncate text-[11px] text-ink-400">
              {r.article_count} articles ·{" "}
              <Audience value={r.audience} /> ·{" "}
              <Length value={r.length_target} /> ·{" "}
              {r.structure_kind} ·{" "}
              {r.cost_usd != null && `$${r.cost_usd.toFixed(3)}`}
              {r.cost_usd != null && " · "}
              {timeAgo(r.created_at) || "just now"}
            </div>
          </button>
          <StatusPill status={r.status} />
          <button
            onClick={() => onOpen(r.id)}
            className="btn-ghost !py-1"
            title="Open"
          >
            <Eye className="h-4 w-4" />
          </button>
          <button
            onClick={() => onDelete(r.id)}
            className="btn-ghost !py-1 text-danger-600 opacity-0 group-hover:opacity-100"
            title="Delete"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </li>
      ))}
    </ul>
  );
}

function StatusPill({ status }: { status: string }) {
  const cls =
    status === "ready"
      ? "chip-green"
      : status === "failed"
        ? "chip-red"
        : status === "generating"
          ? "chip-amber"
          : "chip";
  return <span className={cls}>{status}</span>;
}

function Audience({ value }: { value: string }) {
  return (
    <span className="font-medium text-ink-500">
      {value === "both" ? "Exec + Tech" : value}
    </span>
  );
}

function Length({ value }: { value: string }) {
  const label =
    value === "short"
      ? "1-2 pp"
      : value === "medium"
        ? "2-3 pp"
        : value === "long"
          ? "3-4 pp"
          : value;
  return <span>{label}</span>;
}

// =============================================================================
// Create view (form + sticky preview / generate panel)
// =============================================================================
function CreateView({
  form,
  setForm,
  preview,
  previewing,
  generating,
  error,
  onCancel,
  onGenerate,
}: {
  form: FormState;
  setForm: (f: FormState) => void;
  preview: ReportPreview | null;
  previewing: boolean;
  generating: boolean;
  error: string | null;
  onCancel: () => void;
  onGenerate: () => void;
}) {
  const update = (patch: Partial<FormState>) => setForm({ ...form, ...patch });

  return (
    <>
      <PageHeader
        title="New report"
        subtitle="Filter articles, choose a structure, and generate a finished briefing."
        actions={
          <button onClick={onCancel} className="btn-ghost">
            <ChevronLeft className="h-4 w-4" /> Back to history
          </button>
        }
      />

      <div className="grid gap-5 lg:grid-cols-[2fr_1fr]">
        {/* ---------- form ---------- */}
        <div className="space-y-5">
          <FormCard title="Title">
            <input
              value={form.name}
              onChange={(e) => update({ name: e.target.value })}
              className="input w-full"
              placeholder="Weekly Threat Briefing"
            />
          </FormCard>

          <FormCard
            title="Filter: keywords (OR)"
            subtitle="Comma- or newline-separated. Each keyword is matched against title + overview + extracted entities."
          >
            <textarea
              value={form.keywords}
              onChange={(e) => update({ keywords: e.target.value })}
              className="input min-h-[64px] w-full"
              placeholder="ransomware, Volt Typhoon, CVE-2024-3400"
            />
          </FormCard>

          <FormCard title="Filter: timeframe">
            <div className="flex items-center gap-2 text-sm">
              <span>Last</span>
              <input
                type="number"
                min={1}
                max={365}
                value={form.since_days}
                onChange={(e) =>
                  update({ since_days: Math.max(1, +e.target.value || 7) })
                }
                className="input !w-20"
              />
              <span>days</span>
              <div className="ml-auto flex gap-1">
                {[1, 7, 14, 30, 90].map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => update({ since_days: d })}
                    className={
                      "rounded-md px-2 py-1 text-xs " +
                      (form.since_days === d
                        ? "bg-beam-100 text-beam-700"
                        : "text-ink-500 hover:bg-ink-100")
                    }
                  >
                    {d}d
                  </button>
                ))}
              </div>
            </div>
          </FormCard>

          <MetadataFilters form={form} update={update} />

          <FormCard
            title="Structure"
            subtitle="Pick a default BLUF outline or define your own section headings."
          >
            <div className="mb-3 flex gap-3">
              <RadioPill
                checked={form.structure_kind === "BLUF"}
                onChange={() => update({ structure_kind: "BLUF" })}
                label="BLUF (default)"
              />
              <RadioPill
                checked={form.structure_kind === "custom"}
                onChange={() => update({ structure_kind: "custom" })}
                label="Custom sections"
              />
            </div>
            {form.structure_kind === "custom" ? (
              <textarea
                value={form.sections}
                onChange={(e) => update({ sections: e.target.value })}
                className="input min-h-[110px] w-full font-mono text-xs"
                placeholder={`One section heading per line, e.g.:
Executive Summary
Adversary Activity
Vulnerabilities
Sectoral Impact
Recommendations`}
              />
            ) : (
              <div className="rounded-lg border border-ink-200 bg-ink-50 p-3 text-xs text-ink-600">
                <div className="mb-1 font-semibold">Default BLUF outline:</div>
                <ol className="list-decimal pl-4">
                  <li>Bottom Line Up Front</li>
                  <li>Key Judgments</li>
                  <li>Background</li>
                  <li>Detailed Findings</li>
                  <li>Recommendations</li>
                  <li>Sources</li>
                </ol>
              </div>
            )}
          </FormCard>

          <FormCard title="Audience">
            <div className="flex flex-wrap gap-2">
              {(
                [
                  { id: "executive", label: "Executive", desc: "Plain English, business impact" },
                  { id: "technical", label: "Technical", desc: "MITRE IDs, CVEs, IOCs, detections" },
                  { id: "both", label: "Both", desc: "Exec summary + technical detail" },
                ] as const
              ).map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => update({ audience: opt.id })}
                  className={
                    "flex-1 rounded-lg border-2 px-3 py-2 text-left transition " +
                    (form.audience === opt.id
                      ? "border-beam-500 bg-beam-50"
                      : "border-ink-200 hover:border-ink-300")
                  }
                >
                  <div className="text-sm font-semibold">{opt.label}</div>
                  <div className="text-[11px] text-ink-500">{opt.desc}</div>
                </button>
              ))}
            </div>
          </FormCard>

          <FormCard title="Length">
            <div className="flex flex-wrap gap-2">
              {(
                [
                  { id: "short", label: "Short", desc: "~1-2 pages" },
                  { id: "medium", label: "Medium", desc: "~2-3 pages" },
                  { id: "long", label: "Long", desc: "~3-4 pages" },
                ] as const
              ).map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => update({ length: opt.id })}
                  className={
                    "flex-1 rounded-lg border-2 px-3 py-2 text-left transition " +
                    (form.length === opt.id
                      ? "border-beam-500 bg-beam-50"
                      : "border-ink-200 hover:border-ink-300")
                  }
                >
                  <div className="text-sm font-semibold">{opt.label}</div>
                  <div className="text-[11px] text-ink-500">{opt.desc}</div>
                </button>
              ))}
            </div>
          </FormCard>

          <FormCard
            title="Scope note (optional)"
            subtitle="A line or two of context for the analyst — what to emphasize, who the report is for, etc."
          >
            <textarea
              value={form.scope_note}
              onChange={(e) => update({ scope_note: e.target.value })}
              className="input min-h-[64px] w-full"
              placeholder="Briefing for the CISO ahead of the Tuesday risk committee. Emphasize anything affecting our finance / SaaS exposure."
            />
          </FormCard>
        </div>

        {/* ---------- sticky preview / generate ---------- */}
        <div>
          <div className="card sticky top-4 space-y-4 p-4">
            <div>
              <div className="text-xs font-bold uppercase tracking-wider text-ink-400">
                Scope preview
              </div>
              {previewing && !preview ? (
                <div className="mt-2 flex items-center gap-2 text-xs text-ink-500">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Counting articles…
                </div>
              ) : preview ? (
                <div className="mt-2">
                  <div className="text-2xl font-bold text-ink-900">
                    {preview.article_count}
                  </div>
                  <div className="text-xs text-ink-500">
                    matching enriched articles
                  </div>
                  {preview.article_count > 200 && (
                    <div className="mt-1 text-[11px] text-amber-600">
                      Will analyze most-recent 200 (cap).
                    </div>
                  )}
                  {preview.article_count === 0 && (
                    <div className="mt-1 text-[11px] text-danger-600">
                      No matches — widen the timeframe or relax filters.
                    </div>
                  )}
                  <div className="mt-3 text-[11px] text-ink-500">
                    Estimated cost: <strong>${preview.estimated_cost_usd.toFixed(3)}</strong>
                  </div>
                </div>
              ) : (
                <div className="mt-2 text-xs italic text-ink-400">
                  Adjust filters above to refresh.
                </div>
              )}
            </div>

            {preview && preview.sample.length > 0 && (
              <div>
                <div className="text-xs font-bold uppercase tracking-wider text-ink-400">
                  Sample
                </div>
                <ul className="mt-1.5 space-y-1 text-[11px] text-ink-600">
                  {preview.sample.map((s) => (
                    <li key={s.id} className="truncate">
                      • {s.title || s.url}
                    </li>
                  ))}
                  {preview.article_count > preview.sample.length && (
                    <li className="italic text-ink-400">
                      +{preview.article_count - preview.sample.length} more
                    </li>
                  )}
                </ul>
              </div>
            )}

            <div className="border-t border-ink-100 pt-4">
              <button
                onClick={onGenerate}
                disabled={
                  generating ||
                  !form.name.trim() ||
                  !preview ||
                  preview.article_count === 0
                }
                className="btn-primary w-full !py-2"
              >
                {generating ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Generating… (~30-60s)
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4" />
                    Generate report
                  </>
                )}
              </button>
              {generating && (
                <div className="mt-2 text-[11px] italic text-ink-500">
                  OpenAI is building your report. Hang tight — don't close
                  this tab.
                </div>
              )}
              {error && (
                <div className="mt-2 rounded-md bg-danger-50 px-2 py-1 text-[11px] text-danger-700">
                  {error}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function FormCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card p-4">
      <div className="mb-2">
        <div className="text-sm font-semibold text-ink-900">{title}</div>
        {subtitle && (
          <div className="mt-0.5 text-[11px] text-ink-500">{subtitle}</div>
        )}
      </div>
      {children}
    </div>
  );
}

function RadioPill({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onChange}
      className={
        "rounded-md px-3 py-1.5 text-xs font-medium " +
        (checked
          ? "bg-beam-100 text-beam-700 ring-2 ring-beam-500"
          : "bg-ink-50 text-ink-600 hover:bg-ink-100")
      }
    >
      {label}
    </button>
  );
}

function MetadataFilters({
  form,
  update,
}: {
  form: FormState;
  update: (patch: Partial<FormState>) => void;
}) {
  const [type, setType] = useState("threat_actor");
  const [val, setVal] = useState("");

  function addRow() {
    if (!val.trim()) return;
    update({ rows: [...form.rows, { type, name: val.trim() }] });
    setVal("");
  }
  function removeRow(idx: number) {
    update({ rows: form.rows.filter((_, i) => i !== idx) });
  }
  function toggleHas(t: string) {
    update({
      has_types: form.has_types.includes(t)
        ? form.has_types.filter((x) => x !== t)
        : [...form.has_types, t],
    });
  }

  return (
    <FormCard
      title="Filter: metadata"
      subtitle="OR-match articles that contain any of these entities, AND require certain metadata categories to be present."
    >
      <div className="mb-3">
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-500">
          Match any of
        </div>
        <div className="flex flex-wrap gap-1.5">
          {form.rows.map((r, i) => (
            <span key={i} className="chip-blue">
              {ENTITY_TYPES.find((e) => e.value === r.type)?.label || r.type}:{" "}
              <strong>{r.name}</strong>
              <button
                onClick={() => removeRow(i)}
                className="ml-1 text-beam-700 hover:text-danger-600"
              >
                <X className="inline h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
        <div className="mt-2 flex gap-2">
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="input !w-44 !py-1 !text-xs"
          >
            {ENTITY_TYPES.map((e) => (
              <option key={e.value} value={e.value}>
                {e.label}
              </option>
            ))}
          </select>
          <input
            value={val}
            onChange={(e) => setVal(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addRow())}
            placeholder="apt29 / cve-2024-1234 / finance / ..."
            className="input flex-1 !py-1 !text-xs"
          />
          <button onClick={addRow} className="btn-secondary !py-1 !text-xs">
            <Plus className="h-3 w-3" /> Add
          </button>
        </div>
      </div>
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-500">
          Must contain at least one
        </div>
        <div className="flex flex-wrap gap-1.5">
          {HAS_METADATA_OPTIONS.map((opt) => {
            const on = form.has_types.includes(opt.value);
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => toggleHas(opt.value)}
                className={
                  "rounded-md border px-2 py-1 text-[11px] " +
                  (on
                    ? "border-beam-500 bg-beam-50 text-beam-700"
                    : "border-ink-200 text-ink-500 hover:bg-ink-50")
                }
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>
    </FormCard>
  );
}

// =============================================================================
// Report viewer
// =============================================================================
function ReportView({
  detail,
  loading,
  onBack,
  onDelete,
}: {
  detail?: ReportDetail;
  loading: boolean;
  onBack: () => void;
  onDelete: () => void;
}) {
  if (loading || !detail) {
    return (
      <div className="card mt-6 h-96 animate-pulse bg-ink-100/50" />
    );
  }
  const meta = `${detail.article_count} articles · ${detail.audience} · ${detail.length_target} · ${detail.structure_kind}${detail.cost_usd != null ? ` · $${detail.cost_usd.toFixed(3)}` : ""}`;
  return (
    <>
      <PageHeader
        title={detail.name}
        subtitle={meta}
        actions={
          <div className="flex gap-2">
            <button onClick={onBack} className="btn-ghost">
              <ChevronLeft className="h-4 w-4" /> History
            </button>
            <CopyBtn text={detail.body_md} />
            <DownloadBtn name={detail.name} text={detail.body_md} />
            <button onClick={onDelete} className="btn-ghost text-danger-600">
              <Trash2 className="h-4 w-4" /> Delete
            </button>
          </div>
        }
      />

      {detail.status === "failed" ? (
        <div className="card border-danger-200 bg-danger-50 p-5">
          <div className="text-sm font-semibold text-danger-900">
            Generation failed
          </div>
          <div className="mt-1 text-xs text-danger-700">{detail.error}</div>
        </div>
      ) : (
        <article className="card prose prose-sm max-w-none p-8 prose-headings:font-bold prose-h2:mt-8 prose-h2:border-b prose-h2:border-ink-200 prose-h2:pb-2 prose-h2:text-lg prose-h3:text-base prose-a:text-beam-600 prose-strong:text-ink-900">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {detail.body_md}
          </ReactMarkdown>
        </article>
      )}

      {detail.article_ids.length > 0 && detail.status === "ready" && (
        <details className="card mt-4 p-4">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-ink-500">
            Source articles ({detail.article_ids.length})
          </summary>
          <ul className="mt-3 grid gap-1 text-xs sm:grid-cols-2">
            {detail.article_ids.map((id) => (
              <li key={id}>
                <a
                  href={`/stream?article=${id}`}
                  className="text-beam-600 hover:underline"
                >
                  Article #{id} <ChevronRight className="inline h-3 w-3" />
                </a>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

function CopyBtn({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          /* noop */
        }
      }}
      className="btn-secondary"
    >
      <Copy className="h-4 w-4" /> {done ? "Copied!" : "Copy"}
    </button>
  );
}

function DownloadBtn({ name, text }: { name: string; text: string }) {
  function go() {
    const blob = new Blob([text], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name.replace(/[^\w\s-]/g, "").trim().replace(/\s+/g, "_") || "report"}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <button onClick={go} className="btn-secondary">
      <Download className="h-4 w-4" /> .md
    </button>
  );
}
