import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Project, Video } from "@/api/types";
import { Button, Card, Field, Input, PageHeader, StatusBadge, Tag } from "@/components/ui";

export default function Videos() {
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const projectFromUrl = params.get("project") ?? "";

  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  const [projectId, setProjectId] = useState(projectFromUrl);

  const videos = useQuery({
    queryKey: ["videos", projectId],
    queryFn: () =>
      api.get<Video[]>(`/videos${projectId ? `?project_id=${projectId}` : ""}`),
    refetchInterval: 4000,
  });

  const [idea, setIdea] = useState("");
  const [batchCount, setBatchCount] = useState(0);

  const createOne = useMutation({
    mutationFn: () =>
      api.post<Video>(`/projects/${projectId}/videos`, { idea, topic: idea, autostart: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["videos"] });
      setIdea("");
    },
  });

  const createBatch = useMutation({
    mutationFn: () =>
      api.post<Video[]>(`/projects/${projectId}/videos/batch`, {
        count: batchCount,
        autostart: true,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["videos"] }),
  });

  return (
    <div>
      <PageHeader
        eyebrow="Your render queue"
        title={<>Videos</>}
        subtitle="Every short you've generated, with live pipeline status."
      />

      <Card className="mb-6">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <Field label="Project">
            <select
              className="w-full rounded-lg border border-white/10 bg-inset/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/25"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            >
              <option value="" className="bg-panel">All projects</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id} className="bg-panel">{p.name}</option>
              ))}
            </select>
          </Field>
          <div className="md:col-span-2">
            <Field label="New video idea / topic">
              <Input value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="e.g. Why the ocean is blue" />
            </Field>
          </div>
          <div className="flex items-end">
            <Button disabled={!projectId || !idea || createOne.isPending} onClick={() => createOne.mutate()}>
              Generate
            </Button>
          </div>
        </div>
        <div className="mt-3 flex items-end gap-3">
          <div className="w-40">
            <Field label="Batch count">
              <Input type="number" value={batchCount} onChange={(e) => setBatchCount(Number(e.target.value))} />
            </Field>
          </div>
          <Button
            variant="ghost"
            disabled={!projectId || batchCount < 1 || createBatch.isPending}
            onClick={() => createBatch.mutate()}
          >
            Generate {batchCount || ""} in batch
          </Button>
        </div>
      </Card>

      <div className="space-y-2.5">
        {videos.data?.map((v) => (
          <Link key={v.id} to={`/videos/${v.id}`} className="block">
            <Card interactive className="flex items-center justify-between">
              <div>
                <div className="font-semibold text-slate-100">{v.title || v.topic || v.idea || "Untitled"}</div>
                <div className="mt-0.5 font-mono text-xs text-slate-500">stage: {v.current_stage} · {v.mode}</div>
              </div>
              <div className="flex items-center gap-2">
                {v.config?.originality_warning != null && <Tag color="amber">low originality</Tag>}
                {v.config?.variation_hint != null && <Tag color="violet">low variation</Tag>}
                <StatusBadge status={v.status} />
              </div>
            </Card>
          </Link>
        ))}
        {videos.data?.length === 0 && <p className="text-sm text-slate-500">No videos yet.</p>}
      </div>
    </div>
  );
}
