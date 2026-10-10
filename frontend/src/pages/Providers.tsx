import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type {
  AgentConfig,
  AutoFixResult,
  Capability,
  Prompt,
  Provider,
  ProviderCatalogEntry,
  ProviderPreset,
  VoiceInfo,
} from "@/api/types";
import {
  Button,
  Card,
  Field,
  HealthBadge,
  Input,
  PageHeader,
  Section,
  Select,
  SpecBox,
  Tag,
  TopPick,
  TypeBadge,
} from "@/components/ui";
import { IconPlug } from "@/components/icons";
import { EditProviderModal } from "@/components/providers/EditProviderModal";
import { ModelsPanel } from "@/components/providers/ModelsPanel";
import { KeysPanel } from "@/components/providers/KeysPanel";
import { HistoryPanel } from "@/components/providers/HistoryPanel";
import { pt } from "@/i18n/ptBR";

const CAPS: { key: Capability; label: string }[] = [
  { key: "llm", label: "Text (LLM)" },
  { key: "image", label: "Image" },
  { key: "tts", label: "Voice (TTS)" },
  { key: "stt", label: "Subtitles (STT)" },
  { key: "publish", label: "Publishing" },
  { key: "video", label: "Video" },
  { key: "search", label: "Search" },
  { key: "music", label: "Music" },
  { key: "media", label: "Media search" },
];

type PageSection = "catalog" | "pipeline";

