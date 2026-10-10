import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type {
  Account,
  ChannelGrammar,
  DirectionStatus,
  EditorialDirection,
  LabScene,
  Project,
  ProductionDefaults,
  ReferenceSource,
  ReferenceVideo,
  StyleProfile,
  StyleProfileItem,
  Video,
  VideoLabRun,
} from "@/api/types";
import {
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Select,
  StatusBadge,
  Tag,
  Textarea,
  Toggle,
} from "@/components/ui";
import { Modal, ModalHeader } from "@/components/Modal";
import { formatAge, formatCompactViews, pt } from "@/i18n/ptBR";

const IN_PROGRESS = new Set(["pending", "fetching", "analyzing"]);
const DEEPDIVE_IN_PROGRESS = new Set(["pending", "running"]);

function useProject(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.get<Project>(`/projects/${projectId}`),
  });
}

/* --------------------------------------------------------------- Referências */

function ReferenceVideoRow({ video }: { video: ReferenceVideo }) {
  const [expanded, setExpanded] = useState(false);
  const roleLabel = pt.references.roleLabels[video.role];
  const deepdiveLabel = pt.references.deepdiveLabels[video.deepdive_status];
  const hasDeepdiveResults =
    video.deepdive_status === "ready" &&
    (video.attention_notes.length > 0 || video.scene_breakdown.length > 0);

  return (
    <div className="border-b border-white/5 py-2.5 last:border-0">
      <div className="flex flex-wrap items-center gap-3">
        {video.thumbnail_url && (
          <img src={video.thumbnail_url} alt="" className="h-10 w-16 shrink-0 rounded-md object-cover" />
        )}
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm text-slate-200">{video.title}</div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span>{formatCompactViews(video.views)} views</span>
            {video.outlier_score != null && (
              <span>· {pt.references.outlierMultiplier(video.outlier_score)}</span>
            )}
            {video.views_per_day != null && <span>· {pt.references.viewsPerDay(video.views_per_day)}</span>}
            {video.published_at && <span>· {formatAge(video.published_at)}</span>}
            {roleLabel && <Tag color={video.role === "top" ? "emerald" : video.role === "bottom" ? "amber" : "slate"}>{roleLabel}</Tag>}
            {video.transcript_status === "fetched" && <Tag color="violet">{pt.references.transcriptSaved}</Tag>}
            {deepdiveLabel && (
              <Tag color={video.deepdive_status === "ready" ? "violet" : video.deepdive_status === "failed" ? "amber" : "brand"}>
                {deepdiveLabel}
              </Tag>
            )}
          </div>
          {video.deepdive_status === "failed" && video.deepdive_error && (
            <p className="mt-1 text-xs text-rose-400">{video.deepdive_error}</p>
          )}
        </div>
        {hasDeepdiveResults && (
          <Button variant="ghost" onClick={() => setExpanded((v) => !v)}>
            {expanded ? pt.common.hide : pt.references.attentionNotesTitle}
          </Button>
        )}
      </div>

      {expanded && hasDeepdiveResults && (
        <div className="mt-2 ml-[76px] space-y-2">
          {video.attention_notes.length > 0 && (
            <div>
              <p className="text-xs text-slate-500">{pt.references.attentionNotesHint}</p>
              <ul className="mt-1 list-inside list-disc text-sm text-slate-300">
                {video.attention_notes.map((note, i) => (
                  <li key={i}>{note}</li>
                ))}
              </ul>
            </div>
          )}
          {video.scene_breakdown.length > 0 && (
            <div>
              <h5 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                {pt.references.sceneBreakdownTitle}
              </h5>
              <div className="flex flex-wrap gap-1.5">
                {video.scene_breakdown.map((scene) => (
                  <span
                    key={scene.index}
                    title={(scene.vision?.mood as string) || ""}
                    className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[10px] text-slate-400"
                  >
                    {scene.start_s.toFixed(0)}s
                    {scene.beat_role && (
                      <> · {pt.lab.beatLabels[scene.beat_role as keyof typeof pt.lab.beatLabels] ?? scene.beat_role}</>
                    )}
                    {scene.has_caption && " · CC"}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ReferenceCard({ source }: { source: ReferenceSource }) {
  const videos = useQuery({
    queryKey: ["reference-videos", source.id],
    queryFn: () => api.get<ReferenceVideo[]>(`/references/${source.id}/videos`),
    enabled: source.status === "ready",
    refetchInterval: (query) => {
      const data = query.state.data as ReferenceVideo[] | undefined;
      return data?.some((v) => DEEPDIVE_IN_PROGRESS.has(v.deepdive_status)) ? 3000 : false;
    },
  });

  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Tag color="brand">{source.kind === "video" ? pt.references.kindVideo : pt.references.kindChannel}</Tag>
            <span className="truncate font-medium text-slate-100">{source.title || source.url}</span>
          </div>
          <div className="mt-1 truncate text-xs text-slate-500">{source.url}</div>
        </div>
        <StatusBadge status={source.status} />
      </div>

      {IN_PROGRESS.has(source.status) && (
        <div className="mt-3">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/5">
            <div
              className="h-full rounded-full bg-gradient-to-r from-brand-500 to-violet-500 transition-all"
              style={{ width: `${source.progress}%` }}
            />
          </div>
          <div className="mt-1 text-xs text-slate-500">
            {pt.references.statusLabels[source.status]} · {source.progress}%
          </div>
        </div>
      )}

      {source.status === "failed" && <p className="mt-2 text-xs text-rose-400">{source.error}</p>}

      {source.kind === "channel" && source.stats?.n_videos != null && (
        <div className="mt-3 flex gap-3 text-xs text-slate-500">
          <span>{pt.references.statsCount(source.stats.n_videos)}</span>
          {source.stats.median_views != null && <span>{pt.references.statsMedian(source.stats.median_views)}</span>}
        </div>
      )}

      {source.status === "ready" && videos.data && videos.data.length > 0 && (
        <div className="mt-4 border-t border-white/10 pt-3">
          {videos.data.map((v) => (
            <ReferenceVideoRow key={v.id} video={v} />
          ))}
        </div>
      )}
    </Card>
  );
}

function ReferencesTab({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [urls, setUrls] = useState("");

  const sources = useQuery({
    queryKey: ["references", projectId],
    queryFn: () => api.get<ReferenceSource[]>(`/references?project_id=${projectId}`),
    refetchInterval: (query) => {
      const data = query.state.data as ReferenceSource[] | undefined;
      return data?.some((s) => IN_PROGRESS.has(s.status)) ? 2000 : false;
    },
  });

  const submit = useMutation({
    mutationFn: () =>
      api.post<ReferenceSource[]>("/references", {
        urls: urls.split("\n").map((u) => u.trim()).filter(Boolean),
        project_id: projectId,
      }),
    onSuccess: () => {
      setUrls("");
      qc.invalidateQueries({ queryKey: ["references", projectId] });
    },
  });

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="text-sm font-semibold text-slate-100">{pt.references.boxTitle}</h3>
        <p className="mt-1 text-xs text-slate-500">{pt.references.boxHint}</p>
        <p className="mt-2 text-xs text-brand-300">{pt.references.principle}</p>
        <form
          className="mt-3 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            submit.mutate();
          }}
        >
          <Textarea
            rows={3}
            placeholder={pt.references.placeholder}
            value={urls}
            onChange={(e) => setUrls(e.target.value)}
          />
          {submit.isError && <p className="text-xs text-rose-400">{(submit.error as Error).message}</p>}
          <Button type="submit" disabled={!urls.trim() || submit.isPending}>
            {submit.isPending ? pt.references.submitting : pt.references.submit}
          </Button>
        </form>
      </Card>

      {sources.data && sources.data.length === 0 && (
        <EmptyState title={pt.references.empty.title} hint={pt.references.empty.hint} />
      )}

      <div className="space-y-3">
        {sources.data?.map((s) => <ReferenceCard key={s.id} source={s} />)}
      </div>

      <LabPanel projectId={projectId} />
    </div>
  );
}

/* --------------------------------------------------------- Laboratório de vídeo */

const IN_PROGRESS_LAB = new Set(["pending", "running"]);

function LabPanel({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [runId, setRunId] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const upload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.set("file", file);
      body.set("project_id", projectId);
      return api.postForm<VideoLabRun>("/lab/runs", body);
    },
    onSuccess: (run) => setRunId(run.id),
  });

  const run = useQuery({
    queryKey: ["lab-run", runId],
    queryFn: () => api.get<VideoLabRun>(`/lab/runs/${runId}`),
    enabled: !!runId,
    refetchInterval: (query) => {
      const data = query.state.data as VideoLabRun | undefined;
      return data && IN_PROGRESS_LAB.has(data.status) ? 1500 : false;
    },
  });

  const scenes = useQuery({
    queryKey: ["lab-scenes", runId],
    queryFn: () => api.get<LabScene[]>(`/lab/runs/${runId}/scenes`),
    enabled: !!runId && run.data?.status === "ready",
  });

  const channelGrammar = useQuery({
    queryKey: ["channel-grammar", projectId],
    queryFn: () => api.get<ChannelGrammar>(`/projects/${projectId}/grammar`),
    retry: false,
  });

  const removeRun = useMutation({
    mutationFn: () => api.del(`/lab/runs/${runId}`),
    onSuccess: () => {
      setRunId(null);
      qc.invalidateQueries({ queryKey: ["channel-grammar", projectId] });
    },
  });

  function onFile(file: File | undefined | null) {
    if (file) upload.mutate(file);
  }

  const totalDuration = scenes.data?.reduce((sum, s) => sum + s.duration_s, 0) || 1;
  const grammar = channelGrammar.data?.grammar;

  return (
    <Card>
      <h3 className="text-sm font-semibold text-slate-100">{pt.lab.title}</h3>
      <p className="mt-1 text-xs text-slate-500">{pt.lab.hint}</p>
      <p className="mt-2 text-xs text-amber-400">{pt.lab.disclaimer}</p>

      {!runId && (
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            onFile(e.dataTransfer.files?.[0]);
          }}
          className={`mt-3 flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 text-center text-xs text-slate-500 transition ${
            dragOver ? "border-brand-500 bg-brand-500/5" : "border-white/10"
          }`}
        >
          {upload.isPending ? pt.lab.uploading : pt.lab.dropHint}
          <input
            type="file"
            accept="video/*"
            className="hidden"
            onChange={(e) => onFile(e.target.files?.[0])}
            disabled={upload.isPending}
          />
        </label>
      )}
      {upload.isError && <p className="mt-2 text-xs text-rose-400">{(upload.error as Error).message}</p>}

      {runId && run.data && (
        <div className="mt-4">
          <div className="flex items-center justify-between">
            <Tag color={run.data.status === "ready" ? "emerald" : run.data.status === "failed" ? "amber" : "brand"}>
              {pt.lab.statusLabels[run.data.status]}
            </Tag>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => setRunId(null)}>
                {pt.common.cancel}
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  if (confirm(pt.lab.removeConfirm)) removeRun.mutate();
                }}
              >
                {pt.lab.remove}
              </Button>
            </div>
          </div>

          {IN_PROGRESS_LAB.has(run.data.status) && (
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/5">
              <div
                className="h-full rounded-full bg-gradient-to-r from-brand-500 to-violet-500 transition-all"
                style={{ width: `${run.data.progress}%` }}
              />
            </div>
          )}
          {run.data.status === "failed" && (
            <p className="mt-2 text-xs text-rose-400">{run.data.error || pt.lab.error}</p>
          )}

          {run.data.status === "ready" && scenes.data && scenes.data.length > 0 && (
            <div className="mt-4 space-y-4">
              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {pt.lab.scenesTitle}
                </h4>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 md:grid-cols-6">
                  {scenes.data.map((scene) => (
                    <div key={scene.id} className="overflow-hidden rounded-lg border border-white/10 bg-white/5">
                      <img
                        src={`/api/v1/lab/runs/${runId}/scenes/${scene.index}/thumb`}
                        alt=""
                        className="aspect-video w-full object-cover"
                      />
                      <div className="p-1.5 text-[10px] text-slate-400">
                        <div className="flex items-center justify-between">
                          <span>{scene.duration_s.toFixed(1)}s</span>
                          <span className="flex gap-1">
                            {(scene.fade_in || scene.fade_out) && <span title={pt.lab.fadeIcon}>〜</span>}
                            {scene.has_caption && <span title={pt.lab.captionIcon}>CC</span>}
                          </span>
                        </div>
                        {scene.beat_role && (
                          <Tag color="violet">
                            {pt.lab.beatLabels[scene.beat_role as keyof typeof pt.lab.beatLabels] ?? scene.beat_role}
                          </Tag>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {pt.lab.rhythmTitle}
                </h4>
                <div className="flex h-6 w-full overflow-hidden rounded-full bg-white/5">
                  {scenes.data.map((scene) => (
                    <div
                      key={scene.id}
                      title={`${pt.lab.beatLabels[scene.beat_role as keyof typeof pt.lab.beatLabels] ?? scene.beat_role} · ${scene.duration_s.toFixed(1)}s`}
                      className="h-full border-r border-night/50 bg-gradient-to-b from-brand-500/70 to-violet-500/70"
                      style={{ width: `${(scene.duration_s / totalDuration) * 100}%` }}
                    />
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {grammar && channelGrammar.data && (
        <div className="mt-4 border-t border-white/10 pt-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            {pt.lab.channelGrammarTitle} — {pt.lab.measuredIn(channelGrammar.data.videos_analyzed)}
          </h4>
          <div className="flex flex-wrap gap-3 text-xs text-slate-400">
            {grammar.scene_duration_median_s?.value != null && (
              <span>corte mediano: {grammar.scene_duration_median_s.value.toFixed(1)}s</span>
            )}
            {grammar.avg_wpm?.value != null && <span>{Math.round(grammar.avg_wpm.value)} palavras/min</span>}
            {grammar.loudness_lufs?.value != null && (
              <span>{grammar.loudness_lufs.value.toFixed(1)} LUFS</span>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

function ProductionDefaultsCard({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [saved, setSaved] = useState(false);

  const defaults = useQuery({
    queryKey: ["production-defaults", projectId],
    queryFn: () => api.get<ProductionDefaults>(`/projects/${projectId}/production-defaults`),
  });

  const [form, setForm] = useState<ProductionDefaults>({});
  const current = { ...defaults.data, ...form };

  const save = useMutation({
    mutationFn: () => api.patch<ProductionDefaults>(`/projects/${projectId}/production-defaults`, form),
    onSuccess: (data) => {
      qc.setQueryData(["production-defaults", projectId], data);
      setForm({});
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    },
  });

  function set<K extends keyof ProductionDefaults>(key: K, value: ProductionDefaults[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  return (
    <Card>
      <h3 className="text-sm font-semibold text-slate-100">{pt.production.title}</h3>
      <p className="mt-1 text-xs text-slate-500">{pt.production.hint}</p>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label={pt.production.tone}>
          <Input value={current.tone ?? ""} onChange={(e) => set("tone", e.target.value)} placeholder="casual, dramático…" />
        </Field>
        <Field label={pt.production.voice}>
          <Input value={current.voice ?? ""} onChange={(e) => set("voice", e.target.value)} placeholder="pt-BR-FranciscaNeural" />
        </Field>
        <Field label={pt.production.aspect}>
          <Select
            value={current.aspect_ratio ?? "9:16"}
            onChange={(v) => set("aspect_ratio", v)}
            options={Object.entries(pt.production.aspectOptions).map(([value, label]) => ({ value, label }))}
          />
        </Field>
        <div className="flex flex-col gap-3 pt-6">
          <Toggle
            checked={current.subtitles_enabled ?? true}
            onChange={(v) => set("subtitles_enabled", v)}
            label={pt.production.subtitlesEnabled}
          />
          <Toggle
            checked={current.music_enabled ?? true}
            onChange={(v) => set("music_enabled", v)}
            label={pt.production.musicEnabled}
          />
        </div>
      </div>

      <div className="mt-4">
        <Button onClick={() => save.mutate()} disabled={save.isPending || Object.keys(form).length === 0}>
          {saved ? pt.production.saved : pt.production.save}
        </Button>
      </div>
    </Card>
  );
}

/* -------------------------------------------------------------------- Estilo */

function StyleItemRow({
  path,
  item,
  onToggle,
  onMissingData,
}: {
  path: string;
  item: StyleProfileItem;
  onToggle: (path: string, accepted: boolean) => void;
  onMissingData: () => void;
}) {
  if (item.value == null) {
    return (
      <div className="flex items-start justify-between gap-3 border-b border-white/5 py-2.5 last:border-0">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Tag color="slate">{pt.style.missingData}</Tag>
            {item.why && <span className="text-xs text-slate-500">{item.why}</span>}
          </div>
          <div className="mt-0.5 text-xs text-slate-500">{pt.style.missingDataHint}</div>
        </div>
        <Button variant="ghost" onClick={onMissingData}>
          {pt.style.sendVideoToMeasure}
        </Button>
      </div>
    );
  }

  const value = Array.isArray(item.value) ? item.value.join(", ") : String(item.value);
  return (
    <div className="flex items-start gap-3 border-b border-white/5 py-2.5 last:border-0">
      <input
        type="checkbox"
        checked={item.accepted}
        onChange={(e) => onToggle(path, e.target.checked)}
        className="mt-1 h-4 w-4 rounded border-white/20 bg-inset accent-brand-500"
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-slate-200">{value}</span>
          <Tag color={item.confidence === "high" ? "emerald" : item.confidence === "medium" ? "brand" : "slate"}>
            {pt.style.confidenceLabels[item.confidence]}
          </Tag>
        </div>
        {item.why && <div className="mt-0.5 text-xs text-slate-500">{pt.style.whyPrefix}{item.why}</div>}
      </div>
    </div>
  );
}

function CreateChannelModal({ profileId, onClose }: { profileId: string; onClose: () => void }) {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [niche, setNiche] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.post<StyleProfile>(`/style-profiles/${profileId}/create-channel`, { name, niche }),
    onSuccess: (profile) => navigate(`/canais/${profile.project_id}`),
  });

  return (
    <Modal onClose={onClose}>
      <ModalHeader title={pt.style.createChannelWithStyle} onClose={onClose} />
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Nome do novo canal">
          <Input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
        </Field>
        <Field label="Nicho">
          <Input value={niche} onChange={(e) => setNiche(e.target.value)} />
        </Field>
        <div className="flex gap-2 pt-2">
          <Button type="submit" disabled={!name || create.isPending}>
            {pt.common.create}
          </Button>
          <Button type="button" variant="ghost" onClick={onClose}>
            {pt.common.cancel}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function StyleTab({ projectId, onGoToReferences }: { projectId: string; onGoToReferences: () => void }) {
  const qc = useQueryClient();
  const [creatingChannel, setCreatingChannel] = useState(false);

  const profiles = useQuery({
    queryKey: ["style-profiles", projectId],
    queryFn: () => api.get<StyleProfile[]>(`/projects/${projectId}/style-profiles`),
  });

  const featured = profiles.data?.find((p) => p.status === "draft") ?? profiles.data?.[0];

  const patch = useMutation({
    mutationFn: (profile: Record<string, unknown>) =>
      api.patch<StyleProfile>(`/style-profiles/${featured!.id}`, { profile }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["style-profiles", projectId] }),
  });

  const activate = useMutation({
    mutationFn: () => api.post<StyleProfile>(`/style-profiles/${featured!.id}/activate`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["style-profiles", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });

  function toggleItem(path: string, accepted: boolean) {
    if (!featured) return;
    const [section, key] = path.split(".");
    const profile = JSON.parse(JSON.stringify(featured.profile)) as Record<string, Record<string, StyleProfileItem>>;
    if (profile[section]?.[key]) {
      profile[section][key] = { ...profile[section][key], accepted };
      patch.mutate(profile);
    }
  }

  if (profiles.data && profiles.data.length === 0) {
    return <EmptyState title={pt.style.empty.title} hint={pt.style.empty.hint} />;
  }

  const sections = Object.keys(pt.style.sections) as (keyof typeof pt.style.sections)[];

  return (
    <div className="space-y-4">
      <ProductionDefaultsCard projectId={projectId} />

      {featured && (
        <Card>
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-100">{pt.style.learnedTitle}</h3>
            <Tag color={featured.status === "active" ? "emerald" : featured.status === "draft" ? "brand" : "slate"}>
              v{featured.version} · {pt.style[featured.status as "draft" | "active" | "archived"]}
            </Tag>
          </div>

          {sections.map((section) => {
            const items = featured.profile?.[section as keyof typeof featured.profile] as
              | Record<string, StyleProfileItem>
              | undefined;
            if (!items || Object.keys(items).length === 0) return null;
            return (
              <div key={section} className="mt-4">
                <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {pt.style.sections[section]}
                </h4>
                {Object.entries(items).map(([key, item]) => (
                  <StyleItemRow
                    key={key}
                    path={`${section}.${key}`}
                    item={item}
                    onToggle={toggleItem}
                    onMissingData={onGoToReferences}
                  />
                ))}
              </div>
            );
          })}

          {featured.profile?.nao_replicavel && featured.profile.nao_replicavel.length > 0 && (
            <div className="mt-4 border-t border-white/10 pt-3">
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                {pt.style.notReplicableTitle}
              </h4>
              <ul className="list-inside list-disc text-sm text-slate-400">
                {featured.profile.nao_replicavel.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-4 flex gap-2 border-t border-white/10 pt-4">
            <Button onClick={() => activate.mutate()} disabled={activate.isPending || featured.status === "active"}>
              {pt.style.useOnChannel}
            </Button>
            <Button variant="ghost" onClick={() => setCreatingChannel(true)}>
              {pt.style.createChannelWithStyle}
            </Button>
          </div>
        </Card>
      )}

      {profiles.data && profiles.data.length > 1 && (
        <Card>
          <h3 className="mb-2 text-sm font-semibold text-slate-100">{pt.style.versionHistory}</h3>
          <p className="mb-3 text-xs text-slate-500">{pt.style.versionNote}</p>
          <div className="space-y-1">
            {profiles.data.map((p) => (
              <div key={p.id} className="flex items-center gap-2 text-sm text-slate-300">
                <span className="font-mono text-xs text-slate-500">v{p.version}</span>
                <Tag color={p.status === "active" ? "emerald" : p.status === "draft" ? "brand" : "slate"}>
                  {pt.style[p.status as "draft" | "active" | "archived"]}
                </Tag>
              </div>
            ))}
          </div>
        </Card>
      )}

      {creatingChannel && featured && (
        <CreateChannelModal profileId={featured.id} onClose={() => setCreatingChannel(false)} />
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- Direções */

function DirectionCard({ direction, index }: { direction: EditorialDirection; index: number }) {
  const qc = useQueryClient();
  const navigate = useNavigate();

  const setStatus = useMutation({
    mutationFn: (status: DirectionStatus) =>
      api.post<EditorialDirection>(`/directions/${direction.id}/${status === "used" ? "use" : "dismiss"}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["directions", direction.project_id] }),
  });

  return (
    <Card className={direction.status === "dismissed" ? "opacity-50" : ""}>
      <div className="flex items-center justify-between">
        <Tag color="violet">{pt.directions.directionLabel(index + 1)}</Tag>
        {direction.status !== "new" && <Tag color={direction.status === "used" ? "emerald" : "slate"}>{direction.status}</Tag>}
      </div>
      <h3 className="mt-2 font-semibold text-slate-100">{direction.title}</h3>
      <p className="mt-1 text-sm text-slate-400">{direction.why}</p>
      {direction.approach && (
        <p className="mt-2 text-xs text-slate-500">
          <span className="font-semibold text-slate-400">{pt.directions.approach}: </span>
          {direction.approach}
        </p>
      )}
      {direction.evidence?.url && (
        <a
          href={direction.evidence.url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-block text-xs text-brand-300 hover:underline"
        >
          {pt.directions.source}
          {direction.evidence.views != null ? ` · ${formatCompactViews(direction.evidence.views)} views` : ""}
        </a>
      )}
      {direction.status === "new" && (
        <div className="mt-3 flex gap-2">
          <Button
            variant="ghost"
            onClick={() => {
              setStatus.mutate("used");
              navigate(`/create?topic=${encodeURIComponent(direction.title)}`);
            }}
          >
            {pt.directions.use}
          </Button>
          <Button variant="ghost" onClick={() => setStatus.mutate("dismissed")}>
            {pt.directions.dismiss}
          </Button>
        </div>
      )}
    </Card>
  );
}

function DirectionsTab({ projectId, niche }: { projectId: string; niche: string }) {
  const qc = useQueryClient();
  const [nicheInput, setNicheInput] = useState(niche);

  const directions = useQuery({
    queryKey: ["directions", projectId],
    queryFn: () => api.get<EditorialDirection[]>(`/projects/${projectId}/directions`),
  });

  const discover = useMutation({
    mutationFn: () =>
      api.post<EditorialDirection[]>(`/projects/${projectId}/directions/discover`, { niche: nicheInput }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["directions", projectId] }),
  });

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="text-sm font-semibold text-slate-100">{pt.directions.discoverTitle}</h3>
        <p className="mt-1 text-xs text-slate-500">{pt.directions.discoverHint}</p>
        <form
          className="mt-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            discover.mutate();
          }}
        >
          <Input
            className="flex-1"
            value={nicheInput}
            onChange={(e) => setNicheInput(e.target.value)}
            placeholder={pt.directions.nichePlaceholder}
          />
          <Button type="submit" disabled={!nicheInput.trim() || discover.isPending}>
            {pt.directions.discoverSubmit}
          </Button>
        </form>
        {discover.isError && <p className="mt-2 text-xs text-rose-400">{(discover.error as Error).message}</p>}
      </Card>

      {directions.data && directions.data.length === 0 && (
        <EmptyState title={pt.directions.empty.title} hint={pt.directions.empty.hint} />
      )}

      <div className="space-y-3">
        {directions.data?.map((d, i) => <DirectionCard key={d.id} direction={d} index={i} />)}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- Vídeos */

function VideosTab({ projectId }: { projectId: string }) {
  const videos = useQuery({
    queryKey: ["videos", projectId],
    queryFn: () => api.get<Video[]>(`/videos?project_id=${projectId}`),
  });

  if (videos.data && videos.data.length === 0) {
    return <EmptyState title="Nenhum vídeo ainda" hint="Crie um vídeo para este canal em Criar." />;
  }

  return (
    <div className="space-y-2">
      {videos.data?.map((v) => (
        <Link key={v.id} to={`/videos/${v.id}`}>
          <Card interactive className="flex items-center justify-between">
            <span className="truncate text-sm text-slate-200">{v.title || v.idea}</span>
            <StatusBadge status={v.status} />
          </Card>
        </Link>
      ))}
    </div>
  );
}

/* --------------------------------------------------------------------- Contas */

const PLATFORMS = ["tiktok", "youtube", "facebook", "instagram"];

function AccountsTab() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  const [form, setForm] = useState({ name: "", platform: "tiktok", socialIds: "" });

  const create = useMutation({
    mutationFn: () =>
      api.post<Account>("/accounts", {
        name: form.name,
        platform: form.platform,
        params: {
          social_account_ids: form.socialIds
            .split(",")
            .map((s) => Number(s.trim()))
            .filter((n) => !Number.isNaN(n)),
        },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setForm({ ...form, name: "", socialIds: "" });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/accounts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">{pt.accounts.hint}</p>
      <Card>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <Field label={pt.accounts.platform}>
            <Select
              value={form.platform}
              onChange={(v) => setForm({ ...form, platform: v })}
              options={PLATFORMS.map((p) => ({ value: p, label: p }))}
            />
          </Field>
          <Field label={pt.accounts.name}>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label={pt.accounts.socialIds}>
            <Input value={form.socialIds} onChange={(e) => setForm({ ...form, socialIds: e.target.value })} />
          </Field>
          <div className="flex items-end">
            <Button disabled={!form.name || create.isPending} onClick={() => create.mutate()}>
              {pt.accounts.add}
            </Button>
          </div>
        </div>
      </Card>

      <div className="space-y-2">
        {data?.map((a) => (
          <Card key={a.id} className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-slate-100">{a.name}</span>
              <Tag>{a.platform}</Tag>
            </div>
            <div className="flex items-center gap-2">
              {a.enabled ? <StatusBadge status="completed" /> : <StatusBadge status="cancelled" />}
              <Button variant="danger" onClick={() => remove.mutate(a.id)}>
                {pt.accounts.delete}
              </Button>
            </div>
          </Card>
        ))}
        {data?.length === 0 && <p className="text-sm text-slate-500">{pt.accounts.empty}</p>}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------- Shell */

const TABS = ["referencias", "estilo", "direcoes", "videos", "contas"] as const;
type Tab = (typeof TABS)[number];

export default function ChannelDetail() {
  const { id = "" } = useParams();
  const project = useProject(id);
  const [tab, setTab] = useState<Tab>("referencias");

  if (project.isLoading) return <p className="text-slate-400">{pt.common.loading}</p>;
  const p = project.data;
  if (!p) return <p className="text-rose-400">{pt.common.notFound}</p>;

  return (
    <div>
      <PageHeader eyebrow={pt.channels.eyebrow} title={p.name} subtitle={`${p.niche || "sem nicho"} · ${p.language}`} />

      <div className="mb-5 flex gap-1 border-b border-white/10">
        {TABS.map((key) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition ${
              tab === key
                ? "border-brand-500 text-brand-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            {pt.channelDetail.tabs[key]}
          </button>
        ))}
      </div>

      {tab === "referencias" && <ReferencesTab projectId={id} />}
      {tab === "estilo" && <StyleTab projectId={id} onGoToReferences={() => setTab("referencias")} />}
      {tab === "direcoes" && <DirectionsTab projectId={id} niche={p.niche} />}
      {tab === "videos" && <VideosTab projectId={id} />}
      {tab === "contas" && <AccountsTab />}
    </div>
  );
}
