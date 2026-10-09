import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button, Card, Field, Input, PageHeader } from "@/components/ui";

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
      <PageHeader
        eyebrow="Workspace configuration"
        title={<>Settings</>}
      />

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
