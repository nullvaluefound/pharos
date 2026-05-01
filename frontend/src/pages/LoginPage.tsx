import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";

export function LoginPage() {
  const { login, loading, error } = useAuth();
  const navigate = useNavigate();
  const [u, setU] = useState("");
  const [p, setP] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await login(u, p);
      navigate("/");
    } catch {}
  }

  return (
    <div className="flex h-full items-center justify-center bg-gradient-to-br from-ink-50 via-white to-beam-50 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center">
          <img
            src="/logo.png"
            alt="Pharos"
            className="mb-3 h-16 w-16 rounded-2xl shadow-lg ring-1 ring-ink-200/40 dark:ring-pharos-navy-500"
          />
          <h1 className="text-2xl font-bold tracking-tight">Welcome to Pharos</h1>
          <p className="text-sm text-ink-500">A beam through the noise.</p>
        </div>
        <form onSubmit={submit} className="card space-y-4 p-6">
          <div>
            <label className="mb-1 block text-xs font-semibold text-ink-700">Username</label>
            <input
              autoFocus
              value={u}
              onChange={(e) => setU(e.target.value)}
              className="input"
              required
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold text-ink-700">Password</label>
            <input
              type="password"
              value={p}
              onChange={(e) => setP(e.target.value)}
              className="input"
              required
            />
          </div>
          {error && (
            <div className="rounded-lg border border-danger-100 bg-danger-50 px-3 py-2 text-sm text-danger-600">
              {error}
            </div>
          )}
          <button type="submit" disabled={loading} className="btn-primary w-full !py-2">
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="mt-4 text-center text-sm text-ink-500">
          Don't have an account?{" "}
          <Link to="/register" className="font-medium text-beam-600 hover:underline">
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}
