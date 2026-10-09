import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Provider, ProviderConfigHistoryEntry, ProviderEvent } from "@/api/types";
import { Button, Tag } from "@/components/ui";
import { Modal, ModalHeader } from "@/components/Modal";

const SOURCE_COLOR: Record<string, "slate" | "violet" | "brand"> = {
  manual: "slate",
  auto_fix: "violet",
  auto_recovery: "violet",
};

/** Config history + rollback (sections 25/40) and the provider's recent
 * observability events (section 26), in one panel. */
export function HistoryPanel({ provider, onClose }: { provider: Provider; onClose: () => void }) {
  const qc = useQueryClient();

  const historyQuery = useQuery({
    queryKey: ["provider-history", provider.id],
    queryFn: () => api.get<ProviderConfigHistoryEntry[]>(`/providers/${provider.id}/history`),
  });
  const eventsQuery = useQuery({
    queryKey: ["provider-events", provider.id],
    queryFn: () => api.get<ProviderEvent[]>(`/providers/${provider.id}/events`),
  });

  const rollback = useMutation({
    mutationFn: (snapshotId: string) =>
      api.post<Provider>(`/providers/${provider.id}/history/${snapshotId}/rollback`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["provider-history", provider.id] });
      qc.invalidateQueries({ queryKey: ["providers"] });
    },
  });

  const history = historyQuery.data ?? [];
  const events = eventsQuery.data ?? [];

  return (
    <Modal onClose={onClose} maxWidthClass="max-w-3xl">
      <ModalHeader title={`History — ${provider.name}`} onClose={onClose} />
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Config snapshots
          </h3>
          {history.length === 0 && <p className="text-sm text-slate-500">No changes recorded yet.</p>}
          <div className="max-h-96 space-y-2 overflow-y-auto">
            {history.map((h) => (
              <div key={h.id} className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
                <div className="flex items-center justify-between gap-2">
                  <Tag color={SOURCE_COLOR[h.source] ?? "slate"}>{h.source}</Tag>
                  <span className="text-[11px] text-slate-500">
                    {new Date(h.created_at).toLocaleString()}
                  </span>
                </div>
                <p className="mt-1.5 text-xs text-slate-300">{h.reason}</p>
                <p className="mt-1 font-mono text-[11px] text-slate-500">
                  model: {String(h.snapshot.model ?? "—")}
                </p>
                <Button
                  variant="ghost"
                  className="mt-2"
                  onClick={() => rollback.mutate(h.id)}
                  disabled={rollback.isPending}
                >
                  Rollback to this
                </Button>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Recent events
          </h3>
          {events.length === 0 && <p className="text-sm text-slate-500">No events recorded yet.</p>}
          <div className="max-h-96 space-y-1.5 overflow-y-auto">
            {events.map((e) => (
              <div key={e.id} className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] text-slate-300">{e.event_type}</span>
                  <span className="text-[10px] text-slate-500">
                    {new Date(e.created_at).toLocaleTimeString()}
                  </span>
                </div>
                {e.message && <p className="mt-1 text-[11px] text-slate-500">{e.message}</p>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
}
