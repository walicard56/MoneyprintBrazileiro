import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  IconDashboard,
  IconChannel,
  IconVideo,
  IconSparkles,
  IconPlug,
  IconSettings,
} from "./icons";
import { pt } from "@/i18n/ptBR";
import { BackendStatus } from "./BackendStatus";
import type { ComponentType, SVGProps } from "react";

type NavItem = {
  to: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  end?: boolean;
};

const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", end: true, icon: IconDashboard },
  { to: "/canais", label: pt.nav.canais, icon: IconChannel },
  { to: "/videos", label: "Videos", icon: IconVideo },
  { to: "/providers", label: "Providers", icon: IconPlug },
  { to: "/settings", label: "Settings", icon: IconSettings },
];

export default function Layout() {
  const navigate = useNavigate();
  return (
    <div className="flex min-h-screen flex-col">
      <header className="glass sticky top-0 z-30 border-b">
        <div className="mx-auto grid h-16 max-w-7xl grid-cols-[auto_1fr_auto] items-center gap-4 px-4 md:px-8">
          {/* Brand lockup */}
          <button
            onClick={() => navigate("/")}
            className="flex shrink-0 items-center gap-2.5"
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-violet-600 text-base font-black text-white shadow-[0_8px_24px_-8px_rgba(37,99,235,0.9)]">
              M
            </div>
            <div className="hidden leading-tight sm:block">
              <div className="text-[14px] font-extrabold tracking-tight text-slate-50">
                Money<span className="gradient-text">Print</span>
              </div>
              <div className="text-[9px] font-medium uppercase tracking-[0.14em] text-slate-500">
                short-video studio
              </div>
            </div>
          </button>

          {/* Centered nav */}
          <nav className="flex min-w-0 items-center justify-center gap-1 overflow-x-auto">
            {NAV.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `group relative flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition ${
                      isActive
                        ? "bg-brand-500/10 text-brand-300"
                        : "text-slate-400 hover:bg-white/5 hover:text-slate-100"
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon width={16} height={16} />
                      <span className="hidden md:inline">{item.label}</span>
                      {isActive && (
                        <span className="absolute inset-x-2.5 -bottom-[1px] h-0.5 rounded-full bg-gradient-to-r from-brand-400 to-violet-500" />
                      )}
                    </>
                  )}
                </NavLink>
              );
            })}
          </nav>

          {/* Status + primary action */}
          <div className="flex shrink-0 items-center gap-3">
            <BackendStatus compact />
            <button
              onClick={() => navigate("/create")}
              className="group inline-flex items-center gap-2 rounded-lg bg-gradient-to-b from-brand-500 to-brand-600 px-3.5 py-2 text-sm font-semibold text-white shadow-[0_10px_28px_-10px_rgba(37,99,235,0.95)] transition hover:from-brand-400 hover:to-brand-500"
            >
              <IconSparkles width={15} height={15} className="transition group-hover:rotate-12" />
              <span className="hidden sm:inline">New video</span>
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1">
        <div className="mx-auto max-w-7xl animate-fadein p-6 md:p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
