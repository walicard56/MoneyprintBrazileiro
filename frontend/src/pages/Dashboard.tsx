import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { api } from "@/api/client";
import type { DashboardSummary, Provider, Video } from "@/api/types";
import { Card, StatCard, PageHeader, Button, EmptyState, StatusBadge } from "@/components/ui";
import { IconSparkles } from "@/components/icons";

const STATUS_COLORS: Record<string, string> = {
  completed: "#10b981",
  running: "#3b82f6",
  failed: "#f43f5e",
  pending: "#64748b",
  waiting_approval: "#8b5cf6",
  cancelled: "#475569",
  retry: "#f59e0b",
};

export default function Dashboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<DashboardSummary>("/admin/dashboard"),
    refetchInterval: 5000,
  });
  const providers = useQuery({ queryKey: ["providers"], queryFn: () => api.get<Provider[]>("/providers") });
  const recent = useQuery({
    queryKey: ["videos", "recent"],
    queryFn: () => api.get<Video[]>("/videos"),
    refetchInterval: 5000,
  });

  if (isLoading) return <p className="text-slate-400">Loading…</p>;
  if (error) return <p className="text-rose-400">Could not load dashboard: {(error as Error).message}</p>;
  if (!data) return null;

  const byStatus = data.videos_by_status.map((s) => ({
    name: s.status.replace("_", " "),
    count: s.count,
    status: s.status,
  }));
  const find = (s: string) => data.videos_by_status.find((x) => x.status === s)?.count ?? 0;

  const needsSetup = data.projects_total === 0 || data.providers_enabled === 0;

  return (
    <div>
      <PageHeader
        eyebrow="Production overview"
        title={<>Dashboard</>}
        subtitle="Everything flowing through your short-video pipeline, at a glance."
        action={
          <Link to="/create">
            <Button>
              <IconSparkles width={16} height={16} /> New video
            </Button>
          </Link>
        }
      />

      {needsSetup && (
        <Card featured className="mb-6">
          <h2 className="mb-3 text-sm font-semibold text-slate-100">Get started</h2>
          <ol className="space-y-2 text-sm">
            <Step done={true} text="Seed defaults (Settings → Seed defaults)" to="/settings" label="Open settings" />
            <Step
              done={data.providers_enabled > 0}
              text="Add providers (1 LLM + 1 image + 1 voice)"
              to="/providers"
              label="Add providers"
            />
            <Step
              done={data.projects_total > 0}
              text="Create a project (your channel/niche)"
              to="/projects"
              label="Create project"
            />
            <Step done={data.videos_total > 0} text="Generate your first video" to="/create" label="Create video" />
          </ol>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Total videos" value={data.videos_total} accent="brand" />
        <StatCard label="Processing" value={find("running")} sub="in pipeline" accent="amber" />
        <StatCard label="Completed" value={find("completed")} accent="emerald" />
        <StatCard label="Failed" value={find("failed")} accent="rose" />
        <StatCard label="Queue depth" value={data.queue_depth} sub="pending jobs" accent="violet" />
        <StatCard label="Providers enabled" value={data.providers_enabled} accent="brand" />
        <StatCard label="Projects" value={data.projects_total} accent="emerald" />
        <StatCard label="Waiting approval" value={find("waiting_approval")} accent="violet" />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="mb-4 text-sm font-semibold text-slate-200">Videos by status</h2>
          <div className="h-64">
            {byStatus.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-600">
                No videos yet.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={byStatus}>
                  <XAxis dataKey="name" stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="#64748b" fontSize={12} allowDecimals={false} tickLine={false} axisLine={false} />
                  <Tooltip
                    cursor={{ fill: "rgba(148,163,184,0.06)" }}
                    contentStyle={{
                      background: "#0d1526",
                      border: "1px solid rgba(255,255,255,0.1)",
                      borderRadius: "0.75rem",
                    }}
                    labelStyle={{ color: "#e2e8f0" }}
                  />
                  <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                    {byStatus.map((entry) => (
                      <Cell key={entry.status} fill={STATUS_COLORS[entry.status] ?? "#3b82f6"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>

        <Card>
          <h2 className="mb-4 text-sm font-semibold text-slate-200">Estimated cost</h2>
          <div className="spec-box divide-y divide-white/5">
            <CostRow label="Today" value={data.cost_today} />
            <CostRow label="This week" value={data.cost_week} />
            <CostRow label="This month" value={data.cost_month} />
            <CostRow label="All time" value={data.cost_total} highlight />
          </div>
          <p className="mt-4 text-xs text-slate-500">
            Providers enabled: {providers.data?.filter((p) => p.enabled).length ?? 0}
          </p>
        </Card>
      </div>

      <div className="mt-6">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Recent videos</h2>
        {(recent.data ?? []).length === 0 ? (
          <EmptyState
            title="No videos yet"
            hint="Create your first short — pick a project, enter an idea, and the agents handle the rest."
            action={<Link to="/create"><Button>Create video</Button></Link>}
          />
        ) : (
          <div className="space-y-2.5">
            {recent.data!.slice(0, 6).map((v) => (
              <Link key={v.id} to={`/videos/${v.id}`} className="block">
                <Card interactive className="flex items-center justify-between">
                  <div>
                    <div className="font-semibold text-slate-100">{v.title || v.topic || v.idea || "Untitled"}</div>
                    <div className="mt-0.5 font-mono text-xs text-slate-500">stage: {v.current_stage}</div>
                  </div>
                  <StatusBadge status={v.status} />
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Step({ done, text, to, label }: { done: boolean; text: string; to: string; label: string }) {
  return (
    <li className="flex items-center justify-between">
      <span className="flex items-center gap-2">
        <span
          className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] ${
            done ? "bg-emerald-500 text-white" : "border border-slate-600 text-slate-500"
          }`}
        >
          {done ? "✓" : ""}
        </span>
        <span className={done ? "text-slate-500 line-through" : "text-slate-200"}>{text}</span>
      </span>
      {!done && (
        <Link to={to} className="text-xs font-semibold text-brand-400 hover:underline">{label} →</Link>
      )}
    </li>
  );
}

function CostRow({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div className="spec-row">
      <span className="spec-key">{label}</span>
      <span className={highlight ? "font-mono text-base font-bold text-emerald-400" : "font-mono text-xs font-semibold text-slate-100"}>
        ${value.toFixed(2)}
      </span>
    </div>
  );
}
