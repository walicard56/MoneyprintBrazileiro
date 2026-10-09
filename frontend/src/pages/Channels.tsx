import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Project, StyleProfile, Video } from "@/api/types";
import { Button, Card, EmptyState, Field, Input, PageHeader, Tag } from "@/components/ui";
import { pt } from "@/i18n/ptBR";

function hashHue(seed: string): number {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash << 5) - hash + seed.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash) % 360;
}

function styleBullets(profile: StyleProfile | undefined): string[] {
  if (!profile) return [];
  const items: string[] = [];
  for (const section of Object.values(profile.profile ?? {})) {
    if (!section || typeof section !== "object" || Array.isArray(section)) continue;
    for (const item of Object.values(section as Record<string, { value?: unknown; accepted?: boolean }>)) {
      if (!item || typeof item !== "object" || !("value" in item)) continue;
      if (item.accepted === false) continue;
      const value = (item as { value?: unknown }).value;
      if (value == null || value === "") continue;
      items.push(Array.isArray(value) ? value.join(", ") : String(value));
      if (items.length >= 4) return items;
    }
  }
  return items;
}

function ChannelCard({ project }: { project: Project }) {
  const hue = hashHue(project.name);
  const profiles = useQuery({
    queryKey: ["style-profiles", project.id],
    queryFn: () => api.get<StyleProfile[]>(`/projects/${project.id}/style-profiles`),
  });
  const videos = useQuery({
    queryKey: ["videos", project.id],
    queryFn: () => api.get<Video[]>(`/videos?project_id=${project.id}`),
  });

  const active = profiles.data?.find((p) => p.status === "active");
  const bullets = styleBullets(active);
  const latestVideo = videos.data?.[0];

  return (
    <Link to={`/canais/${project.id}`}>
      <Card interactive className="h-full">
        <div className="flex items-start gap-3">
          <div
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-sm font-bold text-white"
            style={{
              background: `linear-gradient(135deg, hsl(${hue} 72% 55%), hsl(${(hue + 45) % 360} 72% 45%))`,
            }}
          >
            {project.name.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0">
            <div className="truncate font-semibold text-slate-100">{project.name}</div>
            <div className="truncate text-xs text-slate-500">
              {project.niche || "sem nicho"} · {project.language}
            </div>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span>{pt.channels.videosCount(videos.data?.length ?? 0)}</span>
          {active && (
            <>
              <span>·</span>
              <span>{pt.channels.defaultVersion(active.version)}</span>
            </>
          )}
          {latestVideo && (
            <>
              <span>·</span>
              <span className="truncate">{pt.channels.lastVideo(latestVideo.title || latestVideo.idea)}</span>
            </>
          )}
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {bullets.length > 0 ? (
            bullets.map((b, i) => (
              <Tag key={i} color="brand">
                {b}
              </Tag>
            ))
          ) : (
            <span className="text-xs text-slate-500">{pt.channels.noStyleYet}</span>
          )}
        </div>
      </Card>
    </Link>
  );
}

export default function Channels() {
  const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", niche: "", language: "Portuguese" });

  const create = useMutation({
    mutationFn: () => api.post<Project>("/projects", form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      setForm({ name: "", niche: "", language: "Portuguese" });
      setCreating(false);
    },
  });

  return (
    <div>
      <PageHeader
        eyebrow={pt.channels.eyebrow}
        title={pt.channels.title}
        subtitle={pt.channels.subtitle}
        action={<Button onClick={() => setCreating((v) => !v)}>{pt.channels.newChannel}</Button>}
      />

      {creating && (
        <Card className="mb-6">
          <h2 className="mb-4 text-sm font-semibold text-slate-200">{pt.channels.newChannelFormTitle}</h2>
          <form
            className="grid grid-cols-1 gap-3 md:grid-cols-3"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <Field label="Nome">
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </Field>
            <Field label="Nicho">
              <Input value={form.niche} onChange={(e) => setForm({ ...form, niche: e.target.value })} />
            </Field>
            <Field label="Idioma">
              <Input value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })} />
            </Field>
            <div className="flex items-end gap-2 md:col-span-3">
              <Button type="submit" disabled={!form.name || create.isPending}>
                {pt.common.create}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
                {pt.common.cancel}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {projects.data && projects.data.length === 0 && (
        <EmptyState title={pt.channels.empty.title} hint={pt.channels.empty.hint} />
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {projects.data?.map((p) => <ChannelCard key={p.id} project={p} />)}
      </div>
    </div>
  );
}
