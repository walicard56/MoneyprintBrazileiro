import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Project, Provider, Video } from "@/api/types";
import {
  Button,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Section,
  Select,
  Slider,
  Textarea,
  Toggle,
} from "@/components/ui";
import { IconScript, IconFilm, IconAudio, IconCaption, IconSparkles } from "@/components/icons";

const LANGUAGES = ["Portuguese", "English", "Spanish", "French", "German", "Italian", "Japanese"];
const TEMPLATES = [
  "curiosity", "storytelling", "list", "facts", "documentary",
  "news", "mystery", "educational", "motivational", "entertainment", "cinematic",
];
const TONES = ["neutral", "energetic", "calm", "dramatic", "funny", "inspirational"];
const PLATFORMS = ["tiktok", "youtube", "facebook", "instagram"];
const VOICES = ["Jasper", "Bella", "Luna", "Bruno", "Rosie", "Hugo", "Kiki", "Leo"];

const ASPECTS: Record<string, { label: string; w: number; h: number }> = {
  "9:16": { label: "9:16 vertical (Shorts/Reels/TikTok)", w: 1080, h: 1920 },
  "1:1": { label: "1:1 square", w: 1080, h: 1080 },
  "16:9": { label: "16:9 landscape", w: 1920, h: 1080 },
};

