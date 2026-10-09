import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Provider, ProviderApiKey } from "@/api/types";
import { Button, Field, Input, Tag } from "@/components/ui";
import { Modal, ModalHeader } from "@/components/Modal";

const KEY_STATUS_COLOR: Record<string, "slate" | "emerald" | "amber" | "brand"> = {
  active: "emerald",
  cooldown: "amber",
  invalid: "slate",
  disabled: "slate",
};

/** API Keys panel (section 42): a provider's key pool, each tested and
 * managed independently of the others. */
export function KeysPanel({ provider, onClose }: { provider: Provider; onClose: () => void }) {
  const qc = useQueryClient();
  const [newKey, setNewKey] = useState({ label: "", api_key: "" });
  const [testResults, setTestResults] = useState<Record<string, string>>({});

  const keysQuery = useQuery({
    queryKey: ["provider-keys", provider.id],
    queryFn: () => api.get<ProviderApiKey[]>(`/providers/${provider.id}/keys`),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["provider-keys", provider.id] });
    qc.invalidateQueries({ queryKey: ["providers"] });
  };

  const addKey = useMutation({
    mutationFn: () => api.post<ProviderApiKey>(`/providers/${provider.id}/keys`, newKey),
    onSuccess: () => {
      setNewKey({ label: "", api_key: "" });
      invalidate();
    },
  });

  const testKey = useMutation({
    mutationFn: (keyId: string) =>
      api.post<{ ok: boolean; detail: string }>(`/providers/${provider.id}/keys/${keyId}/test`),
    onSuccess: (r, keyId) => {
      setTestResults((prev) => ({ ...prev, [keyId]: r.ok ? `OK: ${r.detail}` : `FAIL: ${r.detail}` }));
      invalidate();
    },
  });

  const setStatus = useMutation({
    mutationFn: ({ keyId, status }: { keyId: string; status: string }) =>
      api.patch(`/providers/${provider.id}/keys/${keyId}`, { status }),
    onSuccess: invalidate,
  });

  const removeKey = useMutation({
    mutationFn: (keyId: string) => api.del(`/providers/${provider.id}/keys/${keyId}`),
    onSuccess: invalidate,
  });

  const keys = keysQuery.data ?? [];

  return (
    <Modal onClose={onClose}>
      <ModalHeader title={`API keys — ${provider.name}`} onClose={onClose} />
      <div className="space-y-3">
        {keys.length === 0 && (
          <p className="text-sm text-slate-500">
            No keys in the pool yet — the provider is using its single legacy key. Add one below to
            start rotating between multiple keys.
          </p>
        )}
        {keys.map((k) => (
          <div
            key={k.id}
            className="rounded-xl border border-white/10 bg-white/[0.03] p-3.5"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="font-medium text-slate-100">{k.label || "(unlabeled)"}</span>
                <Tag color={KEY_STATUS_COLOR[k.status] ?? "slate"}>{k.status}</Tag>
                <span className="font-mono text-xs text-slate-500">{k.api_key_masked}</span>
              </div>
              <div className="flex gap-1.5">
                <Button variant="ghost" onClick={() => testKey.mutate(k.id)} disabled={testKey.isPending}>
                  Test
                </Button>
                {k.status === "disabled" ? (
                  <Button variant="ghost" onClick={() => setStatus.mutate({ keyId: k.id, status: "active" })}>
                    Enable
                  </Button>
                ) : (
                  <Button variant="ghost" onClick={() => setStatus.mutate({ keyId: k.id, status: "disabled" })}>
                    Disable
                  </Button>
                )}
                <Button variant="danger" onClick={() => removeKey.mutate(k.id)}>
                  Remove
                </Button>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-3 font-mono text-[11px] text-slate-500">
              <span>health {k.health_score.toFixed(0)}%</span>
              <span>
                success {k.success_count} / fail {k.failure_count}
              </span>
              {k.cooldown_until && <span className="text-amber-400">cooldown until {new Date(k.cooldown_until).toLocaleTimeString()}</span>}
              {testResults[k.id] && <span className="text-slate-400">· {testResults[k.id]}</span>}
            </div>
          </div>
        ))}

        <div className="rounded-xl border border-dashed border-white/15 p-3.5">
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            <Field label="Label (optional)">
              <Input value={newKey.label} onChange={(e) => setNewKey({ ...newKey, label: e.target.value })} />
            </Field>
            <Field label="API key">
              <Input
                type="password"
                value={newKey.api_key}
                onChange={(e) => setNewKey({ ...newKey, api_key: e.target.value })}
              />
            </Field>
          </div>
          <div className="mt-2.5">
            <Button onClick={() => addKey.mutate()} disabled={!newKey.api_key || addKey.isPending}>
              {addKey.isPending ? "Adding…" : "Add key"}
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
