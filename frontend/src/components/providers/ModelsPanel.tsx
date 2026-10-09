import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { AutoFixResult, Provider, ProviderModel } from "@/api/types";
import { Button, Tag } from "@/components/ui";
import { Modal, ModalHeader } from "@/components/Modal";

/** Model management panel (section 41): current/fallback/discovered models,
 * plus a one-click Auto-select that runs the backend's auto-fix flow. */
export function ModelsPanel({ provider, onClose }: { provider: Provider; onClose: () => void }) {
  const qc = useQueryClient();
  const [autoFixReport, setAutoFixReport] = useState<string | null>(null);

  const modelsQuery = useQuery({
    queryKey: ["provider-models", provider.id],
    queryFn: () => api.get<ProviderModel[]>(`/providers/${provider.id}/models`),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["provider-models", provider.id] });
    qc.invalidateQueries({ queryKey: ["providers"] });
  };

  const discover = useMutation({
    mutationFn: () => api.post<ProviderModel[]>(`/providers/${provider.id}/models/discover`),
    onSuccess: (data) => {
      qc.setQueryData(["provider-models", provider.id], data);
      qc.invalidateQueries({ queryKey: ["providers"] });
    },
  });

  const setPrimary = useMutation({
    mutationFn: (model: string) =>
      api.post<Provider>(`/providers/${provider.id}/models/set-primary`, { model }),
    onSuccess: invalidate,
  });

  const addFallback = useMutation({
    mutationFn: (model: string) =>
      api.post<Provider>(`/providers/${provider.id}/models/fallback`, { model }),
    onSuccess: invalidate,
  });

  const removeFallback = useMutation({
    mutationFn: (model: string) =>
      api.del(`/providers/${provider.id}/models/fallback/${encodeURIComponent(model)}`),
    onSuccess: invalidate,
  });

  const autoSelect = useMutation({
    mutationFn: () => api.post<AutoFixResult>(`/providers/${provider.id}/auto-fix`),
    onSuccess: (r) => {
      setAutoFixReport(r.report);
      invalidate();
    },
  });

  const models = modelsQuery.data ?? [];
  const fallbacks = provider.fallback_models ?? [];

  return (
    <Modal onClose={onClose} maxWidthClass="max-w-3xl">
      <ModalHeader title={`Models — ${provider.name}`} onClose={onClose} />
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-slate-400">Current model:</span>
          <Tag color="brand">{provider.model || "—"}</Tag>
          <Button variant="ghost" onClick={() => discover.mutate()} disabled={discover.isPending}>
            {discover.isPending ? "Refreshing…" : "Refresh models"}
          </Button>
          <Button variant="ghost" onClick={() => autoSelect.mutate()} disabled={autoSelect.isPending}>
            {autoSelect.isPending ? "Running…" : "Auto Fix"}
          </Button>
        </div>

        {autoFixReport && (
          <p className="rounded-lg border border-white/10 bg-white/5 p-3 text-xs text-slate-300">
            {autoFixReport}
          </p>
        )}

        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Fallback models
          </h3>
          {fallbacks.length === 0 && (
            <p className="text-sm text-slate-500">
              None configured — on a model error, this provider has nothing else to fall back to.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {fallbacks.map((m) => (
              <span
                key={m}
                className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-slate-300"
              >
                {m}
                <button
                  onClick={() => removeFallback.mutate(m)}
                  className="text-slate-500 hover:text-rose-400"
                  title="Remove fallback"
                >
                  ✕
                </button>
              </span>
            ))}
          </div>
        </div>

        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Discovered models {models.length > 0 && `(${models.length})`}
          </h3>
          {modelsQuery.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
          {!modelsQuery.isLoading && models.length === 0 && (
            <p className="text-sm text-slate-500">
              Discovery isn't supported by this provider implementation, or returned nothing yet —
              try "Refresh models".
            </p>
          )}
          <div className="max-h-64 space-y-1.5 overflow-y-auto">
            {models.map((m) => (
              <div
                key={m.id}
                className="flex items-center justify-between rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2"
              >
                <div className="flex items-center gap-2 overflow-hidden">
                  <span className="truncate font-mono text-xs text-slate-200">{m.id}</span>
                  {m.id === provider.model && <Tag color="brand">primary</Tag>}
                  {m.deprecated && <Tag color="amber">deprecated</Tag>}
                </div>
                <div className="flex shrink-0 gap-1.5">
                  <Button
                    variant="ghost"
                    onClick={() => setPrimary.mutate(m.id)}
                    disabled={m.id === provider.model}
                  >
                    Set primary
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => addFallback.mutate(m.id)}
                    disabled={fallbacks.includes(m.id)}
                  >
                    Add fallback
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
}
