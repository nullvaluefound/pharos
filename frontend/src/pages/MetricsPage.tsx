import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { PageHeader } from "../components/PageHeader";
import { api } from "../lib/api";
import type {
  EntityCount,
  MetricsOverview,
  SeverityBreakdown,
  TimeBucket,
} from "../lib/types";

const TYPES = [
  { value: "threat_actor", label: "Threat actors" },
  { value: "malware", label: "Malware" },
  { value: "cve", label: "CVEs" },
  { value: "ttp_mitre", label: "MITRE techniques" },
  { value: "vendor", label: "Vendors" },
  { value: "sector", label: "Sectors" },
  { value: "country", label: "Countries" },
];

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#dc2626",
  high: "#f59e0b",
  medium: "#3b82f6",
  low: "#22c55e",
  unknown: "#a1a1aa",
};

export function MetricsPage() {
  const [days, setDays] = useState(30);
  const [type, setType] = useState("threat_actor");

  const overview = useQuery<MetricsOverview>({
    queryKey: ["metrics-overview", days],
    queryFn: () => api(`/metrics/overview?days=${days}`),
  });
  const top = useQuery<{ entities: EntityCount[] }>({
    queryKey: ["metrics-top", type, days],
    queryFn: () => api(`/metrics/top-entities?type=${type}&days=${days}&limit=15`),
  });
  const ts = useQuery<{ buckets: TimeBucket[] }>({
    queryKey: ["metrics-ts", days],
    queryFn: () => api(`/metrics/timeseries?days=${days}&bucket=day`),
  });
  const sev = useQuery<{ breakdown: SeverityBreakdown[] }>({
    queryKey: ["metrics-sev", days],
    queryFn: () => api(`/metrics/severity?days=${days}`),
  });

  const sevData = (sev.data?.breakdown || []).map((s) => ({
    name: s.severity || "unknown",
    value: s.count,
  }));

  return (
    <div className="mx-auto max-w-6xl px-5 py-6">
      <PageHeader
        title="Insights"
        subtitle="Aggregate views over your enriched corpus."
        actions={
          <div className="inline-flex rounded-lg border border-ink-200 bg-white p-0.5">
            {[7, 14, 30, 90].map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={
                  "rounded-md px-3 py-1 text-xs font-medium " +
                  (days === d
                    ? "bg-ink-100 text-ink-900"
                    : "text-ink-500 hover:text-ink-900")
                }
              >
                {d}d
              </button>
            ))}
          </div>
        }
      />

      <div className="grid gap-3 sm:grid-cols-3 md:grid-cols-6">
        <Stat label="Articles" value={overview.data?.article_count ?? 0} />
        <Stat label="Enriched" value={overview.data?.enriched_count ?? 0} />
        <Stat label="Pending" value={overview.data?.pending_count ?? 0} />
        <Stat label="Constellations" value={overview.data?.cluster_count ?? 0} />
        <Stat label="Feeds" value={overview.data?.feed_count ?? 0} />
        <Stat label="Saved" value={overview.data?.saved_count ?? 0} />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-2 p-5">
          <h3 className="mb-3 text-sm font-bold uppercase tracking-wider text-ink-500">
            Volume over time
          </h3>
          <div className="h-64">
            <ResponsiveContainer>
              <LineChart data={ts.data?.buckets || []}>
                <CartesianGrid stroke="#e4e4e7" strokeDasharray="3 3" />
                <XAxis dataKey="bucket" stroke="#71717a" fontSize={11} />
                <YAxis stroke="#71717a" fontSize={11} allowDecimals={false} />
                <Tooltip />
                <Line
                  type="monotone"
                  dataKey="count"
                  stroke="#2563eb"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card p-5">
          <h3 className="mb-3 text-sm font-bold uppercase tracking-wider text-ink-500">
            Severity mix
          </h3>
          {sevData.length === 0 ? (
            <p className="text-xs text-ink-400">No data yet.</p>
          ) : (
            <div className="h-64">
              <ResponsiveContainer>
                <PieChart>
                  <Pie
                    data={sevData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={45}
                    outerRadius={85}
                  >
                    {sevData.map((s) => (
                      <Cell key={s.name} fill={SEVERITY_COLORS[s.name] || "#a1a1aa"} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      <div className="card mt-4 p-5">
        <div className="mb-3 flex items-center gap-3">
          <h3 className="text-sm font-bold uppercase tracking-wider text-ink-500">
            Top entities
          </h3>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="input !w-44 !py-1 !text-xs"
          >
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        {(top.data?.entities || []).length === 0 ? (
          <p className="text-xs text-ink-400">
            No matches yet — wait for the lantern to enrich more articles.
          </p>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[2fr,3fr]">
            <div className="h-72">
              <ResponsiveContainer>
                <BarChart
                  data={top.data!.entities.slice(0, 10)}
                  layout="vertical"
                  margin={{ left: 80 }}
                >
                  <CartesianGrid stroke="#e4e4e7" strokeDasharray="3 3" />
                  <XAxis type="number" stroke="#71717a" fontSize={11} allowDecimals={false} />
                  <YAxis
                    type="category"
                    dataKey="display_name"
                    stroke="#71717a"
                    fontSize={11}
                    width={80}
                  />
                  <Tooltip />
                  <Bar dataKey="count" fill="#2563eb" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <ul className="space-y-1 text-sm">
              {top.data!.entities.map((e) => (
                <li key={e.name} className="flex items-center gap-2 py-1">
                  <Link
                    to={`/search?q=${encodeURIComponent(e.display_name)}`}
                    className="flex-1 truncate hover:text-beam-700"
                  >
                    {e.display_name}
                  </Link>
                  <span className="chip">{e.count}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="card p-4">
      <div className="text-xs font-semibold uppercase tracking-wider text-ink-400">
        {label}
      </div>
      <div className="mt-1 text-2xl font-bold tabular-nums">{value.toLocaleString()}</div>
    </div>
  );
}
