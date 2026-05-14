import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, KeyRound, Mail, Save, Send } from "lucide-react";

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

interface EmailStatus {
  email: string | null;
  smtp_configured: boolean;
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

  // ----- notification email -----
  const emailQ = useQuery<EmailStatus>({
    queryKey: ["settings", "email"],
    queryFn: () => api<EmailStatus>("/settings/email"),
  });
  const [emailDraft, setEmailDraft] = useState<string>("");
  const [emailMsg, setEmailMsg] = useState<{ ok: boolean; text: string } | null>(null);
  // Sync the draft to the server value once loaded so the field isn't
  // empty on first render when the user already has an address set.
  useEffect(() => {
    if (emailQ.data && emailDraft === "") {
      setEmailDraft(emailQ.data.email ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emailQ.data?.email]);

  const saveEmail = useMutation({
    mutationFn: () =>
      api<EmailStatus>("/settings/email", {
        method: "PUT",
        body: JSON.stringify({ email: emailDraft.trim() }),
      }),
    onSuccess: (data) => {
      qc.setQueryData(["settings", "email"], data);
      setEmailMsg({
        ok: true,
        text: data.email
          ? `Saved. Digests will go to ${data.email}.`
          : "Saved. Email digests are now disabled.",
      });
    },
    onError: (e: any) =>
      setEmailMsg({ ok: false, text: e?.message || "Could not save email" }),
  });

  const sendTest = useMutation({
    mutationFn: () => api("/settings/email/test", { method: "POST" }),
    onSuccess: () =>
      setEmailMsg({ ok: true, text: "Test email sent. Check your inbox." }),
    onError: (e: any) =>
      setEmailMsg({ ok: false, text: e?.message || "Test send failed" }),
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

      <section className="card mb-5 p-5">
        <h2 className="mb-1 flex items-center gap-2 text-base font-semibold">
          <Mail className="h-4 w-4" /> Notification email
        </h2>
        <p className="mb-4 text-xs text-ink-500">
          Watches with “Also email me a digest” turned on will send updates
          here whenever new articles match.
        </p>

        {emailQ.data && !emailQ.data.smtp_configured && (
          <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-900/20 dark:text-amber-200">
            Email delivery is not configured on this Pharos server. The address
            below will be saved, but no emails will go out until the
            administrator sets <code>SMTP_HOST</code> and friends in{" "}
            <code>.env</code>.
          </div>
        )}

        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[240px]">
            <label className="mb-1 block text-xs font-semibold text-ink-700">
              Send digests to
            </label>
            <input
              type="email"
              placeholder="you@example.com"
              autoComplete="email"
              value={emailDraft}
              onChange={(e) => {
                setEmailDraft(e.target.value);
                setEmailMsg(null);
              }}
              className="input"
            />
          </div>
          <button
            type="button"
            onClick={() => {
              setEmailMsg(null);
              saveEmail.mutate();
            }}
            disabled={saveEmail.isPending}
            className="btn-primary"
          >
            <Save className="h-4 w-4" />
            {saveEmail.isPending ? "Saving…" : "Save email"}
          </button>
          <button
            type="button"
            onClick={() => {
              setEmailMsg(null);
              sendTest.mutate();
            }}
            disabled={
              sendTest.isPending ||
              !emailQ.data?.email ||
              !emailQ.data?.smtp_configured
            }
            className="btn-ghost"
            title={
              !emailQ.data?.smtp_configured
                ? "SMTP is not configured on this server"
                : !emailQ.data?.email
                  ? "Save an email address first"
                  : "Send a one-off test message"
            }
          >
            <Send className="h-4 w-4" />
            {sendTest.isPending ? "Sending…" : "Send test"}
          </button>
        </div>

        {emailMsg && (
          <div
            className={
              "mt-3 rounded-lg border px-3 py-2 text-sm " +
              (emailMsg.ok
                ? "border-good-100 bg-good-50 text-good-600"
                : "border-danger-100 bg-danger-50 text-danger-600")
            }
          >
            {emailMsg.text}
          </div>
        )}
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
