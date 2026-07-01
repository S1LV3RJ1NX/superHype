import {
  LayoutDashboard,
  Link2,
  LogOut,
  Megaphone,
  Trophy,
  UsersRound,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Wordmark } from "@/components/Wordmark";
import { cn } from "@/lib/utils";

const NAV = [
  { label: "Dashboard", icon: LayoutDashboard, href: "/app" },
  { label: "Campaigns", icon: Megaphone, href: "/app/campaigns" },
  { label: "Connectors", icon: Link2, href: "/app/connections" },
  { label: "Leaderboard", icon: Trophy, href: "/app/leaderboard" },
  { label: "Teams", icon: UsersRound, href: "/app/teams", adminOnly: true },
  { label: "Users", icon: Users, href: "/app/users", adminOnly: true },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const location = useLocation();

  return (
    <div className="flex min-h-screen bg-paper text-ink">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-sand md:flex">
        <div className="flex h-16 items-center px-5">
          <Wordmark className="text-xl" />
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-3 py-2">
          {NAV.map(({ label, icon: Icon, href, adminOnly }) => {
            if (adminOnly && user?.role !== "admin") return null;
            const active = location.pathname === href;
            return (
              <Link
                key={label}
                to={href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active
                    ? "bg-surface font-medium text-ink shadow-sm"
                    : "text-muted-ink hover:bg-surface/60",
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-border px-3 py-3">
          <button
            onClick={logout}
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-ink transition-colors hover:bg-surface/60"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 items-center justify-between border-b border-border bg-paper px-6">
          <Wordmark className="text-lg md:hidden" />
          <Link
            to="/app/profile"
            className="ml-auto flex items-center gap-3 rounded-full py-1 pl-3 pr-1 transition-colors hover:bg-sand"
            title="Your profile"
          >
            <span className="flex flex-col items-end leading-tight">
              <span className="text-sm text-ink">
                {user?.name ?? user?.email ?? ""}
              </span>
              {user?.team_name && (
                <span className="text-xs text-muted-ink">{user.team_name}</span>
              )}
            </span>
            {user?.avatar_url ? (
              <img
                src={user.avatar_url}
                alt=""
                className="h-8 w-8 rounded-full ring-1 ring-border"
                referrerPolicy="no-referrer"
              />
            ) : (
              <div className="h-8 w-8 rounded-full bg-clay/15 ring-1 ring-border" />
            )}
          </Link>
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