export default function Create() {
  const navigate = useNavigate();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  const providers = useQuery({ queryKey: ["providers"], queryFn: () => api.get<Provider[]>("/providers") });

  const [f, setF] = useState({
    projectId: "",
    subject: "",
    language: "Portuguese",
    template: "curiosity",
    tone: "energetic",
    duration: 45,
    platform: "tiktok",
    aspect: "9:16",
    mode: "auto",
    voice: "Jasper",
    musicEnabled: true,
    musicVolume: 10,
    subtitlesEnabled: true,
    subtitlePosition: "center",
    subtitleSize: 100,
    subtitleColor: "#FFFF00",
    count: 1,
  });
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((s) => ({ ...s, [k]: v }));

  // Default the project selection to the first available project.
  const projectId = f.projectId || projects.data?.[0]?.id || "";

  const missing = useMemo(() => {
    const caps = new Set((providers.data ?? []).filter((p) => p.enabled).map((p) => p.capability));
    const need: string[] = [];
    if (!caps.has("llm")) need.push("LLM");
    if (!caps.has("image")) need.push("Image");
    if (!caps.has("tts")) need.push("TTS");
    return need;
  }, [providers.data]);

  function buildConfig() {
    const aspect = ASPECTS[f.aspect];
    return {
      language: f.language,
      structure: f.template,
      tone: f.tone,
      duration: f.duration,
      platform: f.platform,
      aspect_ratio: f.aspect,
      preset: { width: aspect.w, height: aspect.h, fps: 30 },
      voice: f.voice,
      music_enabled: f.musicEnabled,
      music_volume: f.musicVolume / 100,
      subtitles_enabled: f.subtitlesEnabled,
      subtitle_position: f.subtitlePosition,
      subtitle_fontsize: f.subtitleSize,
      subtitle_color: f.subtitleColor,
    };
  }

  const generate = useMutation({
    mutationFn: async () => {
      const config = buildConfig();
      if (f.count > 1) {
        const topics = Array.from({ length: f.count }, () => f.subject);
        return api.post<Video[]>(`/projects/${projectId}/videos/batch`, {
          topics,
          mode: f.mode,
          config,
          autostart: true,
        });
      }
      const v = await api.post<Video>(`/projects/${projectId}/videos`, {
        idea: f.subject,
        topic: f.subject,
        mode: f.mode,
        config,
        autostart: true,
      });
      return v;
    },
    onSuccess: (res) => {
      if (Array.isArray(res)) navigate("/videos");
      else navigate(`/videos/${res.id}`);
    },
  });

  if (projects.isLoading) return <p className="text-slate-400">Loading…</p>;
  if ((projects.data ?? []).length === 0) {
    return (
      <div>
        <PageHeader title="Create video" subtitle="Turn an idea into a finished short." />
        <EmptyState
          title="You need a project first"
          hint="A project is a channel/niche with its own defaults (language, style, duration)."
          action={<Link to="/projects"><Button>Create a project</Button></Link>}
        />
      </div>
    );
  }

  return (
    <div className="pb-28">
      <PageHeader title="Create video" subtitle="Configure once, then let the agents do the work." />

      {missing.length > 0 && (
        <div className="mb-5 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
          No enabled provider for: <b>{missing.join(", ")}</b>. Add them in{" "}
          <Link to="/providers" className="underline">Providers</Link> or generation will fail at that stage.
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* Script */}
        <Section title="Script" description="What the video is about" icon={<IconScript />}>
          <Field label="Project">
            <Select
              value={projectId}
              onChange={(v) => set("projectId", v)}
              options={(projects.data ?? []).map((p) => ({ value: p.id, label: p.name }))}
            />
          </Field>
          <Field label="Subject / idea">
            <Textarea
              rows={4}
              value={f.subject}
              onChange={(e) => set("subject", e.target.value)}
              placeholder="e.g. Why the ocean looks blue — surprising facts"
            />
          </Field>
          <Field label="Language">
            <Select value={f.language} onChange={(v) => set("language", v)}
              options={LANGUAGES.map((l) => ({ value: l, label: l }))} />
          </Field>
          <Field label="Template / structure">
            <Select value={f.template} onChange={(v) => set("template", v)}
              options={TEMPLATES.map((t) => ({ value: t, label: t }))} />
          </Field>
          <Field label="Tone">
            <Select value={f.tone} onChange={(v) => set("tone", v)}
              options={TONES.map((t) => ({ value: t, label: t }))} />
          </Field>
        </Section>

        {/* Video */}
        <Section title="Video" description="Format and how it runs" icon={<IconFilm />}>
          <Field label="Platform">
            <Select value={f.platform} onChange={(v) => set("platform", v)}
              options={PLATFORMS.map((p) => ({ value: p, label: p }))} />
          </Field>
          <Field label="Aspect ratio">
            <Select value={f.aspect} onChange={(v) => set("aspect", v)}
              options={Object.entries(ASPECTS).map(([k, v]) => ({ value: k, label: v.label }))} />
          </Field>
          <Field label={`Duration — ${f.duration}s`}>
            <Slider value={f.duration} onChange={(v) => set("duration", v)} min={10} max={90} suffix="s" />
          </Field>
          <Field label="Generation mode">
            <Select
              value={f.mode}
              onChange={(v) => set("mode", v)}
              options={[
                { value: "auto", label: "Auto — run everything" },
                { value: "manual", label: "Manual — approve each step" },
                { value: "hybrid", label: "Hybrid — approve key steps" },
              ]}
            />
          </Field>
          <Field label="How many videos">
            <Input type="number" min={1} max={100} value={f.count}
              onChange={(e) => set("count", Math.max(1, Number(e.target.value)))} />
          </Field>
        </Section>

        {/* Audio + Subtitles */}
        <div className="space-y-5">
          <Section title="Audio" description="Voice and music" icon={<IconAudio />}>
            <Field label="Voice (KittenTTS)">
              <Select value={f.voice} onChange={(v) => set("voice", v)}
                options={VOICES.map((v) => ({ value: v, label: v }))} />
            </Field>
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">Background music</span>
              <Toggle checked={f.musicEnabled} onChange={(v) => set("musicEnabled", v)} />
            </div>
            {f.musicEnabled && (
              <Field label={`Music volume — ${f.musicVolume}%`}>
                <Slider value={f.musicVolume} onChange={(v) => set("musicVolume", v)} min={0} max={100} suffix="%" />
              </Field>
            )}
          </Section>

          <Section title="Subtitles" icon={<IconCaption />}>
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">Enable subtitles</span>
              <Toggle checked={f.subtitlesEnabled} onChange={(v) => set("subtitlesEnabled", v)} />
            </div>
            {f.subtitlesEnabled && (
              <>
                <Field label="Position">
                  <Select value={f.subtitlePosition} onChange={(v) => set("subtitlePosition", v)}
                    options={[
                      { value: "center", label: "Center" },
                      { value: "bottom", label: "Bottom" },
                      { value: "top", label: "Top" },
                    ]} />
                </Field>
                <Field label={`Font size — ${f.subtitleSize}`}>
                  <Slider value={f.subtitleSize} onChange={(v) => set("subtitleSize", v)} min={30} max={140} />
                </Field>
                <Field label="Color">
                  <input type="color" value={f.subtitleColor}
                    onChange={(e) => set("subtitleColor", e.target.value)}
                    className="h-9 w-16 cursor-pointer rounded-lg border border-white/10 bg-inset" />
                </Field>
              </>
            )}
          </Section>
        </div>
      </div>

      {/* Sticky generate bar */}
      <div className="fixed bottom-0 left-0 right-0 z-20 border-t border-white/10 bg-night/80 backdrop-blur-xl lg:left-64">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-4 md:px-8">
          <div className="font-mono text-xs text-slate-400">
            {f.count > 1 ? `${f.count} videos` : "1 video"} · {f.platform} · {f.aspect} · {f.duration}s · {f.mode}
          </div>
          <div className="flex items-center gap-3">
            {generate.error && (
              <span className="text-sm text-rose-400">{(generate.error as Error).message}</span>
            )}
            <button
              onClick={() => generate.mutate()}
              disabled={!f.subject || !projectId || generate.isPending}
              className="flex items-center gap-2 rounded-lg bg-gradient-to-b from-brand-500 to-brand-600 px-6 py-3 text-sm font-semibold text-white shadow-[0_10px_28px_-10px_rgba(37,99,235,0.95)] transition hover:from-brand-400 hover:to-brand-500 disabled:opacity-50"
            >
              <IconSparkles width={16} height={16} />
              {generate.isPending ? "Starting…" : "Generate video"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
