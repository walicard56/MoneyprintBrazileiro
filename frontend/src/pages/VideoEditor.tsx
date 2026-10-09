import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { MediaItem, Scene, VideoDetail as VideoDetailT, VoiceInfo } from "@/api/types";
import { Button, Card, Field, Input, PageHeader, Select, Slider, Textarea, Toggle } from "@/components/ui";
import { pt } from "@/i18n/ptBR";

/** Fetches an authenticated API path as a blob and hands back a local
 * object URL — there's no static file mount, so a plain <img src>/<video
 * src> can't reach these (no way to carry the bearer header). */
function useBlobUrl(path: string | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!path) {
      setUrl(null);
      return;
    }
    let objectUrl: string | null = null;
    let cancelled = false;
    api
      .getBlob(path)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setUrl(null);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);
  return url;
}

function SceneThumb({
  scene,
  selected,
  onClick,
}: {
  scene: Scene;
  selected: boolean;
  onClick: () => void;
}) {
  const url = useBlobUrl(scene.image_path ? `/scenes/${scene.id}/thumbnail` : null);
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex h-24 w-20 shrink-0 flex-col overflow-hidden rounded-lg border transition ${
        selected ? "border-brand-500 ring-2 ring-brand-500/40" : "border-white/10 hover:border-white/30"
      }`}
    >
      <div className="flex-1 bg-inset/70">
        {url ? (
          <img src={url} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-[10px] text-slate-600">—</div>
        )}
      </div>
      <div className="flex items-center justify-between bg-black/40 px-1.5 py-0.5">
        <span className="text-[10px] font-semibold text-slate-200">{scene.index}</span>
        <span className="text-[10px] text-slate-400">{scene.duration}s</span>
      </div>
    </button>
  );
}

function MediaSearchPanel({ videoId, sceneId, onUsed }: { videoId: string; sceneId: string; onUsed: () => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MediaItem[]>([]);

  const search = useMutation({
    mutationFn: () => api.get<MediaItem[]>(`/media/search?query=${encodeURIComponent(query)}&video_id=${videoId}`),
    onSuccess: setResults,
  });

  const use = useMutation({
    mutationFn: (item: MediaItem) =>
      api.post(`/scenes/${sceneId}/image/from-url`, {
        url: item.download_url,
        provider: item.provider,
        media_id: item.id,
      }),
    onSuccess: onUsed,
  });

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={pt.editor.searchPlaceholder}
          onKeyDown={(e) => e.key === "Enter" && query && search.mutate()}
        />
        <Button variant="ghost" onClick={() => search.mutate()} disabled={!query || search.isPending}>
          {pt.editor.searchButton}
        </Button>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {results.map((item) => (
          <div key={`${item.provider}:${item.id}`} className="overflow-hidden rounded-lg border border-white/10">
            <img src={item.thumbnail_url} alt="" className="h-20 w-full object-cover" />
            <Button
              variant="ghost"
              className="w-full rounded-none text-xs"
              onClick={() => use.mutate(item)}
              disabled={use.isPending}
            >
              {item.already_used ? `${pt.editor.use} (${pt.editor.alreadyUsed})` : pt.editor.use}
            </Button>
          </div>
        ))}
        {results.length === 0 && !search.isPending && (
          <p className="col-span-3 text-xs text-slate-500">{pt.editor.searchEmpty}</p>
        )}
      </div>
    </div>
  );
}

export default function VideoEditor() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [narration, setNarration] = useState("");
  const [duration, setDuration] = useState(0);
  const [splitPct, setSplitPct] = useState(50);
  const [showSearch, setShowSearch] = useState(false);
  const [captionEnabled, setCaptionEnabled] = useState(true);
  const [captionSize, setCaptionSize] = useState(48);
  const [captionColor, setCaptionColor] = useState("#FFFFFF");
  const [captionPosition, setCaptionPosition] = useState("bottom");
  const [voice, setVoice] = useState("");
  const [playingVoice, setPlayingVoice] = useState(false);

  const video = useQuery({
    queryKey: ["video", id],
    queryFn: () => api.get<VideoDetailT>(`/videos/${id}`),
    refetchInterval: 4000,
  });

  const voices = useQuery({
    queryKey: ["tts-voices", "edge"],
    queryFn: () => api.get<VoiceInfo[]>("/tts/voices?provider=edge"),
  });

  const v = video.data;
  const scenes = v?.scenes ?? [];
  const selected = scenes.find((s) => s.id === selectedId) ?? scenes[0] ?? null;

  useEffect(() => {
    if (selected) {
      setSelectedId(selected.id);
      setNarration(selected.narration);
      setDuration(selected.duration);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id]);

  useEffect(() => {
    if (v?.config) {
      setCaptionEnabled(v.config.subtitles_enabled !== false);
      setCaptionSize(Number(v.config.subtitle_fontsize ?? 48));
      setCaptionColor(String(v.config.subtitle_color ?? "#FFFFFF"));
      setCaptionPosition(String(v.config.subtitle_position ?? "bottom"));
      setVoice(String(v.config.voice ?? ""));
    }
  }, [v?.id, v?.config]);

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["video", id] });
  }

  const saveScene = useMutation({
    mutationFn: () => api.patch(`/scenes/${selected!.id}`, { narration, duration }),
    onSuccess: invalidate,
  });

  const split = useMutation({
    mutationFn: () => api.post(`/scenes/${selected!.id}/split`, { at_ratio: splitPct / 100 }),
    onSuccess: invalidate,
  });

  const mergeNext = useMutation({
    mutationFn: () => api.post(`/scenes/${selected!.id}/merge-next`),
    onSuccess: invalidate,
  });

  const regenerateImage = useMutation({
    mutationFn: () => api.post(`/scenes/${selected!.id}/image/regenerate`),
    onSuccess: invalidate,
  });

  const uploadImage = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.postForm(`/scenes/${selected!.id}/image/upload`, form);
    },
    onSuccess: invalidate,
  });

  const undo = useMutation({ mutationFn: () => api.post(`/videos/${id}/undo`), onSuccess: invalidate });
  const redo = useMutation({ mutationFn: () => api.post(`/videos/${id}/redo`), onSuccess: invalidate });

  const saveCaption = useMutation({
    mutationFn: () =>
      api.patch(`/videos/${id}/caption-style`, {
        enabled: captionEnabled,
        fontsize: captionSize,
        color: captionColor,
        position: captionPosition,
      }),
    onSuccess: invalidate,
  });

  const revoice = useMutation({
    mutationFn: () => api.post(`/videos/${id}/revoice`, { voice: voice || undefined }),
    onSuccess: invalidate,
  });

  const exportVideo = useMutation({
    mutationFn: () => api.post(`/videos/${id}/export`),
    onSuccess: invalidate,
  });

  async function listenVoice(voiceId: string) {
    setPlayingVoice(true);
    try {
      const blob = await api.postBlob("/tts/preview", { provider: "edge", voice: voiceId });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
    } finally {
      setPlayingVoice(false);
    }
  }

  async function downloadVideo() {
    const blob = await api.getBlob(`/videos/${id}/download`);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${v?.title || v?.topic || "video"}.mp4`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (video.isLoading) return <p className="text-slate-400">{pt.common.loading}</p>;
  if (!v) return <p className="text-rose-400">{pt.common.notFound}</p>;

  const isLast = selected ? selected.index === scenes.length : false;
  const exporting = v.status === "running" || v.status === "pending";

  return (
    <div>
      <PageHeader
        title={pt.editor.title}
        subtitle={v.title || v.topic}
        action={
          <div className="flex items-center gap-2">
            <Link to={`/videos/${id}`}>
              <Button variant="ghost">{pt.editor.backToVideo}</Button>
            </Link>
            <Button variant="ghost" onClick={() => undo.mutate()} disabled={undo.isPending}>
              {pt.editor.undo}
            </Button>
            <Button variant="ghost" onClick={() => redo.mutate()} disabled={redo.isPending}>
              {pt.editor.redo}
            </Button>
          </div>
        }
      />

      <Card className="mb-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">{pt.editor.scenesTitle(scenes.length)}</h2>
        {scenes.length === 0 ? (
          <p className="text-sm text-slate-500">{pt.editor.noScenesYet}</p>
        ) : (
          <div className="flex gap-2 overflow-x-auto pb-1">
            {scenes.map((s) => (
              <SceneThumb key={s.id} scene={s} selected={s.id === selected?.id} onClick={() => setSelectedId(s.id)} />
            ))}
          </div>
        )}
      </Card>

      {selected && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <h2 className="mb-3 text-sm font-semibold text-slate-200">
              {pt.editor.scenesTitle(scenes.length)} — #{selected.index}
            </h2>
            <div className="space-y-3">
              <Field label={pt.editor.narration}>
                <Textarea rows={4} value={narration} onChange={(e) => setNarration(e.target.value)} />
              </Field>
              <Field label={pt.editor.duration}>
                <Input
                  type="number"
                  step="0.1"
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}
                />
              </Field>
              <Button onClick={() => saveScene.mutate()} disabled={saveScene.isPending}>
                {pt.editor.saveScene}
              </Button>

              <div className="border-t border-white/10 pt-3">
                <Field label={`${pt.editor.splitAt} ${splitPct}%`}>
                  <Slider value={splitPct} onChange={setSplitPct} min={10} max={90} suffix="%" />
                </Field>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button variant="ghost" onClick={() => split.mutate()} disabled={split.isPending}>
                    {pt.editor.split}
                  </Button>
                  <Button variant="ghost" onClick={() => mergeNext.mutate()} disabled={mergeNext.isPending || isLast}>
                    {pt.editor.mergeNext}
                  </Button>
                </div>
                {isLast && <p className="mt-1 text-xs text-slate-500">{pt.editor.lastSceneHint}</p>}
              </div>
            </div>
          </Card>

          <Card>
            <h2 className="mb-3 text-sm font-semibold text-slate-200">{pt.editor.imageTitle}</h2>
            <SceneThumbLarge sceneId={selected.id} />
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="ghost" onClick={() => regenerateImage.mutate()} disabled={regenerateImage.isPending}>
                {pt.editor.imageRegenerate}
              </Button>
              <Button variant="ghost" onClick={() => setShowSearch((s) => !s)}>
                {pt.editor.imageSearch}
              </Button>
              <label>
                <span className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3.5 py-2 text-sm font-semibold text-slate-100 transition hover:border-white/20 hover:bg-white/10">
                  {pt.editor.imageUpload}
                </span>
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) uploadImage.mutate(file);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
            {showSearch && (
              <div className="mt-3 border-t border-white/10 pt-3">
                <MediaSearchPanel videoId={id} sceneId={selected.id} onUsed={invalidate} />
              </div>
            )}
          </Card>
        </div>
      )}

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">{pt.editor.captionTitle}</h2>
          <div className="space-y-3">
            <Toggle checked={captionEnabled} onChange={setCaptionEnabled} label={pt.editor.captionEnabled} />
            <Field label={pt.editor.captionSize}>
              <Input type="number" value={captionSize} onChange={(e) => setCaptionSize(Number(e.target.value))} />
            </Field>
            <Field label={pt.editor.captionColor}>
              <input
                type="color"
                value={captionColor}
                onChange={(e) => setCaptionColor(e.target.value)}
                className="h-9 w-16 cursor-pointer rounded-lg border border-white/10 bg-inset/70"
              />
            </Field>
            <Field label={pt.editor.captionPosition}>
              <Select
                value={captionPosition}
                onChange={setCaptionPosition}
                options={[
                  { value: "top", label: pt.editor.captionPositions.top },
                  { value: "center", label: pt.editor.captionPositions.center },
                  { value: "bottom", label: pt.editor.captionPositions.bottom },
                ]}
              />
            </Field>
            <Button onClick={() => saveCaption.mutate()} disabled={saveCaption.isPending}>
              {pt.editor.saveCaption}
            </Button>
          </div>
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">{pt.editor.voiceTitle}</h2>
          <div className="space-y-3">
            <Field label={pt.editor.voiceTitle}>
              <Select
                value={voice}
                onChange={setVoice}
                options={[{ value: "", label: "—" }, ...(voices.data ?? []).slice(0, 80).map((vo) => ({
                  value: vo.id,
                  label: `${vo.name} (${vo.language})`,
                }))]}
              />
            </Field>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => voice && listenVoice(voice)} disabled={!voice || playingVoice}>
                {pt.create.listen}
              </Button>
              <Button onClick={() => revoice.mutate()} disabled={revoice.isPending}>
                {pt.editor.voiceRevoice}
              </Button>
            </div>
          </div>
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">{pt.editor.exportTitle}</h2>
          <div className="space-y-3">
            <Button onClick={() => exportVideo.mutate()} disabled={exportVideo.isPending || exporting}>
              {exporting ? pt.editor.exporting : pt.editor.exportButton}
            </Button>
            {v.video_path ? (
              <Button variant="ghost" onClick={downloadVideo}>
                {pt.editor.download}
              </Button>
            ) : (
              <p className="text-xs text-slate-500">{pt.editor.notRenderedYet}</p>
            )}
            <p className="text-xs text-slate-500">{pt.editor.savedHint}</p>
          </div>
        </Card>
      </div>
    </div>
  );
}

function SceneThumbLarge({ sceneId }: { sceneId: string }) {
  const url = useBlobUrl(`/scenes/${sceneId}/thumbnail`);
  return (
    <div className="flex aspect-video items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-inset/50">
      {url ? <img src={url} alt="" className="h-full w-full object-contain" /> : <span className="text-xs text-slate-600">—</span>}
    </div>
  );
}
