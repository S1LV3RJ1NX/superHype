import {
  LayoutDashboard,
  Link2,
  PenLine,
  Settings,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";

import { Wordmark } from "@/components/Wordmark";
import { cn } from "@/lib/utils";

const NAV = [
  { label: "Dashboard", icon: LayoutDashboard, active: true },
  { label: "Compose", icon: PenLine, active: false },
  { label: "Skills", icon: Settings, active: false },
  { label: "Connections", icon: Link2, active: false },
  { label: "Users", icon: Users, active: false },
];

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen bg-paper text-ink">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-sand md:flex">
        <div className="flex h-16 items-center px-5">
          <Wordmark className="text-xl" />
        </div>
        <nav className="flex flex-col gap-1 px-3 py-2">
          {NAV.map(({ label, icon: Icon, active }) => (
            <button
              key={label}
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
            </button>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 items-center justify-between border-b border-border bg-paper px-6">
          <Wordmark className="text-lg md:hidden" />
          <div className="ml-auto flex items-center gap-3">
            <span className="text-sm text-muted-ink">Placeholder admin</span>
            <div className="h-8 w-8 rounded-full bg-clay/15 ring-1 ring-border" />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
