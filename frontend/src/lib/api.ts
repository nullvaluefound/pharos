// When the SPA is served from a sub-path (e.g. "/pharos/" via nginx),
// `import.meta.env.BASE_URL` is "/pharos/" -- so API calls go to
// "/pharos/api/v1/..." and the reverse-proxy strips the prefix.
const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");
const API_PREFIX = `${BASE}/api/v1`;
const TOKEN_KEY = "pharos_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...((init.headers as Record<string, string>) || {}),
  };
  if (init.body && !(init.body instanceof FormData)) {
    headers["Content-Type"] ||= "application/json";
  }
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_PREFIX}${path}`, {
    credentials: "include",
    ...init,
    headers,
  });

  if (res.status === 401) {
    setToken(null);
    if (!location.pathname.startsWith("/login")) {
      location.href = "/login";
    }
    throw new ApiError("Unauthorized", 401);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || detail;
    } catch {}
    throw new ApiError(`${res.status}: ${detail}`, res.status);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

// Convenience for raw blob downloads
export async function apiBlob(path: string): Promise<Blob> {
  const token = getToken();
  const res = await fetch(`${API_PREFIX}${path}`, {
    credentials: "include",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new ApiError(`${res.status}: ${res.statusText}`, res.status);
  return await res.blob();
}