export default function Providers() {
  const [section, setSection] = useState<PageSection>("catalog");

  return (
    <div>
      <PageHeader
        eyebrow="Connect your APIs"
        title={<>Providers &amp; <span className="gradient-text">APIs</span></>}
        subtitle="Pick a service, follow the guide, paste your key. Free options are marked."
      />

      {/* Page-level sections */}
      <div className="mb-6 flex gap-1 border-b border-white/10">
        <button
          onClick={() => setSection("catalog")}
          className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition ${
            section === "catalog"
              ? "border-brand-500 text-brand-300"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          Providers
        </button>
        <button
          onClick={() => setSection("pipeline")}
          className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition ${
            section === "pipeline"
              ? "border-brand-500 text-brand-300"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          Agents &amp; Prompts
        </button>
      </div>

      {section === "catalog" ? <ProviderCatalog /> : <PipelineTuning />}
    </div>
  );
}

/* ------------------------------------------------------------ Catalog tab */

function ProviderCatalog() {
  const qc = useQueryClient();
  const [cap, setCap] = useState<Capability>("llm");
  const [setup, setSetup] = useState<ProviderPreset | null>(null);
  const [showCustom, setShowCustom] = useState(false);

  const providers = useQuery({ queryKey: ["providers"], queryFn: () => api.get<Provider[]>("/providers") });
  const presets = useQuery({
    queryKey: ["provider-presets"],
    queryFn: () => api.get<ProviderPreset[]>("/providers/presets"),
  });

  const presetsForCap = useMemo(
    () => (presets.data ?? []).filter((p) => p.capability === cap),
    [presets.data, cap],
  );
  const mine = useMemo(
    () => (providers.data ?? []).filter((p) => p.capability === cap),
    [providers.data, cap],
  );

  return (
    <div>
      {/* Capability tabs */}
      <div className="mb-6 flex flex-wrap gap-2">
        {CAPS.map((c) => (
          <button
            key={c.key}
            onClick={() => setCap(c.key)}
            className={`rounded-lg px-3.5 py-1.5 text-sm font-medium transition ${
              cap === c.key
                ? "bg-gradient-to-b from-brand-500 to-brand-600 text-white shadow-[0_8px_22px_-12px_rgba(37,99,235,0.9)]"
                : "border border-white/10 bg-white/5 text-slate-300 hover:border-white/20 hover:bg-white/10"
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Curated extras that don't (yet) have a one-click preset */}
      {cap === "tts" && (
        <div className="mb-8 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <EdgeVoiceBrowser />
          <div className="space-y-3">
            <PaidTtsKeyCard providerKey="elevenlabs" name="ElevenLabs" docsUrl="https://elevenlabs.io/app/settings/api-keys" />
            <PaidTtsKeyCard providerKey="gemini_tts" name="Gemini (Google)" docsUrl="https://aistudio.google.com/apikey" />
          </div>
        </div>
      )}
      {cap === "media" && (
        <div className="mb-8 grid grid-cols-1 gap-3 md:grid-cols-2">
          <MediaKeyCard providerKey="media_pexels" name="Pexels" docsUrl="https://www.pexels.com/api/" />
          <MediaKeyCard providerKey="media_pixabay" name="Pixabay" docsUrl="https://pixabay.com/api/docs/" />
          <KeylessMediaCard name="Wikimedia Commons" />
          <KeylessMediaCard name="Openverse" />
          <KeylessMediaCard name="NASA Image and Video Library" />
        </div>
      )}

      {/* Preset gallery */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {presetsForCap.map((p) => {
          const installed = mine.some((m) => m.provider === p.provider && m.model === p.default_model);
          return (
            <Card key={p.id} interactive={!installed} featured={installed} className="flex flex-col">
              <div className="mb-3 flex items-start justify-between gap-2">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500/80 to-violet-600/80 text-sm font-bold text-white">
                    {p.display_name.charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <div className="truncate font-semibold text-slate-100">{p.display_name}</div>
                    {p.recommended && <div className="mt-0.5"><TopPick /></div>}
                  </div>
                </div>
                <TypeBadge label={p.free ? "Free" : "Paid"} />
              </div>

              <p className="mb-3 line-clamp-2 flex-1 text-xs leading-relaxed text-slate-400">{p.description}</p>

              <SpecBox
                rows={[
                  { key: "Top Model", value: p.default_model || "—" },
                  {
                    key: "Access",
                    value: p.requires_api_key ? "API key required" : "No key needed",
                    accent: p.requires_api_key ? "default" : "green",
                  },
                ]}
              />

              <div className="mt-4 flex items-center justify-between">
                <span className="font-mono text-[11px] text-slate-500">
                  {installed ? "✓ installed" : p.free ? "free tier" : "paid"}
                </span>
                <Button variant={installed ? "ghost" : "primary"} onClick={() => setSetup(p)}>
                  {installed ? "Add another" : "Set up →"}
                </Button>
              </div>
            </Card>
          );
        })}
        {presetsForCap.length === 0 && (
          <p className="text-sm text-slate-500">
            No ready-made providers for this type yet. Use “Advanced” below to add a custom one.
          </p>
        )}
      </div>

      {/* Your providers */}
      <h2 className="mb-3 mt-9 text-sm font-semibold text-slate-200">
        Your {CAPS.find((c) => c.key === cap)?.label} providers
      </h2>
      <div className="space-y-2.5">
        {mine.map((p) => (
          <ProviderRow key={p.id} provider={p} />
        ))}
        {mine.length === 0 && <p className="text-sm text-slate-500">None configured yet.</p>}
      </div>

      {/* Advanced custom add */}
      <div className="mt-8">
        <button
          onClick={() => setShowCustom((v) => !v)}
          className="text-sm font-medium text-slate-400 transition hover:text-slate-200"
        >
          {showCustom ? "− Hide advanced" : "+ Advanced: add a custom provider"}
        </button>
        {showCustom && (
          <div className="mt-4">
            <CustomProviderForm defaultCapability={cap} />
          </div>
        )}
      </div>

      {setup && (
        <SetupModal
          preset={setup}
          onClose={() => setSetup(null)}
          onDone={() => {
            setSetup(null);
            qc.invalidateQueries({ queryKey: ["providers"] });
          }}
        />
      )}
    </div>
  );
}

type ProviderModal = "edit" | "models" | "keys" | "history" | null;

function ProviderRow({ provider }: { provider: Provider }) {
  const qc = useQueryClient();
  const [test, setTest] = useState<string>("");
  const [autoFixReport, setAutoFixReport] = useState<string>("");
  const [modal, setModal] = useState<ProviderModal>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["providers"] });

  const runTest = useMutation({
    mutationFn: () => api.post<{ ok: boolean; detail: string }>(`/providers/${provider.id}/test`),
    onSuccess: (r) => {
      setTest(r.ok ? `OK: ${r.detail}` : `FAIL: ${r.detail}`);
      invalidate();
    },
    onError: (e) => setTest(`Error: ${(e as Error).message}`),
  });
  const autoFix = useMutation({
    mutationFn: () => api.post<AutoFixResult>(`/providers/${provider.id}/auto-fix`),
    onSuccess: (r) => {
      setAutoFixReport(r.report);
      invalidate();
    },
  });
  const toggleEnabled = useMutation({
    mutationFn: () => api.patch<Provider>(`/providers/${provider.id}`, { enabled: !provider.enabled }),
    onSuccess: invalidate,
  });
  const clone = useMutation({
    mutationFn: () => api.post<Provider>(`/providers/${provider.id}/clone`),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/providers/${provider.id}`),
    onSuccess: invalidate,
  });

  const lastCheck = provider.last_check_at
    ? `${Math.max(0, Math.round((Date.now() - new Date(provider.last_check_at).getTime()) / 1000))}s ago`
    : "never";

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-xs font-bold text-slate-200">
            {provider.name.charAt(0).toUpperCase()}
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-slate-100">{provider.name}</span>
              <Tag>{provider.provider}</Tag>
              <span className="font-mono text-xs text-slate-500">{provider.model || "—"}</span>
              <HealthBadge status={provider.enabled ? provider.status : "disabled"} />
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[11px] text-slate-500">
              <span>{provider.health_score.toFixed(0)}% health</span>
              <span>{provider.latency_ms ? `${provider.latency_ms.toFixed(0)}ms` : "—"}</span>
              <span>{provider.keys_count} key{provider.keys_count === 1 ? "" : "s"}</span>
              <span>{provider.models_count} model{provider.models_count === 1 ? "" : "s"}</span>
              <span>priority {provider.priority}</span>
              <span>last check {lastCheck}</span>
            </div>
            {(test || autoFixReport) && (
              <p className="mt-1 text-[11px] text-slate-400">{autoFixReport || test}</p>
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          <Button variant="ghost" onClick={() => setModal("edit")}>Edit</Button>
          <Button variant="ghost" onClick={() => runTest.mutate()} disabled={runTest.isPending}>
            {runTest.isPending ? "Testing…" : "Test"}
          </Button>
          <Button variant="ghost" onClick={() => setModal("models")}>Models</Button>
          <Button variant="ghost" onClick={() => setModal("keys")}>API Keys</Button>
          <Button variant="ghost" onClick={() => setModal("history")}>History</Button>
          <Button variant="ghost" onClick={() => autoFix.mutate()} disabled={autoFix.isPending}>
            {autoFix.isPending ? "Fixing…" : "Auto Fix"}
          </Button>
          <Button variant="ghost" onClick={() => clone.mutate()} disabled={clone.isPending}>Clone</Button>
          <Button variant="ghost" onClick={() => toggleEnabled.mutate()} disabled={toggleEnabled.isPending}>
            {provider.enabled ? "Disable" : "Enable"}
          </Button>
          <Button variant="danger" onClick={() => remove.mutate()}>Delete</Button>
        </div>
      </div>

      {modal === "edit" && <EditProviderModal provider={provider} onClose={() => setModal(null)} />}
      {modal === "models" && <ModelsPanel provider={provider} onClose={() => setModal(null)} />}
      {modal === "keys" && <KeysPanel provider={provider} onClose={() => setModal(null)} />}
      {modal === "history" && <HistoryPanel provider={provider} onClose={() => setModal(null)} />}
    </Card>
  );
}

function SetupModal({
  preset,
  onClose,
  onDone,
}: {
  preset: ProviderPreset;
  onClose: () => void;
  onDone: () => void;
}) {
  const [name, setName] = useState(preset.display_name);
  const [model, setModel] = useState(preset.default_model);
  const [apiKey, setApiKey] = useState("");
  const [endpoint, setEndpoint] = useState(preset.default_endpoint);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const create = useMutation({
    mutationFn: () =>
      api.post<Provider>("/providers", {
        name,
        capability: preset.capability,
        provider: preset.provider,
        api_key: apiKey,
        endpoint,
        model,
      }),
    onSuccess: onDone,
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="max-h-[85vh] w-full max-w-2xl animate-fadein overflow-y-auto rounded-2xl border border-white/10 bg-panel p-6 shadow-glow"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-slate-50">{preset.display_name}</h2>
              <TypeBadge label={preset.free ? "Free" : "Paid"} />
            </div>
            <p className="mt-0.5 text-xs text-slate-400">{preset.free_details}</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-500 transition hover:bg-white/5 hover:text-slate-200">✕</button>
        </div>

        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {/* Guide */}
          <div>
            <h3 className="mb-3 text-sm font-semibold text-slate-200">How to set it up</h3>
            <ol className="space-y-2.5">
              {preset.setup_steps.map((s, i) => (
                <li key={i} className="flex gap-2.5 text-sm text-slate-300">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-brand-500/30 bg-brand-500/10 text-[11px] font-semibold text-brand-300">
                    {i + 1}
                  </span>
                  <span>{s}</span>
                </li>
              ))}
            </ol>
            <div className="mt-4 flex flex-wrap gap-2">
              {preset.signup_url && (
                <a href={preset.signup_url} target="_blank" rel="noreferrer">
                  <Button>Get API key ↗</Button>
                </a>
              )}
              {preset.docs_url && (
                <a href={preset.docs_url} target="_blank" rel="noreferrer">
                  <Button variant="ghost">Docs ↗</Button>
                </a>
              )}
            </div>
          </div>

          {/* Form */}
          <div className="space-y-3">
            <Field label="Name">
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            {preset.suggested_models.length > 0 && (
              <Field label="Model">
                <Input
                  list={`models-${preset.id}`}
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                />
                <datalist id={`models-${preset.id}`}>
                  {preset.suggested_models.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
              </Field>
            )}
            {preset.requires_api_key && (
              <Field label={preset.api_key_label}>
                <Input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="paste your key"
                />
              </Field>
            )}
            <button
              onClick={() => setShowAdvanced((v) => !v)}
              className="text-xs text-slate-500 transition hover:text-slate-300"
            >
              {showAdvanced ? "− Hide endpoint" : "Advanced: edit endpoint"}
            </button>
            {showAdvanced && (
              <Field label="Endpoint">
                <Input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} />
              </Field>
            )}

            <div className="pt-2">
              <Button
                onClick={() => create.mutate()}
                disabled={create.isPending || (preset.requires_api_key && !apiKey)}
              >
                {create.isPending ? "Adding…" : "Add provider"}
              </Button>
              {create.error && (
                <p className="mt-2 text-xs text-rose-400">{(create.error as Error).message}</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function CustomProviderForm({ defaultCapability }: { defaultCapability: Capability }) {
  const qc = useQueryClient();
  const catalog = useQuery({
    queryKey: ["provider-catalog"],
    queryFn: () => api.get<ProviderCatalogEntry[]>("/providers/catalog"),
  });
  const [form, setForm] = useState({
    name: "",
    capability: defaultCapability,
    provider: "",
    api_key: "",
    endpoint: "",
    model: "",
  });
  const options = (catalog.data ?? []).filter((c) => c.capability === form.capability);
  const create = useMutation({
    mutationFn: () => api.post<Provider>("/providers", form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["providers"] });
      setForm({ ...form, name: "", api_key: "", model: "" });
    },
  });

  const selectClass =
    "w-full rounded-lg border border-white/10 bg-inset/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/25";

  return (
    <Section title="Custom provider" description="Add any registered provider implementation manually" icon={<IconPlug width={16} height={16} />}>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Field label="Capability">
          <select
            className={selectClass}
            value={form.capability}
            onChange={(e) => setForm({ ...form, capability: e.target.value as Capability, provider: "" })}
          >
            {["llm", "image", "video", "tts", "stt", "music", "search", "publish", "media"].map((c) => (
              <option key={c} value={c} className="bg-panel">{c}</option>
            ))}
          </select>
        </Field>
        <Field label="Implementation">
          <select
            className={selectClass}
            value={form.provider}
            onChange={(e) => {
              const entry = options.find((o) => o.provider_key === e.target.value);
              setForm({
                ...form,
                provider: e.target.value,
                endpoint: entry?.default_endpoint ?? "",
                model: entry?.default_model ?? "",
              });
            }}
          >
            <option value="" className="bg-panel">Select…</option>
            {options.map((o) => (
              <option key={o.provider_key} value={o.provider_key} className="bg-panel">{o.display_name}</option>
            ))}
          </select>
        </Field>
        <Field label="Name">
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="Model">
          <Input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
        </Field>
        <Field label="Endpoint">
          <Input value={form.endpoint} onChange={(e) => setForm({ ...form, endpoint: e.target.value })} />
        </Field>
        <Field label="API key">
          <Input
            type="password"
            value={form.api_key}
            onChange={(e) => setForm({ ...form, api_key: e.target.value })}
          />
        </Field>
      </div>
      <div className="mt-3">
        <Button onClick={() => create.mutate()} disabled={!form.provider || !form.name || create.isPending}>
          <IconPlug width={14} height={14} /> Add custom provider
        </Button>
      </div>
    </Section>
  );
}

/* ---------------------------------------------------- Curated TTS extras */

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

/* -------------------------------------------------- Curated media extras */

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

/* --------------------------------------------------------- Pipeline tab */

function PipelineTuning() {
  const qc = useQueryClient();
  const configs = useQuery({
    queryKey: ["agent-configs"],
    queryFn: () => api.get<AgentConfig[]>("/agents?project_id="),
  });
  const providers = useQuery({
    queryKey: ["providers", "llm"],
    queryFn: () => api.get<Provider[]>("/providers?capability=llm"),
  });
  const prompts = useQuery({ queryKey: ["prompts"], queryFn: () => api.get<Prompt[]>("/prompts") });
  const seed = useMutation({
    mutationFn: () => api.post("/admin/seed"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-configs"] });
      qc.invalidateQueries({ queryKey: ["prompts"] });
    },
  });

  const globals = (configs.data ?? []).filter((c) => c.project_id === null);

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-2xl text-sm text-slate-500">
          Global defaults for the pipeline — which provider each agent uses, its model/temperature, and the
          prompt templates they run. Advanced: most people never need to touch this.
        </p>
        <Button variant="ghost" onClick={() => seed.mutate()} disabled={seed.isPending}>
          {seed.isPending ? "Seeding…" : "Seed defaults"}
        </Button>
      </div>

      <h2 className="mb-3 text-sm font-semibold text-slate-200">Agent configuration</h2>
      <div className="space-y-3">
        {globals.map((c) => (
          <AgentRow key={c.id} config={c} providers={providers.data ?? []} />
        ))}
        {globals.length === 0 && (
          <p className="text-sm text-slate-500">No agent configs. Click “Seed defaults”.</p>
        )}
      </div>

      <h2 className="mb-3 mt-9 text-sm font-semibold text-slate-200">Prompt manager</h2>
      <div className="space-y-3">
        {prompts.data?.map((p) => <PromptRow key={p.id} prompt={p} />)}
        {prompts.data?.length === 0 && (
          <p className="text-sm text-slate-500">No prompts. Click “Seed defaults” above.</p>
        )}
      </div>
    </div>
  );
}

function AgentRow({ config, providers }: { config: AgentConfig; providers: Provider[] }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState(config);
  const save = useMutation({
    mutationFn: () =>
      api.patch(`/agents/${config.id}`, {
        model: draft.model,
        temperature: draft.temperature,
        max_tokens: draft.max_tokens,
        system_prompt: draft.system_prompt,
        provider_config_id: draft.provider_config_id,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-configs"] }),
  });

  return (
    <Card>
      <div className="mb-3 flex items-center gap-2">
        <span className="h-1.5 w-1.5 rounded-full bg-gradient-to-r from-brand-400 to-violet-500" />
        <span className="font-mono text-sm font-semibold text-slate-100">{config.agent_type}</span>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <label className="text-xs text-slate-400">
          Provider
          <select
            className="mt-1 w-full rounded-lg border border-white/10 bg-inset/70 px-2 py-1.5 text-sm text-slate-100 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/25"
            value={draft.provider_config_id ?? ""}
            onChange={(e) => setDraft({ ...draft, provider_config_id: e.target.value || null })}
          >
            <option value="">Auto (router + fallback)</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-slate-400">
          Model
          <input
            className="mt-1 w-full rounded-lg border border-white/10 bg-inset/70 px-2 py-1.5 text-sm text-slate-100 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/25"
            value={draft.model}
            onChange={(e) => setDraft({ ...draft, model: e.target.value })}
          />
        </label>
        <label className="text-xs text-slate-400">
          Temperature
          <input
            type="number"
            step="0.1"
            className="mt-1 w-full rounded-lg border border-white/10 bg-inset/70 px-2 py-1.5 text-sm text-slate-100 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/25"
            value={draft.temperature}
            onChange={(e) => setDraft({ ...draft, temperature: Number(e.target.value) })}
          />
        </label>
        <label className="text-xs text-slate-400">
          Max tokens
          <input
            type="number"
            className="mt-1 w-full rounded-lg border border-white/10 bg-inset/70 px-2 py-1.5 text-sm text-slate-100 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/25"
            value={draft.max_tokens}
            onChange={(e) => setDraft({ ...draft, max_tokens: Number(e.target.value) })}
          />
        </label>
      </div>
      <label className="mt-3 block text-xs text-slate-400">
        System prompt
        <textarea
          className="mt-1 h-20 w-full rounded-lg border border-white/10 bg-inset/70 px-2 py-1.5 font-mono text-xs text-slate-100 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/25"
          value={draft.system_prompt}
          onChange={(e) => setDraft({ ...draft, system_prompt: e.target.value })}
        />
      </label>
      <div className="mt-3">
        <Button onClick={() => save.mutate()} disabled={save.isPending}>Save</Button>
      </div>
    </Card>
  );
}

function PromptRow({ prompt }: { prompt: Prompt }) {
  const qc = useQueryClient();
  const [content, setContent] = useState(prompt.content);
  const [testOut, setTestOut] = useState("");

  const save = useMutation({
    mutationFn: () => api.patch(`/prompts/${prompt.id}`, { content }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prompts"] }),
  });
  const test = useMutation({
    mutationFn: () => api.post<{ provider: string; output: string }>(`/prompts/${prompt.id}/test`),
    onSuccess: (r) => setTestOut(`${r.provider}: ${r.output}`),
    onError: (e) => setTestOut(`Error: ${(e as Error).message}`),
  });

  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-slate-100">{prompt.name}</span>
          <span className="font-mono text-xs text-slate-500">
            v{prompt.version} · {prompt.agent_type ?? "general"}
          </span>
          {prompt.is_default && <Tag color="brand">default</Tag>}
        </div>
      </div>
      <textarea
        className="h-40 w-full rounded-lg border border-white/10 bg-inset/70 px-3 py-2 font-mono text-xs text-slate-100 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/25"
        value={content}
        onChange={(e) => setContent(e.target.value)}
      />
      <div className="mt-2 flex items-center gap-2">
        <Button onClick={() => save.mutate()} disabled={save.isPending}>Save (bumps version)</Button>
        <Button variant="ghost" onClick={() => test.mutate()} disabled={test.isPending}>Test</Button>
        {testOut && <span className="text-xs text-slate-400">{testOut}</span>}
      </div>
    </Card>
  );
}
