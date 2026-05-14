import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  BellOff,
  Check,
  Copy,
  Download,
  Edit3,
  Eye,
  Mail,
  Plus,
  Share2,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import { PageHeader } from "../components/PageHeader";
import { Empty } from "../components/Empty";
import { api } from "../lib/api";
import {
  ENTITY_TYPES,
  HAS_METADATA_OPTIONS,
  type WatchOut,
} from "../lib/types";

interface WatchExport {
  kind: string;
  version: number;
  name: string;
  query: Record<string, unknown>;
  code: string;
}

interface FormState {
  id: number | null;
  name: string;
  // Two-level boolean: outer index = AND, inner index = OR. So
  // `[["apt29", "volt typhoon"], ["zero-day", "0day"]]` means
  // (apt29 OR "volt typhoon") AND (zero-day OR 0day).
  keywordGroups: string[][];
  since: number | "";
  notify: boolean;
  notifyEmail: boolean;
  rows: { type: string; name: string }[];
  hasTypes: string[];
}

const EMPTY_FORM: FormState = {
  id: null,
  name: "",
  keywordGroups: [],
  since: 30,
  notify: false,
  notifyEmail: false,
  rows: [],
  hasTypes: [],
};

interface EmailStatus {
  email: string | null;
  smtp_configured: boolean;
}

