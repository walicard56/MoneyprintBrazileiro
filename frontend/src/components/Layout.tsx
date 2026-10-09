import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  IconDashboard,
  IconProjects,
  IconVideo,
  IconSparkles,
  IconPlug,
  IconBot,
  IconText,
  IconUsers,
  IconSettings,
  IconChannel,
} from "./icons";
import { pt } from "@/i18n/ptBR";
import { BackendStatus } from "./BackendStatus";
import type { ComponentType, SVGProps } from "react";

type NavItem = {
  to: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  end?: boolean;
  accent?: boolean;
};

const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", end: true, icon: IconDashboard },
  { to: "/create", label: "Create video", icon: IconSparkles, accent: true },
  { to: "/canais", label: pt.nav.canais, icon: IconChannel },
  { to: "/projects", label: "Projects", icon: IconProjects },
  { to: "/videos", label: "Videos", icon: IconVideo },
  { to: "/providers", label: "Providers / APIs", icon: IconPlug },
  { to: "/agents", label: "Agents", icon: IconBot },
  { to: "/prompts", label: "Prompts", icon: IconText },
  { to: "/accounts", label: "Accounts", icon: IconUsers },
  { to: "/settings", label: "Settings", icon: IconSettings },
];

export default function Layout() {
  const navigate = useNavigate();
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col border-r border-white/10 bg-night/60 p-4 backdrop-blur-xl">
        {/* Brand lockup */}
        <div className="mb-7 flex items-center gap-3 px-1 pt-1">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-violet-600 text-lg font-black text-white shadow-[0_8px_24px_-8px_rgba(37,99,235,0.9)]">
            M
          </div>
          <div className="leading-tight">
            <div className="text-[15px] font-extrabold tracking-tight text-slate-50">
              Money<span className="gradient-text">Print</span>
            </div>
            <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">
              short-video studio
            </div>
          </div>
        </div>

        <button
          onClick={() => navigate("/create")}
          className="group mb-6 flex items-center justify-center gap-2 rounded-xl bg-gradient-to-b from-brand-500 to-brand-600 px-3 py-2.5 text-sm font-semibold text-white shadow-[0_10px_28px_-10px_rgba(37,99,235,0.95)] transition hover:from-brand-400 hover:to-brand-500"
        >
          <IconSparkles width={16} height={16} className="transition group-hover:rotate-12" />
          New video
        </button>

        <nav className="flex-1 space-y-1">
          {NAV.filter((n) => !n.accent).map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                    isActive
                      ? "bg-brand-500/10 text-brand-300"
                      : "text-slate-400 hover:bg-white/5 hover:text-slate-100"
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-gradient-to-b from-brand-400 to-violet-500" />
                    )}
                    <Icon width={17} height={17} />
                    {item.label}
                  </>
                )}
              </NavLink>
            );
          })}
        </nav>

        <BackendStatus />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top glass bar */}
        <header className="glass sticky top-0 z-20 flex h-14 items-center justify-between border-b px-6">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulseglow" />
            <span className="font-mono">All systems operational</span>
          </div>
          <button
            onClick={() => navigate("/create")}
            className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-slate-100 transition hover:border-brand-500/50 hover:bg-brand-500/10"
          >
            <IconSparkles width={14} height={14} /> New video
          </button>
        </header>

        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-6xl animate-fadein p-6 md:p-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
