import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { EditorialDirection, Project, Provider, Video } from "@/api/types";
import {
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Section,
  Select,
  Slider,
  Tag,
  Textarea,
  Toggle,
} from "@/components/ui";
import { IconAudio, IconFilm, IconScript, IconSparkles } from "@/components/icons";
import { pt } from "@/i18n/ptBR";

const LANGUAGES = ["Portuguese", "English", "Spanish", "French", "German", "Italian", "Japanese"];
const TONES = ["neutral", "energetic", "calm", "dramatic", "funny", "inspirational"];
const PLATFORMS = ["tiktok", "youtube", "facebook", "instagram"];
const VOICES = ["Jasper", "Bella", "Luna", "Bruno", "Rosie", "Hugo", "Kiki", "Leo"];
const AI_MODELS = ["fast", "balanced", "quality", "max"] as const;
type EntryMode = "topic" | "discover" | "script" | "narration";

const ASPECTS: Record<string, { label: string; w: number; h: number }> = {
  "9:16": { label: "9:16 vertical (Shorts/Reels/TikTok)", w: 1080, h: 1920 },
  "1:1": { label: "1:1 square", w: 1080, h: 1080 },
  "16:9": { label: "16:9 landscape", w: 1920, h: 1080 },
};

export default function Create() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  const providers = useQuery({ queryKey: ["providers"], queryFn: () => api.get<Provider[]>("/providers") });

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [projectId, setProjectId] = useState("");
  const [mode, setMode] = useState<EntryMode>("topic");
  const [subject, setSubject] = useState(params.get("topic") ?? "");
  const [scriptText, setScriptText] = useState("");
  const [niche, setNiche] = useState("");
  const [directionId, setDirectionId] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showVoice, setShowVoice] = useState(false);
  const [showCustomize, setShowCustomize] = useState(false);

  const [f, setF] = useState({
    aiModel: "balanced" as (typeof AI_MODELS)[number],
    language: "Portuguese",
    structure: "curiosity",
    tone: "energetic",
    durationText: "45s",
    platform: "tiktok",
    aspect: "9:16",
    runMode: "auto",
    backgroundMedia: "video" as "video" | "mixed",
    imageVideoRatio: 40,
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

  const selectedProject = projects.data?.find((p) => p.id === projectId);

  const discover = useMutation({
    mutationFn: () =>
      api.post<EditorialDirection[]>(`/projects/${projectId}/directions/discover`, { niche }),
  });

  const missing = useMemo(() => {
    const caps = new Set((providers.data ?? []).filter((p) => p.enabled).map((p) => p.capability));
    const need: string[] = [];
    if (!caps.has("llm")) need.push("LLM");
    if (!caps.has("image")) need.push("Imagem");
    if (!caps.has("tts")) need.push("Voz");
    return need;
  }, [providers.data]);

  function buildConfig(): Record<string, unknown> {
    const aspect = ASPECTS[f.aspect];
    const config: Record<string, unknown> = {
      ai_model: f.aiModel,
      // Locked server-side too when a channel is selected (N3) — sent here
      // mainly so the review screen shows the language that will actually
      // be used, not a stale "sem canal" default.
      language: selectedProject ? selectedProject.language : f.language,
      structure: f.structure,
      tone: f.tone,
      duration_text: f.durationText,
      platform: f.platform,
      aspect_ratio: f.aspect,
      preset: { width: aspect.w, height: aspect.h, fps: 30 },
      background_media: f.backgroundMedia,
      image_video_ratio: f.imageVideoRatio,
      voice: f.voice,
      music_enabled: f.musicEnabled,
      music_volume: f.musicVolume / 100,
      subtitles_enabled: f.subtitlesEnabled,
      subtitle_position: f.subtitlePosition,
      subtitle_fontsize: f.subtitleSize,
      subtitle_color: f.subtitleColor,
    };
    if (mode === "script") {
      config.entry_mode = "script";
      config.script_text = scriptText;
    } else if (mode === "discover" && directionId) {
      config.entry_mode = "discover";
      config.direction_id = directionId;
    }
    return config;
  }

  const generate = useMutation({
    mutationFn: async () => {
      const config = buildConfig();
      if (f.count > 1 && mode === "topic") {
        const topics = Array.from({ length: f.count }, () => subject);
        return api.post<Video[]>(`/projects/${projectId}/videos/batch`, {
          topics,
          mode: f.runMode,
          config,
          autostart: true,
        });
      }
      const v = await api.post<Video>(`/projects/${projectId}/videos`, {
        idea: subject,
        topic: subject,
        mode: f.runMode,
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

  if (projects.isLoading) return <p className="text-slate-400">{pt.common.loading}</p>;
  if ((projects.data ?? []).length === 0) {
    return (
      <div>
        <PageHeader title={pt.create.title} subtitle={pt.create.subtitle} />
        <EmptyState
          title="Você precisa de um canal primeiro"
          hint="Um canal guarda os padrões do vídeo: idioma, estilo, duração."
          action={<Link to="/canais"><Button>Criar um canal</Button></Link>}
        />
      </div>
    );
  }

  // The backend requires a real project_id to create a video (Video.project_id
  // is a non-nullable FK) — "Sem canal" is shown per the spec's described
  // layout, but a channel must actually be picked before continuing.
  const canAdvance =
    step === 1
      ? !!projectId
      : step === 2
        ? (mode === "topic" && !!subject) ||
          (mode === "script" && !!scriptText) ||
          (mode === "discover" && !!directionId)
        : true;
  const canGenerate = !!projectId && canAdvance && !generate.isPending;

  return (
    <div className="pb-28">
      <PageHeader title={pt.create.title} subtitle={pt.create.subtitle} />

      {missing.length > 0 && (
        <div className="mb-5 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
          {pt.create.missingProviders} <b>{missing.join(", ")}</b>.{" "}
          <Link to="/providers" className="underline">Providers</Link>
        </div>
      )}

      <div className="mb-6 flex gap-2">
        {([1, 2, 3] as const).map((n) => (
          <button
            key={n}
            onClick={() => n < step && setStep(n)}
            className={`flex-1 rounded-lg border px-3 py-2 text-center text-xs font-semibold transition ${
              step === n
                ? "border-brand-500 bg-brand-500/10 text-brand-300"
                : n < step
                  ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-300"
                  : "border-white/10 text-slate-500"
            }`}
          >
            {n}. {n === 1 ? "Canal" : n === 2 ? "Começo" : "Ajustes"}
          </button>
        ))}
      </div>

      {step === 1 && (
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-100">{pt.create.step1Title}</h2>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setProjectId("")}
              className={`rounded-full border px-3 py-1.5 text-sm transition ${
                projectId === ""
                  ? "border-brand-500 bg-brand-500/10 text-brand-300"
                  : "border-white/10 text-slate-400 hover:border-white/20"
              }`}
            >
              {pt.create.noChannel}
            </button>
            {projects.data?.map((p) => (
              <button
                key={p.id}
                onClick={() => setProjectId(p.id)}
                className={`rounded-full border px-3 py-1.5 text-sm transition ${
                  projectId === p.id
                    ? "border-brand-500 bg-brand-500/10 text-brand-300"
                    : "border-white/10 text-slate-400 hover:border-white/20"
                }`}
              >
                {p.name}
              </button>
            ))}
            <Link
              to="/canais"
              className="rounded-full border border-dashed border-white/15 px-3 py-1.5 text-sm text-slate-400 hover:border-white/30"
            >
              {pt.create.newChannelChip}
            </Link>
          </div>
          {selectedProject && (
            <p className="mt-3 text-xs text-slate-500">{pt.create.channelHint(selectedProject.name)}</p>
          )}
          {!projectId && (
            <p className="mt-3 text-xs text-amber-400">Escolha um canal para continuar.</p>
          )}
          <div className="mt-5 flex justify-end">
            <Button onClick={() => setStep(2)} disabled={!canAdvance}>Próximo</Button>
          </div>
        </Card>
      )}

      {step === 2 && (
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-100">{pt.create.step2Title}</h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {(Object.keys(pt.create.modes) as EntryMode[]).map((key) => {
              const disabled = key === "narration";
              const info = pt.create.modes[key];
              return (
                <button
                  key={key}
                  disabled={disabled}
                  onClick={() => setMode(key)}
                  className={`rounded-xl border p-4 text-left transition disabled:cursor-not-allowed disabled:opacity-50 ${
                    mode === key
                      ? "border-brand-500 bg-brand-500/10"
                      : "border-white/10 hover:border-white/20"
                  }`}
                >
                  <div className="font-semibold text-slate-100">{info.label}</div>
                  <div className="mt-1 text-xs text-slate-500">
                    {disabled ? pt.create.narrationComingSoon : info.hint}
                  </div>
                </button>
              );
            })}
          </div>

          {mode === "topic" && (
            <div className="mt-4">
              <Field label={pt.create.topicLabel}>
                <Textarea
                  rows={4}
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder={pt.create.topicPlaceholder}
                />
              </Field>
            </div>
          )}

          {mode === "discover" && (
            <div className="mt-4 space-y-3">
              <Field label={pt.create.discoverNicheLabel}>
                <div className="flex gap-2">
                  <Input className="flex-1" value={niche} onChange={(e) => setNiche(e.target.value)} />
                  <Button
                    type="button"
                    onClick={() => discover.mutate()}
                    disabled={!niche.trim() || !projectId || discover.isPending}
                  >
                    {pt.create.discoverSubmit}
                  </Button>
                </div>
              </Field>
              <p className="text-xs text-slate-500">{pt.create.discoverRule}</p>
              {!projectId && <p className="text-xs text-amber-400">Escolha um canal no passo 1 para descobrir tendências.</p>}
              {discover.isError && <p className="text-xs text-rose-400">{(discover.error as Error).message}</p>}
              <div className="space-y-2">
                {discover.data?.map((d) => (
                  <button
                    key={d.id}
                    onClick={() => {
                      setDirectionId(d.id);
                      setSubject(d.title);
                    }}
                    className={`block w-full rounded-lg border p-3 text-left transition ${
                      directionId === d.id
                        ? "border-brand-500 bg-brand-500/10"
                        : "border-white/10 hover:border-white/20"
                    }`}
                  >
                    <div className="text-sm font-medium text-slate-100">{d.title}</div>
                    <div className="mt-0.5 text-xs text-slate-500">{d.why}</div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {mode === "script" && (
            <div className="mt-4">
              <Field label={pt.create.scriptLabel}>
                <Textarea rows={8} value={scriptText} onChange={(e) => setScriptText(e.target.value)} />
              </Field>
              <p className="mt-1 text-xs text-slate-500">{pt.create.scriptRule}</p>
            </div>
          )}

          <div className="mt-5 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(1)}>Voltar</Button>
            <Button onClick={() => setStep(3)} disabled={!canAdvance}>Próximo</Button>
          </div>
        </Card>
      )}

      {step === 3 && (
        <div className="space-y-5">
          <Section title={pt.create.step3Title} icon={<IconSparkles />}>
            <Field label={pt.create.aiModel}>
              <Select
                value={f.aiModel}
                onChange={(v) => set("aiModel", v as typeof f.aiModel)}
                options={AI_MODELS.map((m) => ({ value: m, label: pt.create.aiModelOptions[m] }))}
              />
            </Field>
            <Field label={pt.create.duration}>
              <Input
                value={f.durationText}
                onChange={(e) => set("durationText", e.target.value)}
                placeholder={pt.create.durationPlaceholder}
              />
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {["30s", "45s", "60s", "90s", "5 min", "10 min", "20 min", "1 hora"].map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => set("durationText", v)}
                    className={`rounded-full border px-2.5 py-1 text-xs transition ${
                      f.durationText === v
                        ? "border-brand-500 bg-brand-500/10 text-brand-300"
                        : "border-white/10 text-slate-500 hover:border-white/20"
                    }`}
                  >
                    {v}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-xs text-slate-500">{pt.create.durationHint}</p>
            </Field>
            <Field label={pt.create.language}>
              {selectedProject ? (
                <>
                  <div className={`${"rounded-lg border border-white/10 bg-inset px-3 py-2 text-sm text-slate-400"}`}>
                    {selectedProject.language}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{pt.create.languageLockedByChannel}</p>
                </>
              ) : (
                <Select
                  value={f.language}
                  onChange={(v) => set("language", v)}
                  options={LANGUAGES.map((l) => ({ value: l, label: l }))}
                />
              )}
            </Field>
            <Field label={pt.create.backgroundMedia}>
              <Select
                value={f.backgroundMedia}
                onChange={(v) => set("backgroundMedia", v as typeof f.backgroundMedia)}
                options={Object.entries(pt.create.backgroundMediaOptions).map(([value, label]) => ({ value, label }))}
              />
            </Field>
            {f.backgroundMedia === "mixed" && (
              <Field label={`${pt.create.videoImageRatio} — ${f.imageVideoRatio}%`}>
                <Slider value={f.imageVideoRatio} onChange={(v) => set("imageVideoRatio", v)} min={0} max={100} suffix="%" />
              </Field>
            )}
          </Section>

          <Section title={pt.create.voiceSection} icon={<IconAudio />}>
            <button
              onClick={() => setShowVoice((v) => !v)}
              className="text-xs font-medium text-brand-300 hover:underline"
            >
              {showVoice ? "Ocultar" : "Mostrar"}
            </button>
            {showVoice && (
              <>
                <Field label="Voz">
                  <div className="flex gap-2">
                    <Select className="flex-1" value={f.voice} onChange={(v) => set("voice", v)}
                      options={VOICES.map((v) => ({ value: v, label: v }))} />
                    <Button type="button" variant="ghost">{pt.create.listen}</Button>
                  </div>
                </Field>
                <p className="text-xs text-emerald-400">{pt.create.voiceFreeNote}</p>
              </>
            )}
          </Section>

          <Section title={pt.create.customizeSection} icon={<IconScript />}>
            <button
              onClick={() => setShowCustomize((v) => !v)}
              className="text-xs font-medium text-brand-300 hover:underline"
            >
              {showCustomize ? "Ocultar" : "Mostrar"}
            </button>
            {showCustomize && (
              <>
                <Field label="Tom">
                  <Select value={f.tone} onChange={(v) => set("tone", v)}
                    options={TONES.map((t) => ({ value: t, label: t }))} />
                </Field>
                <Field label="Modo de geração">
                  <Select
                    value={f.runMode}
                    onChange={(v) => set("runMode", v)}
                    options={[
                      { value: "auto", label: "Automático — roda tudo" },
                      { value: "manual", label: "Manual — aprova cada etapa" },
                      { value: "hybrid", label: "Híbrido — aprova etapas chave" },
                    ]}
                  />
                </Field>
              </>
            )}
          </Section>

          <Section title={pt.create.advancedSection} icon={<IconFilm />}>
            <button
              onClick={() => setShowAdvanced((v) => !v)}
              className="text-xs font-medium text-brand-300 hover:underline"
            >
              {showAdvanced ? "Ocultar" : "Mostrar"}
            </button>
            {showAdvanced && (
              <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
                <Field label="Plataforma">
                  <Select value={f.platform} onChange={(v) => set("platform", v)}
                    options={PLATFORMS.map((p) => ({ value: p, label: p }))} />
                </Field>
                <Field label="Proporção">
                  <Select value={f.aspect} onChange={(v) => set("aspect", v)}
                    options={Object.entries(ASPECTS).map(([k, v]) => ({ value: k, label: v.label }))} />
                </Field>
                {mode === "topic" && (
                  <Field label="Quantos vídeos">
                    <Input type="number" min={1} max={100} value={f.count}
                      onChange={(e) => set("count", Math.max(1, Number(e.target.value)))} />
                  </Field>
                )}
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-400">Música de fundo</span>
                  <Toggle checked={f.musicEnabled} onChange={(v) => set("musicEnabled", v)} />
                </div>
                {f.musicEnabled && (
                  <Field label={`Volume da música — ${f.musicVolume}%`}>
                    <Slider value={f.musicVolume} onChange={(v) => set("musicVolume", v)} min={0} max={100} suffix="%" />
                  </Field>
                )}
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-400">Legendas</span>
                  <Toggle checked={f.subtitlesEnabled} onChange={(v) => set("subtitlesEnabled", v)} />
                </div>
                {f.subtitlesEnabled && (
                  <>
                    <Field label="Posição">
                      <Select value={f.subtitlePosition} onChange={(v) => set("subtitlePosition", v)}
                        options={[
                          { value: "center", label: "Centro" },
                          { value: "bottom", label: "Embaixo" },
                          { value: "top", label: "Em cima" },
                        ]} />
                    </Field>
                    <Field label={`Tamanho da fonte — ${f.subtitleSize}`}>
                      <Slider value={f.subtitleSize} onChange={(v) => set("subtitleSize", v)} min={30} max={140} />
                    </Field>
                    <Field label="Cor">
                      <input type="color" value={f.subtitleColor}
                        onChange={(e) => set("subtitleColor", e.target.value)}
                        className="h-9 w-16 cursor-pointer rounded-lg border border-white/10 bg-inset" />
                    </Field>
                  </>
                )}
              </div>
            )}
          </Section>

          <div className="flex justify-between">
            <Button variant="ghost" onClick={() => setStep(2)}>Voltar</Button>
          </div>
        </div>
      )}

      {/* Sticky generate bar */}
      <div className="fixed bottom-0 left-0 right-0 z-20 border-t border-white/10 bg-night/80 backdrop-blur-xl lg:left-64">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-4 md:px-8">
          <div className="flex items-center gap-2 font-mono text-xs text-slate-400">
            <Tag>{mode}</Tag>
            <span>{f.platform} · {f.aspect} · {f.durationText} · {f.runMode}</span>
          </div>
          <div className="flex items-center gap-3">
            {generate.error && (
              <span className="text-sm text-rose-400">{(generate.error as Error).message}</span>
            )}
            {step < 3 ? (
              <Button onClick={() => setStep((s) => (s + 1) as 1 | 2 | 3)} disabled={!canAdvance}>
                Próximo
              </Button>
            ) : (
              <button
                onClick={() => generate.mutate()}
                disabled={!canGenerate}
                className="flex items-center gap-2 rounded-lg bg-gradient-to-b from-brand-500 to-brand-600 px-6 py-3 text-sm font-semibold text-white shadow-[0_10px_28px_-10px_rgba(37,99,235,0.95)] transition hover:from-brand-400 hover:to-brand-500 disabled:opacity-50"
              >
                <IconSparkles width={16} height={16} />
                {generate.isPending ? pt.create.submitting : pt.create.submit}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
