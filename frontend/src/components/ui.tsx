import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import type { Status } from "@/api/types";

/* ---------------------------------------------------------------- Surfaces */

export function Card({
  children,
  className = "",
  interactive = false,
  featured = false,
}: {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
  featured?: boolean;
}) {
  const base = featured ? "card-featured" : interactive ? "card-interactive" : "card-surface";
  return <div className={`${base} p-5 ${className}`}>{children}</div>;
}

export function StatCard({
  label,
  value,
  sub,
  icon,
  accent = "brand",
}: {
  label: string;
  value: ReactNode;
  sub?: string;
  icon?: ReactNode;
  accent?: "brand" | "emerald" | "violet" | "rose" | "amber";
}) {
  const bar = {
    brand: "from-brand-500 to-violet-500",
    emerald: "from-emerald-400 to-teal-400",
    violet: "from-violet-500 to-fuchsia-500",
    rose: "from-rose-500 to-orange-500",
    amber: "from-amber-400 to-orange-500",
  }[accent];
  return (
    <div className="card-surface relative overflow-hidden p-5">
      <div className={`absolute inset-x-0 top-0 h-px bg-gradient-to-r ${bar} opacity-70`} />
      <div className="flex items-start justify-between">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
        {icon && <span className="text-slate-500">{icon}</span>}
      </div>
      <div className="mt-2 text-3xl font-bold tracking-tight text-slate-50">{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ Badges */

const STATUS_STYLES: Record<string, { wrap: string; dot: string }> = {
  pending: { wrap: "border-slate-600/40 bg-slate-600/15 text-slate-300", dot: "bg-slate-400" },
  running: { wrap: "border-brand-500/40 bg-brand-500/15 text-brand-300", dot: "bg-brand-400 animate-pulseglow" },
  completed: { wrap: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300", dot: "bg-emerald-400" },
  failed: { wrap: "border-rose-500/40 bg-rose-500/15 text-rose-300", dot: "bg-rose-400" },
  retry: { wrap: "border-amber-500/40 bg-amber-500/15 text-amber-300", dot: "bg-amber-400" },
  cancelled: { wrap: "border-slate-600/40 bg-slate-700/20 text-slate-400", dot: "bg-slate-500" },
  waiting_approval: { wrap: "border-violet-500/40 bg-violet-500/15 text-violet-300", dot: "bg-violet-400 animate-pulseglow" },
};

export function StatusBadge({ status }: { status: Status | string }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.pending;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${s.wrap}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {String(status).replace(/_/g, " ")}
    </span>
  );
}

const PROVIDER_HEALTH_STYLES: Record<string, { wrap: string; dot: string }> = {
  unknown: { wrap: "border-slate-600/40 bg-slate-600/15 text-slate-300", dot: "bg-slate-400" },
  configured: { wrap: "border-slate-600/40 bg-slate-600/15 text-slate-300", dot: "bg-slate-400" },
  checking: { wrap: "border-brand-500/40 bg-brand-500/15 text-brand-300", dot: "bg-brand-400 animate-pulseglow" },
  healthy: { wrap: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300", dot: "bg-emerald-400" },
  degraded: { wrap: "border-amber-500/40 bg-amber-500/15 text-amber-300", dot: "bg-amber-400" },
  rate_limited: { wrap: "border-amber-500/40 bg-amber-500/15 text-amber-300", dot: "bg-amber-400" },
  auth_error: { wrap: "border-rose-500/40 bg-rose-500/15 text-rose-300", dot: "bg-rose-400" },
  model_error: { wrap: "border-rose-500/40 bg-rose-500/15 text-rose-300", dot: "bg-rose-400" },
  network_error: { wrap: "border-rose-500/40 bg-rose-500/15 text-rose-300", dot: "bg-rose-400" },
  unavailable: { wrap: "border-rose-500/40 bg-rose-500/15 text-rose-300", dot: "bg-rose-400" },
  disabled: { wrap: "border-slate-600/40 bg-slate-700/20 text-slate-400", dot: "bg-slate-500" },
  recovering: { wrap: "border-violet-500/40 bg-violet-500/15 text-violet-300", dot: "bg-violet-400 animate-pulseglow" },
  failed: { wrap: "border-rose-500/40 bg-rose-500/15 text-rose-300", dot: "bg-rose-400" },
};

/** Status pill for a provider's coarse health status (distinct from the
 * pipeline `Status` that `StatusBadge` renders). */
export function HealthBadge({ status }: { status: string }) {
  const s = PROVIDER_HEALTH_STYLES[status] ?? PROVIDER_HEALTH_STYLES.unknown;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${s.wrap}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {status.replace(/_/g, " ")}
    </span>
  );
}

/** Rounded pill tag (feature chips). */
export function Tag({
  children,
  color = "slate",
}: {
  children: ReactNode;
  color?: "slate" | "brand" | "emerald" | "violet" | "amber";
}) {
  const styles = {
    slate: "border-white/10 bg-white/5 text-slate-300",
    brand: "border-brand-500/30 bg-brand-500/10 text-brand-300",
    emerald: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    violet: "border-violet-500/30 bg-violet-500/10 text-violet-300",
    amber: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  }[color];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium ${styles}`}>
      {children}
    </span>
  );
}

/** Top-right type badge (API / LOCAL / PROXY / FREE / PAID …). */
export function TypeBadge({ label }: { label: string }) {
  const key = label.toLowerCase();
  const color =
    key.includes("free") || key === "verified"
      ? "emerald"
      : key.includes("api")
        ? "brand"
        : key.includes("local") || key.includes("proxy") || key.includes("trial") || key.includes("credit")
          ? "violet"
          : "slate";
  const styles = {
    slate: "border-white/15 bg-white/5 text-slate-300",
    brand: "border-brand-500/40 bg-brand-500/15 text-brand-300",
    emerald: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
    violet: "border-violet-500/40 bg-violet-500/15 text-violet-300",
  }[color as "slate" | "brand" | "emerald" | "violet"];
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${styles}`}>
      {label}
    </span>
  );
}

/** Gold "Top Pick" badge. */
export function TopPick({ children = "Top Pick" }: { children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-amber-400/40 bg-amber-400/10 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
      <span className="text-amber-400">★</span>
      {children}
    </span>
  );
}

/** Small blue verified check. */
export function Verified({ title = "Verified" }: { title?: string }) {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" className="text-brand-400" aria-label={title}>
      <path
        fill="currentColor"
        d="M12 2l2.4 1.8 3 .2.9 2.9 2.2 2-1 2.9 1 2.9-2.2 2-.9 2.9-3 .2L12 22l-2.4-1.8-3-.2-.9-2.9-2.2-2 1-2.9-1-2.9 2.2-2 .9-2.9 3-.2z"
      />
      <path fill="#0d1526" d="m10.6 14.6-2-2-1.2 1.2 3.2 3.2 5.6-5.6-1.2-1.2z" />
    </svg>
  );
}

