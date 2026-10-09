import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Provider, VoiceInfo } from "@/api/types";
import { Button, Card, Field, Input, PageHeader, Select, Tag } from "@/components/ui";
import { pt } from "@/i18n/ptBR";

/* ------------------------------------------------------------- Sua IA (Etapa 5) */

function AiAccountCard({ name }: { name: string }) {
  return (
    <Card className="opacity-70">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-slate-200">{name}</h4>
        <Tag color="amber">{pt.settings.aiStatusPending}</Tag>
      </div>
      <p className="mt-2 text-xs text-slate-500">{pt.settings.aiHint}</p>
    </Card>
  );
}

/* ------------------------------------------------------------- Vozes (Etapa 5) */

function EdgeVoiceBrowser() {
  const [locale, setLocale] = useState("");
  const [playing, setPlaying] = useState<string | null>(null);

  const voices = useQuery({
    queryKey: ["tts-voices", "edge", locale],
    queryFn: () =>
      api.get<VoiceInfo[]>(`/tts/voices?provider=edge${locale ? `&locale=${locale}` : ""}`),
  });

  const commonLocales = ["pt-BR", "en-US", "es-ES", "fr-FR", "de-DE"];

  async function listen(voice: VoiceInfo) {
    setPlaying(voice.id);
    try {
      const blob = await api.postBlob("/tts/preview", { provider: "edge", voice: voice.id });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
    } finally {
      setPlaying(null);
    }
  }

  return (
    <Card>
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-slate-200">Microsoft Edge (grátis)</h4>
        <Tag color="emerald">{pt.settings.configured}</Tag>
      </div>
      <p className="mt-1 text-xs text-slate-500">{pt.settings.voicesFreeNote}</p>

      <div className="mt-3 max-w-xs">
        <Field label={pt.settings.voicesFilterLanguage}>
          <Select
            value={locale}
            onChange={setLocale}
            options={[{ value: "", label: pt.settings.voicesAll }, ...commonLocales.map((l) => ({ value: l, label: l }))]}
          />
        </Field>
      </div>

      <div className="mt-3 max-h-64 space-y-1 overflow-y-auto">
        {voices.data?.slice(0, 50).map((v) => (
          <div key={v.id} className="flex items-center justify-between rounded-lg border border-white/5 px-3 py-1.5 text-sm">
            <span className="text-slate-300">
              {v.name} <span className="text-xs text-slate-500">({v.language}, {v.gender})</span>
            </span>
            <Button variant="ghost" onClick={() => listen(v)} disabled={playing === v.id}>
              {playing === v.id ? "…" : pt.settings.voicesListen}
            </Button>
          </div>
        ))}
        {voices.data && voices.data.length > 50 && (
          <p className="pt-1 text-center text-xs text-slate-500">
            +{voices.data.length - 50} outras — filtre por idioma para ver mais específicas.
          </p>
        )}
        {voices.isLoading && <p className="text-xs text-slate-500">{pt.common.loading}</p>}
      </div>
    </Card>
  );
}

