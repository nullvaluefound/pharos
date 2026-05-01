import { create } from "zustand";

import { api, getToken } from "./api";

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "pharos.theme";

function systemPrefersDark(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function readStored(): Theme {
  if (typeof localStorage === "undefined") return "system";
  const v = localStorage.getItem(STORAGE_KEY);
  if (v === "light" || v === "dark" || v === "system") return v;
  return "system";
}

export function effectiveDark(theme: Theme): boolean {
  if (theme === "dark") return true;
  if (theme === "light") return false;
  return systemPrefersDark();
}

function apply(theme: Theme) {
  const dark = effectiveDark(theme);
  const root = document.documentElement;
  if (dark) root.classList.add("dark");
  else root.classList.remove("dark");
  // Keep the meta theme-color in sync so mobile chrome / iOS adjust.
  const metas = document.querySelectorAll<HTMLMetaElement>(
    'meta[name="theme-color"]',
  );
  metas.forEach((m) => (m.content = dark ? "#0b1224" : "#fafafa"));
}

interface PreferencesPayload {
  settings: Record<string, any>;
}

async function pushRemote(theme: Theme): Promise<void> {
  if (!getToken()) return; // not logged in -> local only
  try {
    // Read-modify-write so we don't clobber other prefs that might land here.
    const cur = await api<PreferencesPayload>("/settings/preferences");
    const merged = { ...(cur.settings || {}), theme };
    await api<PreferencesPayload>("/settings/preferences", {
      method: "PUT",
      body: JSON.stringify({ settings: merged }),
    });
  } catch {
    /* offline / 401 / etc. -- localStorage already saved. */
  }
}

interface ThemeState {
  theme: Theme;
  setTheme: (t: Theme, opts?: { silent?: boolean }) => void;
  toggle: () => void;
  initialize: () => void;
  /** Pull the user's remote pref after login and apply it. Quietly. */
  hydrateFromServer: () => Promise<void>;
}

export const useTheme = create<ThemeState>((set, get) => ({
  theme: readStored(),
  setTheme: (t, opts) => {
    try {
      localStorage.setItem(STORAGE_KEY, t);
    } catch (_) {
      /* noop */
    }
    apply(t);
    set({ theme: t });
    if (!opts?.silent) {
      // Best-effort write-through to the server.
      void pushRemote(t);
    }
  },
  toggle: () => {
    const cur = get().theme;
    // Two-state toggle: explicit light <-> dark. (System mode is settable
    // via hydrateFromServer or programmatically; the button is binary.)
    const next: Theme = effectiveDark(cur) ? "light" : "dark";
    get().setTheme(next);
  },
  initialize: () => {
    const cur = get().theme;
    apply(cur);
    if (cur === "system") {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const handler = () => {
        if (get().theme === "system") apply("system");
      };
      try {
        mq.addEventListener("change", handler);
      } catch (_) {
        // Safari < 14
        mq.addListener(handler);
      }
    }
  },
  hydrateFromServer: async () => {
    if (!getToken()) return;
    try {
      const r = await api<PreferencesPayload>("/settings/preferences");
      const remote = (r.settings || {}).theme as Theme | undefined;
      if (remote === "light" || remote === "dark" || remote === "system") {
        if (remote !== get().theme) {
          // Apply silently so we don't immediately push it back to the server.
          get().setTheme(remote, { silent: true });
        }
      }
    } catch {
      /* leave the locally-stored preference in place */
    }
  },
}));
