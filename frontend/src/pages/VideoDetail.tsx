import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { LogEntry, VideoDetail as VideoDetailT, VideoProgress } from "@/api/types";
import { Button, Card, PageHeader, StatusBadge } from "@/components/ui";

export default function VideoDetail() {
  const { id = "" } = useParams();
  const qc = useQueryClient();

  const video = useQuery({
    queryKey: ["video", id],
    queryFn: () => api.get<VideoDetailT>(`/videos/${id}`),
    refetchInterval: 4000,
  });
  const progress = useQuery({
    queryKey: ["video-progress", id],
    queryFn: () => api.get<VideoProgress>(`/videos/${id}/progress`),
    refetchInterval: 3000,
  });
  const logs = useQuery({
    queryKey: ["video-logs", id],
    queryFn: () => api.get<LogEntry[]>(`/videos/${id}/logs`),
    refetchInterval: 3000,
  });

  const run = useMutation({
    mutationFn: () => api.post(`/videos/${id}/run`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["video", id] }),
  });
  const approve = useMutation({
    mutationFn: () => api.post(`/videos/${id}/approve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["video", id] }),
  });

  if (video.isLoading) return <p className="text-slate-400">Loading…</p>;
  const v = video.data;
  if (!v) return <p className="text-rose-400">Not found.</p>;

  return (
    <div>
      <PageHeader
        title={v.title || v.topic || "Video"}
        action={
          <div className="flex items-center gap-2">
            <StatusBadge status={v.status} />
            {v.status === "waiting_approval" && (
              <Button onClick={() => approve.mutate()}>Approve &amp; continue</Button>
            )}
            {["failed", "cancelled", "pending"].includes(v.status) && (
              <Button variant="ghost" onClick={() => run.mutate()}>Run</Button>
            )}
          </div>
        }
      />

      {v.error && (
        <Card className="mb-4 border-rose-500/40 bg-rose-500/5 font-mono text-xs text-rose-300">{v.error}</Card>
      )}

      <Card className="mb-6">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Pipeline</h2>
        <div className="flex flex-wrap gap-2">
          {progress.data?.stages.map((s) => (
            <div key={s.stage} className="flex flex-col items-center gap-1">
              <StatusBadge status={s.status} />
              <span className="text-[10px] uppercase tracking-wide text-slate-500">{s.stage}</span>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Script</h2>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">
            {v.script?.content || "—"}
          </p>
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Logs</h2>
          <div className="max-h-80 space-y-1 overflow-y-auto font-mono text-xs">
            {logs.data?.map((l) => (
              <div key={l.id} className="text-slate-400">
                <span className="text-slate-600">
                  [{new Date(l.created_at).toLocaleTimeString()}]
                </span>{" "}
                <span className={l.level === "error" ? "text-rose-400" : l.level === "warning" ? "text-amber-400" : ""}>
                  {l.stage || l.agent}: {l.message}
                </span>
              </div>
            ))}
            {logs.data?.length === 0 && <span className="text-slate-600">No logs yet.</span>}
          </div>
        </Card>
      </div>

      <Card className="mt-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Scenes ({v.scenes.length})</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {v.scenes.map((s) => (
            <div key={s.id} className="rounded-xl border border-white/10 bg-inset/50 p-3.5 transition hover:border-brand-500/40">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs font-semibold text-brand-300">Scene {s.index}</span>
                <span className="font-mono text-xs text-slate-500">{s.duration}s</span>
              </div>
              <p className="mt-1 text-sm text-slate-300">{s.narration}</p>
              <p className="mt-2 text-xs text-slate-500">{s.visual_prompt}</p>
              {s.camera && (
                <p className="mt-1 text-[10px] text-slate-600">
                  {String((s.camera as Record<string, unknown>).shot ?? "")}{" "}
                  {String((s.camera as Record<string, unknown>).movement ?? "")}
                </p>
              )}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