function PaidTtsKeyCard({
  providerKey,
  name,
  docsUrl,
}: {
  providerKey: string;
  name: string;
  docsUrl: string;
}) {
  const qc = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const providers = useQuery({
    queryKey: ["providers", "tts"],
    queryFn: () => api.get<Provider[]>("/providers?capability=tts"),
  });
  const existing = providers.data?.find((p) => p.provider === providerKey);

  const balance = useQuery({
    queryKey: ["tts-balance", providerKey],
    queryFn: () => api.get<{ balance: string | null }>(`/tts/balance?provider=${providerKey}`),
    enabled: !!existing,
  });

  const save = useMutation({
    mutationFn: () =>
      api.post<Provider>("/providers", { name, capability: "tts", provider: providerKey, api_key: apiKey }),
    onSuccess: async () => {
      setApiKey("");
      await qc.invalidateQueries({ queryKey: ["providers", "tts"] });
      setMessage(null);
    },
    onError: (err: Error) => setMessage(`Falhou: ${err.message}`),
  });

  const remove = useMutation({
    mutationFn: () => api.del(`/providers/${existing!.id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["providers", "tts"] });
      setMessage(null);
    },
  });

  const test = useMutation({
    mutationFn: () => api.get<VoiceInfo[]>(`/tts/voices?provider=${providerKey}`),
    onSuccess: (voices) => setMessage(`OK — ${voices.length} vozes encontradas.`),
    onError: (err: Error) => setMessage(`Falhou: ${err.message}`),
  });

  return (
    <Card>
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-slate-200">{name}</h4>
        {existing ? <Tag color="emerald">{pt.settings.configured}</Tag> : null}
      </div>
      <a href={docsUrl} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs text-brand-300 hover:underline">
        {pt.settings.howToGetKey}
      </a>

      {existing ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {balance.data?.balance && <span className="text-xs text-slate-400">{balance.data.balance}</span>}
          <Button variant="ghost" onClick={() => test.mutate()} disabled={test.isPending}>
            {test.isPending ? pt.settings.testing : "Testar"}
          </Button>
          <Button variant="ghost" onClick={() => remove.mutate()} disabled={remove.isPending}>
            {pt.settings.removeKey}
          </Button>
        </div>
      ) : (
        <div className="mt-3 flex gap-2">
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={pt.settings.apiKeyPlaceholder}
          />
          <Button onClick={() => save.mutate()} disabled={!apiKey || save.isPending}>
            {pt.settings.saveAndTest}
          </Button>
        </div>
      )}
      {message && <p className="mt-2 text-xs text-slate-400">{message}</p>}
    </Card>
  );
}

/* ------------------------------------------------------------- Mídia (Etapa 5) */

function MediaKeyCard({ providerKey, name, docsUrl }: { providerKey: string; name: string; docsUrl: string }) {
  const qc = useQueryClient();
  const [apiKey, setApiKey] = useState("");

  const providers = useQuery({
    queryKey: ["providers", "media"],
    queryFn: () => api.get<Provider[]>("/providers?capability=media"),
  });
  const existing = providers.data?.find((p) => p.provider === providerKey);

  const save = useMutation({
    mutationFn: () =>
      api.post<Provider>("/providers", { name, capability: "media", provider: providerKey, api_key: apiKey }),
    onSuccess: async () => {
      setApiKey("");
      await qc.invalidateQueries({ queryKey: ["providers", "media"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/providers/${existing!.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["providers", "media"] }),
  });

  return (
    <Card>
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-slate-200">{name}</h4>
        {existing ? <Tag color="emerald">{pt.settings.configured}</Tag> : <Tag color="slate">{pt.settings.mediaNeedsKey}</Tag>}
      </div>
      <a href={docsUrl} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs text-brand-300 hover:underline">
        {pt.settings.howToGetKey}
      </a>
      {existing ? (
        <div className="mt-3">
          <Button variant="ghost" onClick={() => remove.mutate()} disabled={remove.isPending}>
            {pt.settings.removeKey}
          </Button>
        </div>
      ) : (
        <div className="mt-3 flex gap-2">
          <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={pt.settings.apiKeyPlaceholder} />
          <Button onClick={() => save.mutate()} disabled={!apiKey || save.isPending}>
            {pt.settings.saveAndTest}
          </Button>
        </div>
      )}
    </Card>
  );
}

function KeylessMediaCard({ name }: { name: string }) {
  return (
    <Card>
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-slate-200">{name}</h4>
        <Tag color="emerald">{pt.settings.configured}</Tag>
      </div>
      <p className="mt-1 text-xs text-slate-500">{pt.settings.mediaFreeNote}</p>
    </Card>
  );
}

/* ------------------------------------------------------------------- Settings */

export default function Settings() {
  const [token, setToken] = useState(() => {
    try {
      return localStorage.getItem("mp_token") ?? "";
    } catch {
      return "";
    }
  });
  const [saved, setSaved] = useState(false);

  const seed = useMutation({
    mutationFn: () => api.post<{ prompts_created: number; agent_configs_created: number }>("/admin/seed"),
  });

  function saveToken() {
    try {
      if (token) localStorage.setItem("mp_token", token);
      else localStorage.removeItem("mp_token");
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch {
      /* ignore */
    }
  }

  return (
    <div>
      <PageHeader eyebrow="Workspace configuration" title={<>Settings</>} />

      <Card className="mb-4 max-w-xl">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Local API token</h2>
        <p className="mb-3 text-xs text-slate-500">
          Only needed if the backend sets{" "}
          <code className="rounded bg-inset px-1.5 py-0.5 font-mono text-[11px] text-brand-300">MP_LOCAL_API_TOKEN</code>. Stored in this browser only.
        </p>
        <Field label="Token">
          <Input type="password" value={token} onChange={(e) => setToken(e.target.value)} />
        </Field>
        <div className="mt-3">
          <Button onClick={saveToken}>{saved ? "Saved ✓" : "Save"}</Button>
        </div>
      </Card>

      <h2 className="mb-2 mt-6 text-sm font-semibold text-slate-200">{pt.settings.aiTitle}</h2>
      <div className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-2">
        <AiAccountCard name="Claude Code" />
        <AiAccountCard name="Codex" />
      </div>

      <h2 className="mb-2 text-sm font-semibold text-slate-200">{pt.settings.voicesTitle}</h2>
      <div className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-2">
        <EdgeVoiceBrowser />
        <div className="space-y-3">
          <PaidTtsKeyCard providerKey="elevenlabs" name="ElevenLabs" docsUrl="https://elevenlabs.io/app/settings/api-keys" />
          <PaidTtsKeyCard providerKey="gemini_tts" name="Gemini (Google)" docsUrl="https://aistudio.google.com/apikey" />
        </div>
      </div>

      <h2 className="mb-2 text-sm font-semibold text-slate-200">{pt.settings.mediaTitle}</h2>
      <div className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-2">
        <MediaKeyCard providerKey="media_pexels" name="Pexels" docsUrl="https://www.pexels.com/api/" />
        <MediaKeyCard providerKey="media_pixabay" name="Pixabay" docsUrl="https://pixabay.com/api/docs/" />
        <KeylessMediaCard name="Wikimedia Commons" />
        <KeylessMediaCard name="Openverse" />
        <KeylessMediaCard name="NASA Image and Video Library" />
      </div>

      <Card className="mb-4 max-w-xl">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Laboratório (Etapa 3)</h2>
        <p className="mb-3 text-xs text-slate-500">
          Limites e retenção do Laboratório de vídeo, configurados no backend (<code className="rounded bg-inset px-1.5 py-0.5 font-mono text-[11px] text-brand-300">.env</code>), não aqui.
        </p>
        <ul className="space-y-1.5 text-xs text-slate-400">
          <li>
            Duração máxima por vídeo: <code className="rounded bg-inset px-1.5 py-0.5 font-mono text-[11px] text-brand-300">MP_LAB_MAX_DURATION_S</code> (padrão 900s / 15 min)
          </li>
          <li>
            Tamanho máximo do arquivo: <code className="rounded bg-inset px-1.5 py-0.5 font-mono text-[11px] text-brand-300">MP_LAB_MAX_UPLOAD_MB</code> (padrão 500 MB)
          </li>
          <li>
            Retenção das miniaturas: <code className="rounded bg-inset px-1.5 py-0.5 font-mono text-[11px] text-brand-300">MP_LAB_RETENTION_DAYS</code> (padrão 7 dias) — o vídeo enviado é sempre apagado logo após a análise
          </li>
          <li>
            Adaptador de link (yt-dlp): <code className="rounded bg-inset px-1.5 py-0.5 font-mono text-[11px] text-brand-300">MP_ENABLE_LINK_FETCH</code> — <strong className="text-amber-400">desligado por padrão</strong>. Ligar é uma decisão sua: pode violar os Termos de Uso da plataforma de origem e sujeitar sua chave/IP a bloqueio. Não há um botão aqui de propósito — mude a variável de ambiente e reinicie o backend se aceitar o risco.
          </li>
        </ul>
      </Card>

      <Card className="max-w-xl">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Seed defaults</h2>
        <p className="mb-3 text-xs text-slate-500">
          Create the default prompts and agent configurations (safe to run repeatedly).
        </p>
        <Button onClick={() => seed.mutate()} disabled={seed.isPending}>
          {seed.isPending ? "Seeding…" : "Seed defaults"}
        </Button>
        {seed.data && (
          <span className="ml-3 text-sm text-emerald-400">
            +{seed.data.prompts_created} prompts, +{seed.data.agent_configs_created} agents
          </span>
        )}
      </Card>
    </div>
  );
}
