import type { ReactNode } from "react";

/**
 * Generic modal shell, extracted from the ad-hoc overlay the provider
 * "Setup" dialog used to build inline. Every provider dialog (Edit, Models,
 * API Keys, History) shares this so they stay visually consistent.
 */
export function Modal({
  onClose,
  children,
  maxWidthClass = "max-w-2xl",
}: {
  onClose: () => void;
  children: ReactNode;
  maxWidthClass?: string;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className={`max-h-[85vh] w-full ${maxWidthClass} animate-fadein overflow-y-auto rounded-2xl border border-white/10 bg-panel p-6 shadow-glow`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

export function ModalHeader({
  title,
  subtitle,
  onClose,
  badge,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  badge?: ReactNode;
}) {
  return (
    <div className="mb-5 flex items-start justify-between">
      <div>
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-bold text-slate-50">{title}</h2>
          {badge}
        </div>
        {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
      </div>
      <button
        onClick={onClose}
        className="rounded-lg p-1 text-slate-500 transition hover:bg-white/5 hover:text-slate-200"
      >
        ✕
      </button>
    </div>
  );
}
