import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Project } from "@/api/types";
import { Button, Card, Field, Input, PageHeader } from "@/components/ui";

export default function Projects() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  const [form, setForm] = useState({
    name: "",
    niche: "",
    language: "Portuguese",
    style: "cinematic",
    default_duration: 45,
  });

  const create = useMutation({
    mutationFn: () => api.post<Project>("/projects", form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      setForm({ ...form, name: "", niche: "" });
    },
  });

  return (
    <div>
      <PageHeader
        eyebrow="Your channels & niches"
        title={<>Projects</>}
        subtitle="Each project is a channel with its own defaults — language, style, duration."
      />
      <Card className="mb-6">
        <h2 className="mb-4 text-sm font-semibold text-slate-200">New project</h2>
        <form
          className="grid grid-cols-1 gap-3 md:grid-cols-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <Field label="Name">
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </Field>
          <Field label="Niche">
            <Input value={form.niche} onChange={(e) => setForm({ ...form, niche: e.target.value })} />
          </Field>
          <Field label="Language">
            <Input value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })} />
          </Field>
          <Field label="Style">
            <Input value={form.style} onChange={(e) => setForm({ ...form, style: e.target.value })} />
          </Field>
          <Field label="Default duration (s)">
            <Input
              type="number"
              value={form.default_duration}
              onChange={(e) => setForm({ ...form, default_duration: Number(e.target.value) })}
            />
          </Field>
          <div className="flex items-end">
            <Button type="submit" disabled={!form.name || create.isPending}>Create</Button>
          </div>
        </form>
      </Card>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {data?.map((p) => (
          <Card key={p.id} interactive>
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500/80 to-violet-600/80 text-sm font-bold text-white">
                  {p.name.charAt(0).toUpperCase()}
                </div>
                <div>
                  <div className="font-semibold text-slate-100">{p.name}</div>
                  <div className="text-xs text-slate-500">{p.niche || "no niche"} · {p.language}</div>
                </div>
              </div>
              <span className="font-mono text-xs text-slate-500">{p.default_duration}s</span>
            </div>
            <div className="mt-4 flex gap-2">
              <Link to={`/videos?project=${p.id}`}>
                <Button variant="ghost">Videos</Button>
              </Link>
            </div>
          </Card>
        ))}
        {data?.length === 0 && <p className="text-sm text-slate-500">No projects yet.</p>}
      </div>
    </div>
  );
}
