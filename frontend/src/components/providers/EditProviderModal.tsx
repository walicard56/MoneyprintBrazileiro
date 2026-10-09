import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Provider } from "@/api/types";
import { Button, Field, Input, Toggle } from "@/components/ui";
import { Modal, ModalHeader } from "@/components/Modal";

/**
 * Edit flow for an existing provider (section 21/22): load the current
 * config into a draft, let the user change it, and never let a bad edit
 * replace a working provider.
 *
 * The frontend never holds the plaintext stored key, so a draft that keeps
 * the existing key (api_key left blank) can't be fully re-validated here —
 * only a draft that includes a *new* key can be tested end-to-end before
 * saving. That's exactly the case where this guard matters most: rotating a
 * key is the edit most likely to silently break a provider.
 */
export function EditProviderModal({
  provider,
  onClose,
}: {
  provider: Provider;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState({
    name: provider.name,
    endpoint: provider.endpoint,
    model: provider.model,
    api_key: "",
    priority: provider.priority,
    enabled: provider.enabled,
    is_fallback: provider.is_fallback,
  });
  const [validation, setValidation] = useState<{ ok: boolean; detail: string } | null>(null);

  const testDraft = useMutation({
    mutationFn: () =>
      api.post<{ ok: boolean; detail: string }>("/providers/validate", {
        capability: provider.capability,
        provider: provider.provider,
        api_key: draft.api_key,
        endpoint: draft.endpoint,
        model: draft.model,
      }),
    onSuccess: (r) => setValidation(r),
  });

  const save = useMutation({
    mutationFn: async () => {
      // Rotating the key: validate the NEW key before ever saving it.
      if (draft.api_key) {
        const result = await api.post<{ ok: boolean; detail: string }>("/providers/validate", {
          capability: provider.capability,
          provider: provider.provider,
          api_key: draft.api_key,
          endpoint: draft.endpoint,
          model: draft.model,
        });
        setValidation(result);
        if (!result.ok) {
          throw new Error(`New key failed validation, nothing was saved: ${result.detail}`);
        }
      }
      return api.patch<Provider>(`/providers/${provider.id}`, {
        name: draft.name,
        endpoint: draft.endpoint,
        model: draft.model,
        ...(draft.api_key ? { api_key: draft.api_key } : {}),
        priority: draft.priority,
        enabled: draft.enabled,
        is_fallback: draft.is_fallback,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["providers"] });
      onClose();
    },
  });

  return (
    <Modal onClose={onClose}>
      <ModalHeader title={`Edit ${provider.name}`} onClose={onClose} />
      <div className="space-y-3">
        <Field label="Name">
          <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        </Field>
        <Field label="Model">
          <Input value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} />
        </Field>
        <Field label="Endpoint">
          <Input value={draft.endpoint} onChange={(e) => setDraft({ ...draft, endpoint: e.target.value })} />
        </Field>
        <Field
          label={
            provider.has_api_key
              ? `API key (blank keeps the current one — ${provider.api_key_masked})`
              : "API key"
          }
        >
          <Input
            type="password"
            value={draft.api_key}
            onChange={(e) => setDraft({ ...draft, api_key: e.target.value })}
            placeholder="paste a new key, or leave blank to keep the current one"
          />
        </Field>
        <Field label="Priority (lower is tried first)">
          <Input
            type="number"
            value={draft.priority}
            onChange={(e) => setDraft({ ...draft, priority: Number(e.target.value) })}
          />
        </Field>
        <div className="flex items-center gap-5 pt-1">
          <Toggle checked={draft.enabled} onChange={(v) => setDraft({ ...draft, enabled: v })} label="Enabled" />
          <Toggle
            checked={draft.is_fallback}
            onChange={(v) => setDraft({ ...draft, is_fallback: v })}
            label="Part of fallback chain"
          />
        </div>

        {validation && (
          <p className={`text-xs ${validation.ok ? "text-emerald-400" : "text-rose-400"}`}>
            {validation.ok ? "✓ " : "✗ "}
            {validation.detail}
          </p>
        )}
        {!draft.api_key && (
          <p className="text-[11px] text-slate-500">
            Keeping the current key means "Test draft" can only check the endpoint/model, not
            authentication — use the card's own Test button after saving to confirm the full
            config still works.
          </p>
        )}

        <div className="flex items-center justify-between pt-2">
          <Button variant="ghost" onClick={() => testDraft.mutate()} disabled={testDraft.isPending}>
            {testDraft.isPending ? "Testing…" : "Test draft"}
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
        {save.error && <p className="text-xs text-rose-400">{(save.error as Error).message}</p>}
      </div>
    </Modal>
  );
}
