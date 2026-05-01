import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, Edit3, Eye, Plus, Trash2, X } from "lucide-react";

import { PageHeader } from "../components/PageHeader";
import { Empty } from "../components/Empty";
import { api } from "../lib/api";
import {
  ENTITY_TYPES,
  HAS_METADATA_OPTIONS,
  type WatchOut,
} from "../lib/types";

interface FormState {
  id: number | null;
  name: string;
  text: string;
  since: number | "";
  notify: boolean;
  rows: { type: string; name: string }[];
  hasTypes: string[];
}

const EMPTY_FORM: FormState = {
  id: null,
  name: "",
  text: "",
  since: 30,
  notify: false,
  rows: [],
  hasTypes: [],
};

export function WatchesPage() {
  const qc = useQueryClient();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [type, setType] = useState("threat_actor");
  const [name, setName] = useState("");

  const { data: watches } = useQuery<WatchOut[]>({
    queryKey: ["watches"],
    queryFn: () => api<WatchOut[]>("/watches"),
  });

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        name: form.name,
        notify: form.notify,
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

  function startEdit(w: WatchOut) {
    setForm({
      id: w.id,
      name: w.name,
      notify: w.notify,
      text: w.query?.text || "",
      since: w.query?.since_days ?? 30,
      rows: queryToRows(w.query?.any_of || {}),
      hasTypes: w.query?.has_entity_types || [],
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
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
          <label className="mb-1 block text-xs font-semibold text-ink-700">Free text</label>
          <input
            value={form.text}
            onChange={(e) => setForm((f) => ({ ...f, text: e.target.value }))}
            placeholder="Optional. e.g. zero-day"
            className="input"
          />
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
            Notify me when new matches arrive
          </label>
          <button type="submit" className="btn-primary ml-auto" disabled={save.isPending}>
            {save.isPending ? "Saving…" : form.id ? "Update watch" : "Create watch"}
          </button>
        </div>
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
                title={w.notify ? "Notifications on" : "Notifications off"}
              >
                {w.notify ? <Bell className="h-3 w-3" /> : <BellOff className="h-3 w-3" />}
                {w.notify ? "Notify" : "Silent"}
              </span>
              <button onClick={() => startEdit(w)} className="btn-ghost !py-1">
                <Edit3 className="h-4 w-4" />
              </button>
              <button
                onClick={() => {
                  if (confirm(`Delete watch "${w.name}"?`)) del.mutate(w.id);
                }}
                className="btn-ghost !py-1 text-danger-600 hover:bg-danger-50"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function buildQuery(f: FormState) {
  const any_of: Record<string, string[]> = {};
  for (const r of f.rows) {
    any_of[r.type] = [...(any_of[r.type] || []), r.name];
  }
  return {
    any_of,
    has_entity_types: f.hasTypes,
    text: f.text.trim() || null,
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
  if (q?.text) parts.push(`"${q.text}"`);
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
