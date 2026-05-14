import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarClock,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Eye,
  FileText,
  Loader2,
  Mail,
  Pause,
  Pencil,
  Play,
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
  type ReportSchedule,
  type ReportScheduleIn,
  type ScheduleCadence,
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

interface EmailStatus {
  email: string | null;
  smtp_configured: boolean;
}

export function ReportsPage() {
  const qc = useQueryClient();
  const [view, setView] = useState<
    "list" | "create" | "view" | "schedules"
  >("list");
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

  // Used to gate the "Email this report" / schedule-email controls.
  const emailQ = useQuery<EmailStatus>({
    queryKey: ["settings", "email"],
    queryFn: () => api<EmailStatus>("/settings/email"),
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
              <div className="flex gap-2">
                <button
                  onClick={() => setView("schedules")}
                  className="btn-ghost"
                  title="Recurring report schedules"
                >
                  <CalendarClock className="h-4 w-4" /> Schedules
                </button>
                <button onClick={startNew} className="btn-primary">
                  <Plus className="h-4 w-4" /> New report
                </button>
              </div>
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

      {view === "schedules" && (
        <SchedulesView
          onBack={() => setView("list")}
          onOpenReport={(id) => {
            setOpenId(id);
            setView("view");
          }}
          emailStatus={emailQ.data}
        />
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
          emailStatus={emailQ.data}
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
                    {preview.article_count.toLocaleString()}
                  </div>
                  <div className="text-xs text-ink-500">
                    matching enriched articles
                  </div>
                  {preview.capped && (
                    <div className="mt-1 text-[11px] text-amber-600">
                      Will analyze most-recent {preview.cap.toLocaleString()} (cap).
                    </div>
                  )}
                  {preview.article_count === 0 && (
                    <div className="mt-1 text-[11px] text-danger-600">
                      No matches — widen the timeframe or relax filters.
                    </div>
                  )}
                  <div className="mt-3 text-[11px] text-ink-500">
                    Estimated cost: <strong>${preview.estimated_cost_usd.toFixed(3)}</strong>
                    {preview.capped && (
                      <span className="text-ink-400">
                        {" "}(for {preview.used_count.toLocaleString()} articles)
                      </span>
                    )}
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
                      +{(preview.article_count - preview.sample.length).toLocaleString()} more
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
  emailStatus,
  onBack,
  onDelete,
}: {
  detail?: ReportDetail;
  loading: boolean;
  emailStatus?: EmailStatus;
  onBack: () => void;
  onDelete: () => void;
}) {
  const [emailing, setEmailing] = useState(false);

  if (loading || !detail) {
    return (
      <div className="card mt-6 h-96 animate-pulse bg-ink-100/50" />
    );
  }
  const meta = `${detail.article_count} articles · ${detail.audience} · ${detail.length_target} · ${detail.structure_kind}${detail.cost_usd != null ? ` · $${detail.cost_usd.toFixed(3)}` : ""}`;
  const canEmail =
    detail.status === "ready" && !!emailStatus?.smtp_configured;
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
            <button
              onClick={() => setEmailing(true)}
              disabled={!canEmail}
              className="btn-secondary"
              title={
                !emailStatus?.smtp_configured
                  ? "SMTP is not configured on this Pharos server"
                  : detail.status !== "ready"
                    ? "Report must be ready to email"
                    : "Send this report by email"
              }
            >
              <Mail className="h-4 w-4" /> Email
            </button>
            <button onClick={onDelete} className="btn-ghost text-danger-600">
              <Trash2 className="h-4 w-4" /> Delete
            </button>
          </div>
        }
      />

      {emailing && (
        <EmailReportModal
          reportId={detail.id}
          reportName={detail.name}
          defaultTo={emailStatus?.email || ""}
          onClose={() => setEmailing(false)}
        />
      )}

      {detail.status === "failed" ? (
        <div className="card border-danger-200 bg-danger-50 p-5">
          <div className="text-sm font-semibold text-danger-900">
            Generation failed
          </div>
          <div className="mt-1 text-xs text-danger-700">{detail.error}</div>
        </div>
      ) : (
        <article
          className={[
            "card max-w-none p-8",
            // Base typography
            "prose prose-sm dark:prose-invert",
            // Headings
            "prose-headings:font-bold",
            "prose-h2:mt-8 prose-h2:border-b prose-h2:pb-2 prose-h2:text-lg",
            "prose-h2:border-ink-200 dark:prose-h2:border-pharos-navy-500",
            "prose-h3:text-base",
            // Body / inline elements -- explicit white-on-dark for the body
            // copy because the default prose-invert grays are still too dim
            // against our near-black canvas.
            "prose-p:text-ink-800 dark:prose-p:text-white",
            "prose-li:text-ink-800 dark:prose-li:text-white",
            "prose-strong:text-ink-900 dark:prose-strong:text-white",
            "prose-em:text-ink-800 dark:prose-em:text-white",
            "prose-blockquote:text-ink-700 dark:prose-blockquote:text-ink-200",
            "prose-code:text-ink-900 dark:prose-code:text-pharos-gold-300",
            // Links use the brand beam color in both modes
            "prose-a:text-beam-600 dark:prose-a:text-pharos-gold-400",
          ].join(" ")}
        >
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

// =============================================================================
// Ad-hoc email modal
// =============================================================================
function EmailReportModal({
  reportId,
  reportName,
  defaultTo,
  onClose,
}: {
  reportId: number;
  reportName: string;
  defaultTo: string;
  onClose: () => void;
}) {
  const [to, setTo] = useState(defaultTo);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const send = useMutation({
    mutationFn: () =>
      api<{ ok: boolean; sent_to: string }>(`/reports/${reportId}/email`, {
        method: "POST",
        body: JSON.stringify({ to: to.trim() || null }),
      }),
    onSuccess: (r) =>
      setMsg({ ok: true, text: `Sent to ${r.sent_to}.` }),
    onError: (e: any) =>
      setMsg({ ok: false, text: e?.message || "Send failed" }),
  });

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card w-full max-w-md p-5"
      >
        <div className="mb-3 flex items-start justify-between">
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-ink-400">
              Email report
            </div>
            <div className="mt-0.5 text-sm font-semibold text-ink-900">
              {reportName}
            </div>
          </div>
          <button onClick={onClose} className="btn-ghost !py-1">
            <X className="h-4 w-4" />
          </button>
        </div>

        <label className="mb-1 block text-xs font-semibold text-ink-700">
          Send to
        </label>
        <input
          type="email"
          value={to}
          onChange={(e) => setTo(e.target.value)}
          placeholder="you@example.com"
          className="input w-full"
        />
        <p className="mt-1 text-[11px] text-ink-500">
          Defaults to your saved notification email. Override here to send a
          one-off copy without changing your saved address.
        </p>

        {msg && (
          <div
            className={
              "mt-3 rounded-lg border px-3 py-2 text-sm " +
              (msg.ok
                ? "border-good-100 bg-good-50 text-good-600"
                : "border-danger-100 bg-danger-50 text-danger-600")
            }
          >
            {msg.text}
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="btn-ghost">
            Close
          </button>
          <button
            onClick={() => {
              setMsg(null);
              send.mutate();
            }}
            disabled={send.isPending || !to.trim()}
            className="btn-primary"
          >
            <Send className="h-4 w-4" />
            {send.isPending ? "Sending…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Schedules view (recurring reports)
// =============================================================================
function SchedulesView({
  onBack,
  onOpenReport,
  emailStatus,
}: {
  onBack: () => void;
  onOpenReport: (id: number) => void;
  emailStatus?: EmailStatus;
}) {
  const qc = useQueryClient();
  const listQ = useQuery<ReportSchedule[]>({
    queryKey: ["report-schedules"],
    queryFn: () => api<ReportSchedule[]>("/report-schedules"),
  });
  const [editing, setEditing] = useState<ReportSchedule | null>(null);
  const [creating, setCreating] = useState(false);

  const setActive = useMutation({
    mutationFn: (s: ReportSchedule) =>
      api<ReportSchedule>(`/report-schedules/${s.id}`, {
        method: "PUT",
        body: JSON.stringify(scheduleToIn({ ...s, active: !s.active })),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["report-schedules"] }),
  });
  const del = useMutation({
    mutationFn: (id: number) =>
      api(`/report-schedules/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["report-schedules"] }),
  });
  const runNow = useMutation({
    mutationFn: (id: number) =>
      api(`/report-schedules/${id}/run-now`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["report-schedules"] }),
  });

  return (
    <>
      <PageHeader
        title="Recurring reports"
        subtitle="Pharos will generate these on a cadence and (optionally) email them to you."
        actions={
          <div className="flex gap-2">
            <button onClick={onBack} className="btn-ghost">
              <ChevronLeft className="h-4 w-4" /> Back to history
            </button>
            <button
              onClick={() => setCreating(true)}
              className="btn-primary"
            >
              <Plus className="h-4 w-4" /> New schedule
            </button>
          </div>
        }
      />

      {emailStatus && !emailStatus.smtp_configured && (
        <div className="card mb-4 border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-900/20 dark:text-amber-200">
          SMTP isn't configured on this server, so scheduled reports will be
          generated and saved but won't be emailed. Ask your administrator to
          set <code>SMTP_HOST</code> in <code>.env</code>.
        </div>
      )}

      {listQ.isLoading ? (
        <div className="card h-40 animate-pulse bg-ink-100/50" />
      ) : (listQ.data || []).length === 0 ? (
        <Empty
          icon={CalendarClock}
          title="No schedules yet"
          hint="Click 'New schedule' to set up a recurring report."
        />
      ) : (
        <ul className="space-y-2">
          {(listQ.data || []).map((s) => (
            <li
              key={s.id}
              className="card flex flex-wrap items-center gap-3 p-3"
            >
              <CalendarClock
                className={
                  "h-5 w-5 flex-shrink-0 " +
                  (s.active ? "text-beam-500" : "text-ink-300")
                }
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold text-ink-900">
                  {s.name}
                </div>
                <div className="text-[11px] text-ink-500">
                  {describeCadence(s)} ·{" "}
                  {s.email_to
                    ? `email → ${s.email_to}`
                    : emailStatus?.email
                      ? `email → ${emailStatus.email}`
                      : "email off"}
                  {s.next_run_at && s.active && (
                    <> · next: {formatUtcLocal(s.next_run_at)}</>
                  )}
                </div>
                {s.last_error && (
                  <div className="mt-0.5 truncate text-[11px] text-danger-600">
                    Last error: {s.last_error}
                  </div>
                )}
                {s.last_report_id && !s.last_error && (
                  <button
                    onClick={() => onOpenReport(s.last_report_id!)}
                    className="mt-0.5 text-[11px] text-beam-600 hover:underline"
                  >
                    Open last report &rarr;
                  </button>
                )}
              </div>
              <span className={"chip " + (s.active ? "chip-green" : "")}>
                {s.active ? "active" : "paused"}
              </span>
              <button
                onClick={() => runNow.mutate(s.id)}
                disabled={runNow.isPending || !s.active}
                className="btn-ghost !py-1"
                title={
                  s.active
                    ? "Run on the next worker tick (~1 min)"
                    : "Activate the schedule first"
                }
              >
                <Play className="h-4 w-4" /> Run now
              </button>
              <button
                onClick={() => setActive.mutate(s)}
                className="btn-ghost !py-1"
                title={s.active ? "Pause" : "Resume"}
              >
                {s.active ? (
                  <Pause className="h-4 w-4" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
              </button>
              <button
                onClick={() => setEditing(s)}
                className="btn-ghost !py-1"
                title="Edit"
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button
                onClick={() => {
                  if (confirm(`Delete schedule "${s.name}"?`)) del.mutate(s.id);
                }}
                className="btn-ghost !py-1 text-danger-600"
                title="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {(creating || editing) && (
        <ScheduleEditor
          existing={editing || undefined}
          emailStatus={emailStatus}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ["report-schedules"] });
            setCreating(false);
            setEditing(null);
          }}
        />
      )}
    </>
  );
}

function scheduleToIn(s: ReportSchedule): ReportScheduleIn {
  return {
    name: s.name,
    request: s.request,
    cadence: s.cadence,
    hour_utc: s.hour_utc,
    day_of_week: s.day_of_week,
    day_of_month: s.day_of_month,
    email_to: s.email_to,
    active: s.active,
  };
}

function describeCadence(s: ReportSchedule): string {
  const time = `${String(s.hour_utc).padStart(2, "0")}:00 UTC`;
  if (s.cadence === "daily") return `Every day at ${time}`;
  if (s.cadence === "weekly") {
    const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    return `Every ${days[s.day_of_week ?? 0]} at ${time}`;
  }
  return `Day ${s.day_of_month ?? 1} of each month at ${time}`;
}

function formatUtcLocal(iso: string): string {
  // Backend stores naive UTC; append Z so the JS Date parses correctly.
  const t = iso.endsWith("Z") || /[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z";
  const d = new Date(t.replace(" ", "T"));
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Schedule editor modal -- minimal form: pick cadence + a saved request
// ---------------------------------------------------------------------------
function ScheduleEditor({
  existing,
  emailStatus,
  onClose,
  onSaved,
}: {
  existing?: ReportSchedule;
  emailStatus?: EmailStatus;
  onClose: () => void;
  onSaved: () => void;
}) {
  // We reuse the same FormState shape the create-view uses for the
  // ReportRequest so the user fills in one familiar form.
  const [name, setName] = useState(existing?.name || "Weekly Threat Briefing");
  const [reqForm, setReqForm] = useState<FormState>(() =>
    existing ? requestToFormState(existing.request, existing.name) : DEFAULT_FORM,
  );
  const [cadence, setCadence] = useState<ScheduleCadence>(
    existing?.cadence || "weekly",
  );
  const [hour, setHour] = useState<number>(existing?.hour_utc ?? 13);
  const [dow, setDow] = useState<number>(existing?.day_of_week ?? 0);
  const [dom, setDom] = useState<number>(existing?.day_of_month ?? 1);
  const [emailOverride, setEmailOverride] = useState<string>(
    existing?.email_to || "",
  );
  const [active, setActive] = useState<boolean>(existing?.active ?? true);
  const [err, setErr] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => {
      const payload: ReportScheduleIn = {
        name,
        request: toRequest(reqForm),
        cadence,
        hour_utc: hour,
        day_of_week: cadence === "weekly" ? dow : null,
        day_of_month: cadence === "monthly" ? dom : null,
        email_to: emailOverride.trim() || null,
        active,
      };
      const path = existing
        ? `/report-schedules/${existing.id}`
        : "/report-schedules";
      return api<ReportSchedule>(path, {
        method: existing ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
    },
    onSuccess: onSaved,
    onError: (e: any) => setErr(e?.message || "Save failed"),
  });

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 pt-12"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card w-full max-w-3xl p-5"
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-ink-400">
              {existing ? "Edit schedule" : "New schedule"}
            </div>
            <div className="mt-0.5 text-sm text-ink-500">
              Pharos will generate the report on this cadence and (if email is
              configured) send it to your inbox.
            </div>
          </div>
          <button onClick={onClose} className="btn-ghost !py-1">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-semibold text-ink-700">
              Schedule name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input w-full"
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs font-semibold text-ink-700">
                Cadence
              </label>
              <select
                value={cadence}
                onChange={(e) => setCadence(e.target.value as ScheduleCadence)}
                className="input w-full"
              >
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-ink-700">
                Hour (UTC)
              </label>
              <input
                type="number"
                min={0}
                max={23}
                value={hour}
                onChange={(e) =>
                  setHour(Math.max(0, Math.min(23, +e.target.value || 0)))
                }
                className="input w-full"
              />
            </div>
            {cadence === "weekly" && (
              <div>
                <label className="mb-1 block text-xs font-semibold text-ink-700">
                  Day of week
                </label>
                <select
                  value={dow}
                  onChange={(e) => setDow(+e.target.value)}
                  className="input w-full"
                >
                  <option value={0}>Monday</option>
                  <option value={1}>Tuesday</option>
                  <option value={2}>Wednesday</option>
                  <option value={3}>Thursday</option>
                  <option value={4}>Friday</option>
                  <option value={5}>Saturday</option>
                  <option value={6}>Sunday</option>
                </select>
              </div>
            )}
            {cadence === "monthly" && (
              <div>
                <label className="mb-1 block text-xs font-semibold text-ink-700">
                  Day of month
                </label>
                <input
                  type="number"
                  min={1}
                  max={28}
                  value={dom}
                  onChange={(e) =>
                    setDom(Math.max(1, Math.min(28, +e.target.value || 1)))
                  }
                  className="input w-full"
                />
                <div className="mt-1 text-[10px] text-ink-400">
                  Capped at 28 so every month is valid.
                </div>
              </div>
            )}
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold text-ink-700">
              Email override <span className="text-ink-400 font-normal">(optional)</span>
            </label>
            <input
              type="email"
              value={emailOverride}
              onChange={(e) => setEmailOverride(e.target.value)}
              placeholder="you@example.com"
              className="input w-full"
            />
            <p className="mt-1 text-[11px] text-ink-500">
              Leave blank to send to your saved notification email. Useful if a
              specific schedule should land in a shared inbox.
            </p>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={active}
              onChange={(e) => setActive(e.target.checked)}
              className="h-4 w-4 rounded border-ink-300 text-beam-600 focus:ring-beam-500"
            />
            Active (run on cadence)
          </label>

          <details className="rounded-lg border border-ink-200 bg-ink-50 p-3 dark:bg-pharos-navy-900/30">
            <summary className="cursor-pointer text-xs font-bold uppercase tracking-wider text-ink-500">
              Report content
            </summary>
            <div className="mt-3 space-y-3">
              <div>
                <label className="mb-1 block text-xs font-semibold text-ink-700">
                  Title (used as the saved report's name)
                </label>
                <input
                  value={reqForm.name}
                  onChange={(e) =>
                    setReqForm({ ...reqForm, name: e.target.value })
                  }
                  className="input w-full"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-ink-700">
                  Keywords (OR; comma- or newline-separated)
                </label>
                <textarea
                  value={reqForm.keywords}
                  onChange={(e) =>
                    setReqForm({ ...reqForm, keywords: e.target.value })
                  }
                  className="input min-h-[60px] w-full"
                  placeholder="ransomware, Volt Typhoon, CVE-2024-3400"
                />
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <div>
                  <label className="mb-1 block text-xs font-semibold text-ink-700">
                    Lookback (days)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={365}
                    value={reqForm.since_days}
                    onChange={(e) =>
                      setReqForm({
                        ...reqForm,
                        since_days: Math.max(1, +e.target.value || 7),
                      })
                    }
                    className="input !w-28"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold text-ink-700">
                    Audience
                  </label>
                  <select
                    value={reqForm.audience}
                    onChange={(e) =>
                      setReqForm({
                        ...reqForm,
                        audience: e.target.value as FormState["audience"],
                      })
                    }
                    className="input"
                  >
                    <option value="executive">Executive</option>
                    <option value="technical">Technical</option>
                    <option value="both">Both</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold text-ink-700">
                    Length
                  </label>
                  <select
                    value={reqForm.length}
                    onChange={(e) =>
                      setReqForm({
                        ...reqForm,
                        length: e.target.value as FormState["length"],
                      })
                    }
                    className="input"
                  >
                    <option value="short">Short (1-2 pp)</option>
                    <option value="medium">Medium (2-3 pp)</option>
                    <option value="long">Long (3-4 pp)</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold text-ink-700">
                    Structure
                  </label>
                  <select
                    value={reqForm.structure_kind}
                    onChange={(e) =>
                      setReqForm({
                        ...reqForm,
                        structure_kind: e.target
                          .value as FormState["structure_kind"],
                      })
                    }
                    className="input"
                  >
                    <option value="BLUF">BLUF (default)</option>
                    <option value="custom">Custom sections</option>
                  </select>
                </div>
              </div>
              {reqForm.structure_kind === "custom" && (
                <div>
                  <label className="mb-1 block text-xs font-semibold text-ink-700">
                    Custom sections (one per line)
                  </label>
                  <textarea
                    value={reqForm.sections}
                    onChange={(e) =>
                      setReqForm({ ...reqForm, sections: e.target.value })
                    }
                    className="input min-h-[80px] w-full font-mono text-xs"
                  />
                </div>
              )}
              <div>
                <label className="mb-1 block text-xs font-semibold text-ink-700">
                  Scope note (optional)
                </label>
                <textarea
                  value={reqForm.scope_note}
                  onChange={(e) =>
                    setReqForm({ ...reqForm, scope_note: e.target.value })
                  }
                  className="input min-h-[50px] w-full"
                />
              </div>
              <div className="text-[11px] italic text-ink-500">
                Tip: build &amp; preview your filter as a one-off in "New
                report" first. The schedule reuses the same engine.
              </div>
            </div>
          </details>
        </div>

        {err && (
          <div className="mt-3 rounded-lg border border-danger-100 bg-danger-50 px-3 py-2 text-sm text-danger-600">
            {err}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="btn-ghost">
            Cancel
          </button>
          <button
            onClick={() => {
              setErr(null);
              save.mutate();
            }}
            disabled={save.isPending || !name.trim() || !reqForm.name.trim()}
            className="btn-primary"
          >
            <Check className="h-4 w-4" />
            {save.isPending
              ? "Saving…"
              : existing
                ? "Save changes"
                : "Create schedule"}
          </button>
        </div>
      </div>
    </div>
  );
}

function requestToFormState(req: ReportRequest, fallbackName: string): FormState {
  return {
    name: req.name || fallbackName,
    keywords: (req.keywords || []).join(", "),
    since_days: req.since_days || 7,
    rows: Object.entries(req.any_of || {}).flatMap(([type, names]) =>
      (names || []).map((name) => ({ type, name })),
    ),
    has_types: req.has_entity_types || [],
    structure_kind: req.structure_kind || "BLUF",
    sections: (req.sections || []).join("\n"),
    audience: req.audience || "both",
    length: req.length || "short",
    scope_note: req.scope_note || "",
  };
}