/* ----------------------------------------------------------------- Gradient */

export function GradientText({
  children,
  variant = "blue",
}: {
  children: ReactNode;
  variant?: "blue" | "green";
}) {
  return <span className={variant === "green" ? "gradient-text-green" : "gradient-text"}>{children}</span>;
}

/* ------------------------------------------------------------------ SpecBox */

export function SpecBox({ rows }: { rows: { key: string; value: ReactNode; accent?: "default" | "green" | "blue" }[] }) {
  return (
    <div className="spec-box divide-y divide-white/5">
      {rows.map((r, i) => (
        <div key={i} className="spec-row">
          <span className="spec-key">{r.key}</span>
          <span
            className={
              r.accent === "green"
                ? "font-mono text-xs font-semibold text-emerald-400"
                : r.accent === "blue"
                  ? "font-mono text-xs font-semibold text-brand-300"
                  : "spec-val"
            }
          >
            {r.value}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ Buttons */

export function Button({
  children,
  onClick,
  variant = "primary",
  type = "button",
  disabled,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "danger";
  type?: "button" | "submit";
  disabled?: boolean;
  className?: string;
}) {
  const styles = {
    primary:
      "bg-gradient-to-b from-brand-500 to-brand-600 text-white shadow-[0_8px_22px_-10px_rgba(37,99,235,0.9)] hover:from-brand-400 hover:to-brand-500",
    ghost: "border border-white/10 bg-white/5 text-slate-100 hover:border-white/20 hover:bg-white/10",
    danger: "bg-gradient-to-b from-rose-500 to-rose-600 text-white hover:from-rose-400 hover:to-rose-500",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------- Inputs */

const fieldClass =
  "w-full rounded-lg border border-white/10 bg-inset/70 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/25";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${fieldClass} ${props.className ?? ""}`} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${fieldClass} ${props.className ?? ""}`} />;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-slate-400">{label}</span>
      {children}
    </label>
  );
}

export function Select({
  value,
  onChange,
  options,
  className = "",
  disabled = false,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  className?: string;
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className={`${fieldClass} ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"} ${className}`}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} className="bg-panel text-slate-100">
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}) {
  return (
    <button type="button" onClick={() => onChange(!checked)} className="flex items-center gap-2">
      <span
        className={`relative inline-flex h-5 w-9 items-center rounded-full transition ${
          checked ? "bg-brand-600 shadow-[0_0_12px_-2px_rgba(37,99,235,0.8)]" : "bg-slate-700"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${
            checked ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </span>
      {label && <span className="text-sm text-slate-300">{label}</span>}
    </button>
  );
}

export function Slider({
  value,
  onChange,
  min,
  max,
  step = 1,
  suffix = "",
}: {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  suffix?: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-slate-700 accent-brand-500"
      />
      <span className="w-14 shrink-0 text-right text-sm font-semibold text-slate-200">
        {value}
        {suffix}
      </span>
    </div>
  );
}

/* --------------------------------------------------------------- Page parts */

export function PageHeader({
  title,
  subtitle,
  action,
  eyebrow,
}: {
  title: ReactNode;
  subtitle?: string;
  action?: ReactNode;
  eyebrow?: string;
}) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && (
          <div className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-medium text-slate-400">
            <span className="h-1.5 w-1.5 rounded-full bg-brand-400" />
            {eyebrow}
          </div>
        )}
        <h1 className="text-[1.7rem] font-bold leading-tight tracking-tight text-slate-50">{title}</h1>
        {subtitle && <p className="mt-1.5 text-sm text-slate-400">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function Section({
  title,
  description,
  children,
  icon,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="card-surface overflow-hidden">
      <div className="flex items-center gap-3 border-b border-white/10 px-5 py-3.5">
        {icon && (
          <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-brand-500/30 bg-brand-500/10 text-brand-300">
            {icon}
          </span>
        )}
        <div>
          <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
          {description && <p className="text-xs text-slate-500">{description}</p>}
        </div>
      </div>
      <div className="space-y-4 p-5">{children}</div>
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.02] p-12 text-center">
      <p className="text-sm font-semibold text-slate-200">{title}</p>
      {hint && <p className="mx-auto mt-1.5 max-w-md text-xs text-slate-500">{hint}</p>}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}
