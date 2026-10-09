import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Prompt } from "@/api/types";
import { Button, Card, PageHeader, Tag } from "@/components/ui";

export default function Prompts() {
  const { data } = useQuery({ queryKey: ["prompts"], queryFn: () => api.get<Prompt[]>("/prompts") });
  return (
    <div>
      <PageHeader
        eyebrow="Edit without touching code"
        title={<>Prompt <span className="gradient-text">Manager</span></>}
      />
      <div className="space-y-3">
        {data?.map((p) => <PromptRow key={p.id} prompt={p} />)}
        {data?.length === 0 && (
          <p className="text-sm text-slate-500">
            No prompts. Seed defaults from the Agents page.
          </p>
        )}
      </div>
    </div>
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
