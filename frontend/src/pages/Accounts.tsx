import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Account } from "@/api/types";
import { Button, Card, Field, Input, PageHeader, StatusBadge, Tag } from "@/components/ui";

const PLATFORMS = ["tiktok", "youtube", "facebook", "instagram"];

export default function Accounts() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  const [form, setForm] = useState({ name: "", platform: "tiktok", socialIds: "" });

  const create = useMutation({
    mutationFn: () =>
      api.post<Account>("/accounts", {
        name: form.name,
        platform: form.platform,
        params: {
          social_account_ids: form.socialIds
            .split(",")
            .map((s) => Number(s.trim()))
            .filter((n) => !Number.isNaN(n)),
        },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setForm({ ...form, name: "", socialIds: "" });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/accounts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });

  return (
    <div>
      <PageHeader
        eyebrow="Where your shorts go live"
        title={<>Publishing <span className="gradient-text">accounts</span></>}
      />
      <Card className="mb-6">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <Field label="Platform">
            <select
              className="w-full rounded-lg border border-white/10 bg-inset/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/25"
              value={form.platform}
              onChange={(e) => setForm({ ...form, platform: e.target.value })}
            >
              {PLATFORMS.map((p) => <option key={p} value={p} className="bg-panel">{p}</option>)}
            </select>
          </Field>
          <Field label="Name">
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Post Bridge account IDs (comma-sep)">
            <Input value={form.socialIds} onChange={(e) => setForm({ ...form, socialIds: e.target.value })} />
          </Field>
          <div className="flex items-end">
            <Button disabled={!form.name || create.isPending} onClick={() => create.mutate()}>Add</Button>
          </div>
        </div>
      </Card>

      <div className="space-y-2">
        {data?.map((a) => (
          <Card key={a.id} className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-slate-100">{a.name}</span>
              <Tag>{a.platform}</Tag>
            </div>
            <div className="flex items-center gap-2">
              {a.enabled ? <StatusBadge status="completed" /> : <StatusBadge status="cancelled" />}
              <Button variant="danger" onClick={() => remove.mutate(a.id)}>Delete</Button>
            </div>
          </Card>
        ))}
        {data?.length === 0 && <p className="text-sm text-slate-500">No accounts yet.</p>}
      </div>
    </div>
  );
}
