import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

export function BackendStatus({ compact = false }: { compact?: boolean }) {
  const { isSuccess, isError } = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<{ status: string }>("/health"),
    refetchInterval: 10000,
    retry: false,
  });

  const ok = isSuccess && !isError;
  const dot = (
    <span className="relative flex h-2 w-2">
      <span
        className={`absolute inline-flex h-full w-full rounded-full opacity-75 ${
          ok ? "animate-ping bg-emerald-400" : "bg-rose-500"
        }`}
      />
      <span className={`relative inline-flex h-2 w-2 rounded-full ${ok ? "bg-emerald-400" : "bg-rose-500"}`} />
    </span>
  );

  if (compact) {
    return (
      <div
        className="hidden items-center gap-2 rounded-full border border-white/10 bg-white/[0.02] px-3 py-1.5 lg:flex"
        title={ok ? "Backend online" : "Backend offline"}
      >
        {dot}
        <span className="font-mono text-[11px] text-slate-400">{ok ? "Online" : "Offline"}</span>
      </div>
    );
  }

  return (
    <div className="mt-4 flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2.5">
      {dot}
      <span className="font-mono text-[11px] text-slate-400">
        {ok ? "Backend online" : "Backend offline"}
      </span>
    </div>
  );
}