export function WatchesPage() {
  const qc = useQueryClient();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [type, setType] = useState("threat_actor");
  const [name, setName] = useState("");
  // One draft buffer per keyword group, indexed by group position.
  // Cleared on add / on group remove.
  const [kwDrafts, setKwDrafts] = useState<string[]>([]);

  const { data: watches } = useQuery<WatchOut[]>({
    queryKey: ["watches"],
    queryFn: () => api<WatchOut[]>("/watches"),
  });

  // Used to gate the "Also email me" checkbox. We don't block users
  // from saving the watch with notify_email=true if they haven't set
  // up email yet -- the backend just won't deliver until they do --
  // but we surface a helpful banner so they understand why.
  const { data: emailStatus } = useQuery<EmailStatus>({
    queryKey: ["settings", "email"],
    queryFn: () => api<EmailStatus>("/settings/email"),
  });
  const canEmail =
    !!emailStatus?.smtp_configured && !!emailStatus?.email;

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        name: form.name,
        notify: form.notify,
        notify_email: form.notifyEmail,
        query: buildQuery(form),
      };
      if (form.id) {
        return api(`/watches/${form.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
      }
      return api("/watches", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watches"] });
      setForm(EMPTY_FORM);
    },
  });

  const del = useMutation({
    mutationFn: (id: number) => api(`/watches/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watches"] }),
  });

  // Export / Import modal state.
  const [exporting, setExporting] = useState<WatchExport | null>(null);
  const [importing, setImporting] = useState(false);
  const importedAfter = () => {
    qc.invalidateQueries({ queryKey: ["watches"] });
    setImporting(false);
  };

  async function startExport(watchId: number) {
    try {
      const env = await api<WatchExport>(`/watches/${watchId}/export`);
      setExporting(env);
    } catch (e: any) {
      alert(`Could not export: ${e?.message || e}`);
    }
  }

  function startEdit(w: WatchOut) {
    const groups = parseKeywordGroups(w.query?.text);
    setForm({
      id: w.id,
      name: w.name,
      notify: w.notify,
      notifyEmail: w.notify_email,
      keywordGroups: groups,
      since: w.query?.since_days ?? 30,
      rows: queryToRows(w.query?.any_of || {}),
      hasTypes: w.query?.has_entity_types || [],
    });
    setKwDrafts(new Array(groups.length).fill(""));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function setDraft(groupIdx: number, v: string) {
    setKwDrafts((d) => {
      const n = d.slice();
      n[groupIdx] = v;
      return n;
    });
  }

  /** Add one or many keywords (split on comma) to a group. */
  function addKeywordsToGroup(groupIdx: number, raw: string) {
    const parts = raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (parts.length === 0) return;
    setForm((f) => {
      const groups = f.keywordGroups.map((g, i) => {
        if (i !== groupIdx) return g;
        const next = g.slice();
        for (const p of parts) if (!next.includes(p)) next.push(p);
        return next;
      });
      return { ...f, keywordGroups: groups };
    });
    setDraft(groupIdx, "");
  }

  function removeKeyword(groupIdx: number, kwIdx: number) {
    setForm((f) => ({
      ...f,
      keywordGroups: f.keywordGroups
        .map((g, gi) =>
          gi === groupIdx ? g.filter((_, ki) => ki !== kwIdx) : g,
        )
        // Drop any group that became empty.
        .filter((g) => g.length > 0),
    }));
    setKwDrafts((d) => d.filter((_, i) => i !== groupIdx || d.length === 1));
  }

  function addGroup() {
    setForm((f) => ({ ...f, keywordGroups: [...f.keywordGroups, []] }));
    setKwDrafts((d) => [...d, ""]);
  }

  function removeGroup(groupIdx: number) {
    setForm((f) => ({
      ...f,
      keywordGroups: f.keywordGroups.filter((_, i) => i !== groupIdx),
    }));
    setKwDrafts((d) => d.filter((_, i) => i !== groupIdx));
  }

  function addRow() {
    if (!name.trim()) return;
    setForm((f) => ({ ...f, rows: [...f.rows, { type, name: name.trim() }] }));
    setName("");
  }

  function removeRow(i: number) {
    setForm((f) => ({ ...f, rows: f.rows.filter((_, idx) => idx !== i) }));
  }

  function toggleHas(v: string) {
    setForm((f) => ({
      ...f,
      hasTypes: f.hasTypes.includes(v)
        ? f.hasTypes.filter((x) => x !== v)
        : [...f.hasTypes, v],
    }));
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) return;
    save.mutate();
  }

  return (
    <div className="mx-auto max-w-4xl px-5 py-6">
      <PageHeader
        title="Watches"
        subtitle="Saved searches that follow you around. Optionally get notified when matches appear."
        actions={
          <button
            type="button"
            onClick={() => setImporting(true)}
            className="btn-secondary"
            title="Import a watch from a share code or .json file"
          >
            <Upload className="h-4 w-4" /> Import
          </button>
        }
      />

      <form onSubmit={submit} className="card mb-6 space-y-4 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">
            {form.id ? "Edit watch" : "Create a new watch"}
          </h2>
          {form.id && (
            <button
              type="button"
              onClick={() => setForm(EMPTY_FORM)}
              className="btn-ghost !py-1"
            >
              <X className="h-4 w-4" /> Cancel edit
            </button>
          )}
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold text-ink-700">Name</label>
          <input
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="e.g. Volt Typhoon coverage"
            className="input"
            required
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold text-ink-700">
            Keywords{" "}
            <span className="font-normal text-ink-500">
              (boolean filter against article body)
            </span>
          </label>

          {form.keywordGroups.length === 0 ? (
            <button
              type="button"
              onClick={addGroup}
              className="btn-secondary !py-1.5 text-xs"
            >
              <Plus className="h-4 w-4" /> Add a keyword group
            </button>
          ) : (
            <>
              {form.keywordGroups.map((group, gi) => (
                <div key={gi}>
                  {gi > 0 && (
                    <div
                      className="my-2 flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-ink-500"
                      aria-label="and"
                    >
                      <span className="h-px flex-1 bg-ink-200" />
                      AND
                      <span className="h-px flex-1 bg-ink-200" />
                    </div>
                  )}
                  <div className="rounded-lg border border-ink-200 bg-ink-50/40 p-2.5 dark:bg-pharos-navy-700/40">
                    <div className="mb-1 flex items-center justify-between text-[11px] text-ink-500">
                      <span>
                        Group {gi + 1}{" "}
                        <span className="text-ink-400">
                          — any of these (OR)
                        </span>
                      </span>
                      <button
                        type="button"
                        onClick={() => removeGroup(gi)}
                        className="text-ink-400 hover:text-danger-600"
                        title="Remove this group"
                        aria-label={`Remove group ${gi + 1}`}
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>

                    <div className="flex flex-wrap items-center gap-1">
                      {group.map((k, ki) => (
                        <span key={`${k}-${ki}`} className="chip-blue">
                          {k}
                          <button
                            type="button"
                            onClick={() => removeKeyword(gi, ki)}
                            className="-mr-1 ml-1 text-beam-700 hover:text-beam-900"
                            aria-label={`Remove keyword ${k}`}
                          >
                            ×
                          </button>
                        </span>
                      ))}
                      <input
                        value={kwDrafts[gi] || ""}
                        onChange={(e) => setDraft(gi, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === ",") {
                            e.preventDefault();
                            addKeywordsToGroup(gi, kwDrafts[gi] || "");
                          } else if (
                            e.key === "Backspace" &&
                            !(kwDrafts[gi] || "") &&
                            group.length > 0
                          ) {
                            removeKeyword(gi, group.length - 1);
                          }
                        }}
                        onBlur={() => {
                          if ((kwDrafts[gi] || "").trim()) {
                            addKeywordsToGroup(gi, kwDrafts[gi] || "");
                          }
                        }}
                        placeholder={
                          group.length === 0
                            ? "type term, comma- or Enter-separated"
                            : "+ another"
                        }
                        className="min-w-[10rem] flex-1 bg-transparent px-1 py-0.5 text-sm focus:outline-none"
                      />
                    </div>
                  </div>
                </div>
              ))}

              <button
                type="button"
                onClick={addGroup}
                className="btn-ghost mt-2 !py-1 text-xs"
              >
                <Plus className="h-3.5 w-3.5" /> AND another group
              </button>

              <p className="mt-1 text-[11px] italic text-ink-400">
                Tip: terms inside a group are <strong>OR</strong>-matched;
                groups are <strong>AND</strong>-matched. Comma- or Enter-
                separated.
                {form.keywordGroups.length === 1 &&
                  form.keywordGroups[0].length > 1 &&
                  " Currently matching: any of the listed terms."}
                {form.keywordGroups.length > 1 &&
                  form.keywordGroups.every((g) => g.length === 1) &&
                  " Currently matching: all of the listed terms."}
              </p>
            </>
          )}
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold text-ink-700">
            Match if any of these are present
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
                  addRow();
                }
              }}
              placeholder="entity name (e.g. apt29)"
              className="input"
            />
            <button type="button" onClick={addRow} className="btn-secondary">
              <Plus className="h-4 w-4" /> Add
            </button>
          </div>
          {form.rows.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {form.rows.map((r, i) => (
                <span key={i} className="chip-blue">
                  {ENTITY_TYPES.find((x) => x.value === r.type)?.label}: {r.name}
                  <button
                    type="button"
                    onClick={() => removeRow(i)}
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
            Must include metadata of these types
          </label>
          <div className="flex flex-wrap gap-2">
            {HAS_METADATA_OPTIONS.map((o) => (
              <label
                key={o.value}
                className={
                  "cursor-pointer select-none rounded-full border px-2.5 py-1 text-xs " +
                  (form.hasTypes.includes(o.value)
                    ? "border-beam-500 bg-beam-50 text-beam-700"
                    : "border-ink-200 text-ink-600 hover:border-ink-400")
                }
              >
                <input
                  type="checkbox"
                  className="hidden"
                  checked={form.hasTypes.includes(o.value)}
                  onChange={() => toggleHas(o.value)}
                />
                {o.label}
              </label>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-xs font-semibold text-ink-700">
              Within (days)
            </label>
            <input
              type="number"
              min={1}
              max={365}
              value={form.since}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  since: e.target.value === "" ? "" : Number(e.target.value),
                }))
              }
              className="input !w-32"
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.notify}
              onChange={(e) => setForm((f) => ({ ...f, notify: e.target.checked }))}
              className="h-4 w-4 rounded border-ink-300 text-beam-600 focus:ring-beam-500"
            />
            Notify me in-app when new matches arrive
          </label>
          <label
            className={
              "flex items-center gap-2 text-sm " +
              (canEmail ? "" : "text-ink-500")
            }
            title={
              canEmail
                ? "Send a digest email whenever new articles match this watch"
                : "Set a notification email in Settings to enable this"
            }
          >
            <input
              type="checkbox"
              checked={form.notifyEmail}
              onChange={(e) =>
                setForm((f) => ({ ...f, notifyEmail: e.target.checked }))
              }
              className="h-4 w-4 rounded border-ink-300 text-beam-600 focus:ring-beam-500"
            />
            <Mail className="h-3.5 w-3.5" />
            Also email me a digest
          </label>
          <button type="submit" className="btn-primary ml-auto" disabled={save.isPending}>
            {save.isPending ? "Saving…" : form.id ? "Update watch" : "Create watch"}
          </button>
        </div>
        {form.notifyEmail && !canEmail && (
          <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-900/20 dark:text-amber-200">
            {emailStatus && !emailStatus.smtp_configured ? (
              <>
                Email delivery is not configured on this server. Ask your
                administrator to set <code>SMTP_HOST</code> in <code>.env</code>.
                Until then this watch is saved as in-app-only.
              </>
            ) : (
              <>
                You haven't set a notification email yet. Add one on the{" "}
                <Link to="/settings" className="font-medium underline">
                  Settings page
                </Link>
                . The watch will save, but emails won't go out until then.
              </>
            )}
          </div>
        )}
      </form>

      <h2 className="mb-3 text-sm font-bold uppercase tracking-wider text-ink-400">
        Your watches
      </h2>
      {!watches || watches.length === 0 ? (
        <Empty
          icon={Eye}
          title="No watches yet"
          hint="Use the form above to save your first watch."
        />
      ) : (
        <ul className="space-y-2">
          {watches.map((w) => (
            <li key={w.id} className="card flex items-center gap-3 p-4">
              <Eye className="h-4 w-4 text-ink-400" />
              <div className="flex-1 min-w-0">
                <Link
                  to={`/stream?watch=${w.id}`}
                  className="block truncate text-sm font-medium text-ink-900 hover:text-beam-700"
                >
                  {w.name}
                </Link>
                <div className="text-xs text-ink-500">{summarize(w.query)}</div>
              </div>
              <span
                className={
                  "chip text-[10px] " +
                  (w.notify ? "chip-blue" : "")
                }
                title={w.notify ? "In-app notifications on" : "In-app notifications off"}
              >
                {w.notify ? <Bell className="h-3 w-3" /> : <BellOff className="h-3 w-3" />}
                {w.notify ? "Notify" : "Silent"}
              </span>
              {w.notify_email && (
                <span
                  className="chip chip-blue text-[10px]"
                  title="Email digest is enabled for this watch"
                >
                  <Mail className="h-3 w-3" />
                  Email
                </span>
              )}
              <button
                onClick={() => startExport(w.id)}
                className="btn-ghost !py-1"
                title="Export / share this watch"
              >
                <Share2 className="h-4 w-4" />
              </button>
              <button
                onClick={() => startEdit(w)}
                className="btn-ghost !py-1"
                title="Edit"
              >
                <Edit3 className="h-4 w-4" />
              </button>
              <button
                onClick={() => {
                  if (confirm(`Delete watch "${w.name}"?`)) del.mutate(w.id);
                }}
                className="btn-ghost !py-1 text-danger-600 hover:bg-danger-50"
                title="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {exporting && (
        <ExportModal env={exporting} onClose={() => setExporting(null)} />
      )}
      {importing && (
        <ImportModal onClose={() => setImporting(false)} onImported={importedAfter} />
      )}
    </div>
  );
}

// ===========================================================================
// Export modal: copyable share code + .json download
// ===========================================================================
function ExportModal({
  env,
  onClose,
}: {
  env: WatchExport;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(env.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Fallback for browsers blocking clipboard write -- select-all the
      // textarea so the user can ⌘/Ctrl-C manually.
      const ta = document.getElementById("pharos-share-code") as HTMLTextAreaElement | null;
      ta?.select();
    }
  }

  function downloadJson() {
    const { code: _, ...envOnly } = env;
    const blob = new Blob([JSON.stringify(envOnly, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const safeName = env.name.replace(/[^a-z0-9_-]+/gi, "-").slice(0, 60);
    a.href = url;
    a.download = `pharos-watch-${safeName || "export"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <ModalShell title="Share this watch" onClose={onClose}>
      <p className="text-sm text-ink-600">
        <strong>{env.name}</strong> — anyone on Pharos can paste this code
        on their own Watches page to clone the filter.
      </p>
      <div>
        <label className="mb-1 block text-xs font-semibold text-ink-700">
          Share code
        </label>
        <textarea
          id="pharos-share-code"
          readOnly
          value={env.code}
          className="input h-28 w-full resize-none break-all font-mono text-[11px]"
          onFocus={(e) => e.currentTarget.select()}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <button onClick={copy} className="btn-primary">
          {copied ? (
            <>
              <Check className="h-4 w-4" /> Copied
            </>
          ) : (
            <>
              <Copy className="h-4 w-4" /> Copy code
            </>
          )}
        </button>
        <button onClick={downloadJson} className="btn-secondary">
          <Download className="h-4 w-4" /> Download .json
        </button>
        <button onClick={onClose} className="btn-ghost ml-auto">
          Close
        </button>
      </div>
      <p className="text-[11px] text-ink-500">
        Notification preferences are NOT included — each importer decides
        for themselves.
      </p>
    </ModalShell>
  );
}

// ===========================================================================
// Import modal: paste share code OR upload .json
// ===========================================================================
function ImportModal({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: () => void;
}) {
  const [code, setCode] = useState("");
  const [nameOverride, setNameOverride] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function pickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setErr(null);
    setBusy(true);
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      await api("/watches/import", {
        method: "POST",
        body: JSON.stringify({
          data,
          name_override: nameOverride.trim() || undefined,
        }),
      });
      onImported();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function importCode() {
    if (!code.trim()) {
      setErr("Paste a share code first.");
      return;
    }
    setErr(null);
    setBusy(true);
    try {
      await api("/watches/import", {
        method: "POST",
        body: JSON.stringify({
          code: code.trim(),
          name_override: nameOverride.trim() || undefined,
        }),
      });
      onImported();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell title="Import a watch" onClose={onClose}>
      <p className="text-sm text-ink-600">
        Paste a Pharos share code below, or upload a watch <code>.json</code>{" "}
        file. Imports always start with notifications off.
      </p>
      <div>
        <label className="mb-1 block text-xs font-semibold text-ink-700">
          Share code
        </label>
        <textarea
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Paste the share code here…"
          className="input h-28 w-full resize-none break-all font-mono text-[11px]"
        />
      </div>
      <div>
        <label className="mb-1 block text-xs font-semibold text-ink-700">
          Rename on import{" "}
          <span className="font-normal text-ink-500">
            (optional — auto-suffixed if it collides)
          </span>
        </label>
        <input
          value={nameOverride}
          onChange={(e) => setNameOverride(e.target.value)}
          placeholder="Leave blank to keep the original name"
          className="input"
        />
      </div>
      {err && (
        <div className="rounded-md border border-danger-300 bg-danger-50 p-2 text-xs text-danger-700">
          {err}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <button onClick={importCode} disabled={busy} className="btn-primary">
          <Upload className="h-4 w-4" />
          {busy ? "Importing…" : "Import code"}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={pickFile}
        />
        <button
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="btn-secondary"
        >
          <Upload className="h-4 w-4" /> Upload .json
        </button>
        <button onClick={onClose} className="btn-ghost ml-auto" disabled={busy}>
          Cancel
        </button>
      </div>
    </ModalShell>
  );
}

// ---------- shared modal chrome ----------
function ModalShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="card w-full max-w-lg space-y-4 p-5 shadow-xl">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="btn-ghost !py-1" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function quoteKw(k: string): string {
  // SQLite FTS5: phrases are wrapped in double quotes; embedded quotes
  // are escaped by doubling.
  return `"${k.trim().replace(/"/g, '""')}"`;
}

/** Encode the keyword-group form state into an FTS5 boolean expression.
 *  Inner = OR, outer = AND. Examples:
 *
 *    [["foo"]]                          -> "foo"
 *    [["foo", "bar"]]                   -> "foo" OR "bar"
 *    [["foo"], ["bar"]]                 -> "foo" AND "bar"
 *    [["foo", "bar"], ["baz", "qux"]]   -> ("foo" OR "bar") AND ("baz" OR "qux")
 */
function encodeKeywordGroups(groups: string[][]): string | null {
  const clean = groups
    .map((g) => g.map((k) => k.trim()).filter(Boolean))
    .filter((g) => g.length > 0);
  if (clean.length === 0) return null;
  if (clean.length === 1) {
    return clean[0].map(quoteKw).join(" OR ");
  }
  return clean
    .map((g) =>
      g.length === 1 ? quoteKw(g[0]) : "(" + g.map(quoteKw).join(" OR ") + ")",
    )
    .join(" AND ");
}

/** Round-trip the FTS5-encoded ``text`` field back into keyword groups.
 *  Recognizes our own encoder's output (groups joined by AND, terms
 *  inside a group joined by OR), and gracefully falls back to legacy
 *  watch formats:
 *    - last-turn's flat OR list             -> one group
 *    - even older single-string searches    -> one group, one keyword
 */
function parseKeywordGroups(text: string | null | undefined): string[][] {
  if (!text) return [];
  const trimmed = String(text).trim();
  if (!trimmed) return [];

  const groupStrs = splitTopLevelAnd(trimmed);
  const out: string[][] = [];
  const phraseRe = /^"((?:[^"]|"")*)"$/;

  for (const gsRaw of groupStrs) {
    let gs = gsRaw.trim();
    // Strip outer parens added by the encoder for multi-term groups.
    if (gs.startsWith("(") && gs.endsWith(")")) {
      gs = gs.slice(1, -1).trim();
    }
    const parts = gs.split(/\s+OR\s+/);
    if (parts.every((p) => phraseRe.test(p))) {
      out.push(
        parts.map((p) => {
          const m = p.match(phraseRe);
          return (m ? m[1] : p).replace(/""/g, '"');
        }),
      );
    } else {
      // Couldn't parse this fragment as our format -- bail out and
      // treat the whole original input as a single literal keyword.
      return [[trimmed]];
    }
  }

  if (out.length === 0) return [[trimmed]];
  return out;
}

/** Depth- and quote-aware split on top-level " AND ". */
function splitTopLevelAnd(s: string): string[] {
  const out: string[] = [];
  let cur = "";
  let depth = 0;
  let inQ = false;
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (c === '"') {
      // FTS5 escape: doubled quote inside a phrase
      if (inQ && s[i + 1] === '"') {
        cur += '""';
        i += 2;
        continue;
      }
      inQ = !inQ;
      cur += c;
      i++;
      continue;
    }
    if (!inQ) {
      if (c === "(") depth++;
      if (c === ")") depth--;
      // Match " AND " case-insensitively at top level
      if (
        depth === 0 &&
        i + 5 <= s.length &&
        s[i] === " " &&
        s.substring(i + 1, i + 4).toUpperCase() === "AND" &&
        s[i + 4] === " "
      ) {
        out.push(cur);
        cur = "";
        i += 5;
        continue;
      }
    }
    cur += c;
    i++;
  }
  if (cur.trim()) out.push(cur);
  return out;
}

function buildQuery(f: FormState) {
  const any_of: Record<string, string[]> = {};
  for (const r of f.rows) {
    any_of[r.type] = [...(any_of[r.type] || []), r.name];
  }
  return {
    any_of,
    has_entity_types: f.hasTypes,
    text: encodeKeywordGroups(f.keywordGroups),
    since_days: f.since === "" ? null : Number(f.since),
  };
}

function queryToRows(any_of: Record<string, string[]>): { type: string; name: string }[] {
  const out: { type: string; name: string }[] = [];
  for (const [t, names] of Object.entries(any_of || {})) {
    for (const n of names) out.push({ type: t, name: n });
  }
  return out;
}

function summarize(q: any): string {
  const parts: string[] = [];
  const groups = parseKeywordGroups(q?.text);
  if (groups.length === 1 && groups[0].length === 1) {
    parts.push(`"${groups[0][0]}"`);
  } else if (groups.length === 1) {
    parts.push(groups[0].map((k) => `"${k}"`).join(" OR "));
  } else if (groups.length > 1) {
    parts.push(
      groups
        .map((g) =>
          g.length === 1
            ? `"${g[0]}"`
            : "(" + g.map((k) => `"${k}"`).join(" OR ") + ")",
        )
        .join(" AND "),
    );
  }
  const ao = q?.any_of || {};
  for (const [t, ns] of Object.entries(ao)) {
    parts.push(`${t}: ${(ns as string[]).join(", ")}`);
  }
  if (q?.has_entity_types?.length) {
    parts.push(`has: ${q.has_entity_types.join(", ")}`);
  }
  if (q?.since_days) parts.push(`last ${q.since_days}d`);
  return parts.join(" · ") || "any article";
}
