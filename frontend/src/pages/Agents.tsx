import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { AgentConfig, Provider } from "@/api/types";
import { Button, Card, PageHeader } from "@/components/ui";
import { useState } from "react";

export default function Agents() {
  const qc = useQueryClient();
  const configs = useQuery({
    queryKey: ["agent-configs"],
    queryFn: () => api.get<AgentConfig[]>("/agents?project_id="),
  });
  const providers = useQuery({
    queryKey: ["providers", "llm"],
    queryFn: () => api.get<Provider[]>("/providers?capability=llm"),
  });
  const seed = useMutation({
    mutationFn: () => api.post("/admin/seed"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-configs"] }),
  });

  const globals = (configs.data ?? []).filter((c) => c.project_id === null);

  return (
    <div>
      <PageHeader
        eyebrow="Fine-tune the pipeline"
        title={<>Agent <span className="gradient-text">configuration</span></>}
        action={<Button variant="ghost" onClick={() => seed.mutate()}>Seed defaults</Button>}
      />
      <p className="mb-4 text-sm text-slate-500">
        Global defaults. Each agent can be pinned to a provider and tuned without touching code.
      </p>
      <div className="space-y-3">
        {globals.map((c) => (
          <AgentRow key={c.id} config={c} providers={providers.data ?? []} />
        ))}
        {globals.length === 0 && (
          <p className="text-sm text-slate-500">No agent configs. Click “Seed defaults”.</p>
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
