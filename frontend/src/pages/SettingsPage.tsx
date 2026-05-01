import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, KeyRound, Save } from "lucide-react";

import { PageHeader } from "../components/PageHeader";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

interface Prefs {
  settings: {
    default_view?: "grouped" | "flat";
    default_lookback_days?: number;
    show_severity?: boolean;
  };
}

export function SettingsPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const prefsQ = useQuery<Prefs>({
    queryKey: ["preferences"],
    queryFn: () => api<Prefs>("/settings/preferences"),
  });

  const [localPrefs, setLocalPrefs] = useState<Prefs["settings"]>({});
  const merged = { ...(prefsQ.data?.settings || {}), ...localPrefs };

  const savePrefs = useMutation({
    mutationFn: () =>
      api("/settings/preferences", {
        method: "PUT",
        body: JSON.stringify({ settings: merged }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["preferences"] });
      setLocalPrefs({});
    },
  });

  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const changePw = useMutation({
    mutationFn: () =>
      api("/settings/password", {
        method: "POST",
        body: JSON.stringify({
          current_password: pw.current,
          new_password: pw.next,
        }),
      }),
    onSuccess: () => {
      setPwMsg({ ok: true, text: "Password updated." });
      setPw({ current: "", next: "", confirm: "" });
    },
    onError: (e: any) => setPwMsg({ ok: false, text: e.message || "Failed" }),
  });

  function submitPw(e: React.FormEvent) {
    e.preventDefault();
    setPwMsg(null);
    if (pw.next !== pw.confirm)
      return setPwMsg({ ok: false, text: "Passwords do not match." });
    if (pw.next.length < 8)
      return setPwMsg({ ok: false, text: "New password must be ≥ 8 chars." });
    changePw.mutate();
  }

  return (
    <div className="mx-auto max-w-3xl px-5 py-6">
      <PageHeader title="Settings" subtitle={`Signed in as ${user?.username}`} />

      <section className="card mb-5 p-5">
        <h2 className="mb-4 flex items-center gap-2 text-base font-semibold">
          <Save className="h-4 w-4" /> Preferences
        </h2>
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-semibold text-ink-700">
              Default stream view
            </label>
            <div className="flex gap-2">
              {(["grouped", "flat"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() =>
                    setLocalPrefs((p) => ({ ...p, default_view: v }))
                  }
                  className={
                    "rounded-lg border px-3 py-1.5 text-sm capitalize " +
                    ((merged.default_view || "grouped") === v
                      ? "border-beam-500 bg-beam-50 text-beam-700"
                      : "border-ink-200 hover:border-ink-300")
                  }
                >
                  {v === "grouped" ? "Constellations" : "Flat list"}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold text-ink-700">
              Default lookback (days)
            </label>
            <input
              type="number"
              min={1}
              max={365}
              value={merged.default_lookback_days ?? 30}
              onChange={(e) =>
                setLocalPrefs((p) => ({
                  ...p,
                  default_lookback_days: Number(e.target.value),
                }))
              }
              className="input !w-32"
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={merged.show_severity ?? true}
              onChange={(e) =>
                setLocalPrefs((p) => ({ ...p, show_severity: e.target.checked }))
              }
              className="h-4 w-4 rounded border-ink-300 text-beam-600"
            />
            Show severity badges on cards
          </label>
        </div>
        <div className="mt-4 flex items-center gap-2">
          <button
            onClick={() => savePrefs.mutate()}
            disabled={savePrefs.isPending}
            className="btn-primary"
          >
            <Save className="h-4 w-4" />
            {savePrefs.isPending ? "Saving…" : "Save preferences"}
          </button>
          {savePrefs.isSuccess && !savePrefs.isPending && (
            <span className="inline-flex items-center gap-1 text-xs text-good-600">
              <Check className="h-3.5 w-3.5" /> Saved
            </span>
          )}
        </div>
      </section>

      <section className="card p-5">
        <h2 className="mb-4 flex items-center gap-2 text-base font-semibold">
          <KeyRound className="h-4 w-4" /> Change password
        </h2>
        <form onSubmit={submitPw} className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-semibold text-ink-700">
              Current password
            </label>
            <input
              type="password"
              required
              value={pw.current}
              onChange={(e) => setPw((p) => ({ ...p, current: e.target.value }))}
              className="input"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold text-ink-700">
              New password
            </label>
            <input
              type="password"
              required
              value={pw.next}
              onChange={(e) => setPw((p) => ({ ...p, next: e.target.value }))}
              className="input"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold text-ink-700">Confirm</label>
            <input
              type="password"
              required
              value={pw.confirm}
              onChange={(e) => setPw((p) => ({ ...p, confirm: e.target.value }))}
              className="input"
            />
          </div>
          {pwMsg && (
            <div
              className={
                "rounded-lg border px-3 py-2 text-sm " +
                (pwMsg.ok
                  ? "border-good-100 bg-good-50 text-good-600"
                  : "border-danger-100 bg-danger-50 text-danger-600")
              }
            >
              {pwMsg.text}
            </div>
          )}
          <button type="submit" disabled={changePw.isPending} className="btn-primary">
            {changePw.isPending ? "Updating…" : "Update password"}
          </button>
        </form>
      </section>
    </div>
  );
}
