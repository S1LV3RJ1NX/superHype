import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { Link } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ScheduleEntry {
  id: string;
  title: string;
  type: string;
  status: string;
  scheduled_at: string | null;
  launched_at: string | null;
  creator_name: string | null;
  // False when the campaign is redacted for this user (not theirs, not a
  // participant): the API returns a generic title and the chip must not link.
  can_view: boolean;
}

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-sand text-muted-ink",
  generating: "bg-pending/15 text-pending",
  review: "bg-clay/15 text-clay",
  publishing: "bg-ok/15 text-ok",
  paused: "bg-pending/15 text-pending",
  completed: "bg-ok text-paper",
  failed: "bg-fail/10 text-fail",
};

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function ymd(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// The 42-cell (6 week) grid starting on the Monday on or before the 1st, so the
// month always lays out cleanly and adjacent-month days are visible but muted.
function monthGrid(anchor: Date): Date[] {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  // getDay(): 0=Sun..6=Sat; shift so Monday is the first column.
  const lead = (first.getDay() + 6) % 7;
  const start = new Date(first);
  start.setDate(first.getDate() - lead);
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  });
}

export function Events() {
  const [anchor, setAnchor] = useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  const [entries, setEntries] = useState<ScheduleEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const cells = useMemo(() => monthGrid(anchor), [anchor]);
  const todayKey = ymd(new Date());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const start = ymd(cells[0]);
      const end = ymd(cells[cells.length - 1]);
      const data = await apiFetch<ScheduleEntry[]>(
        `/v1/campaigns/schedule?start=${start}&end=${end}`,
      );
      setEntries(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load events");
    } finally {
      setLoading(false);
    }
  }, [cells]);

  useEffect(() => {
    load();
  }, [load]);

  // Group entries by their local calendar day so each cell reads its own list.
  const byDay = useMemo(() => {
    const map: Record<string, ScheduleEntry[]> = {};
    for (const e of entries) {
      if (!e.scheduled_at) continue;
      const key = ymd(new Date(e.scheduled_at));
      (map[key] ??= []).push(e);
    }
    return map;
  }, [entries]);

  const monthLabel = anchor.toLocaleString(undefined, {
    month: "long",
    year: "numeric",
  });

  const step = (delta: number) =>
    setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + delta, 1));

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2 font-serif text-2xl text-ink">
              <CalendarDays className="h-6 w-6 text-clay" />
              Events
            </h1>
            <p className="mt-1 text-sm text-muted-ink">
              Scheduled campaign launches. Only one campaign can be scheduled per
              day, so a taken day is reserved for everyone.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => step(-1)}
              aria-label="Previous month"
              className="rounded-md border border-border p-2 text-muted-ink hover:bg-sand"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-40 text-center text-sm font-medium text-ink">
              {monthLabel}
            </span>
            <button
              onClick={() => step(1)}
              aria-label="Next month"
              className="rounded-md border border-border p-2 text-muted-ink hover:bg-sand"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-4 rounded-md border border-fail/20 bg-fail/5 px-4 py-2 text-sm text-fail">
            {error}
          </div>
        )}

        <div className="relative mt-6 overflow-hidden rounded-lg border border-border bg-surface">
          {loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-paper/60">
              <Loader2 className="h-6 w-6 animate-spin text-muted-ink" />
            </div>
          )}
          <div className="grid grid-cols-7 border-b border-border bg-sand/40">
            {WEEKDAYS.map((d) => (
              <div
                key={d}
                className="px-2 py-2 text-center text-xs font-medium text-muted-ink"
              >
                {d}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7">
            {cells.map((day) => {
              const key = ymd(day);
              const inMonth = day.getMonth() === anchor.getMonth();
              const dayEntries = byDay[key] ?? [];
              const taken = dayEntries.length > 0;
              return (
                <div
                  key={key}
                  className={cn(
                    "min-h-24 border-b border-r border-border p-1.5",
                    !inMonth && "bg-sand/20",
                    taken && "bg-clay/5",
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span
                      className={cn(
                        "inline-flex h-6 w-6 items-center justify-center rounded-full text-xs",
                        key === todayKey
                          ? "bg-ink font-medium text-paper"
                          : inMonth
                            ? "text-ink"
                            : "text-muted-ink/60",
                      )}
                    >
                      {day.getDate()}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-col gap-1">
                    {dayEntries.map((e) => {
                      const tooltip = `${e.title}${e.creator_name ? ` · ${e.creator_name}` : ""}`;
                      const chipClass = cn(
                        "block truncate rounded px-1.5 py-1 text-xs font-medium",
                        STATUS_STYLES[e.status] ?? "bg-sand text-muted-ink",
                      );
                      const label = (
                        <>
                          {new Date(e.scheduled_at!).toLocaleTimeString(
                            undefined,
                            { hour: "2-digit", minute: "2-digit" },
                          )}{" "}
                          {e.title}
                        </>
                      );
                      return e.can_view ? (
                        <Link
                          key={e.id}
                          to={`/app/campaigns/${e.id}`}
                          title={tooltip}
                          className={cn(chipClass, "hover:opacity-80")}
                        >
                          {label}
                        </Link>
                      ) : (
                        <span key={e.id} title={tooltip} className={chipClass}>
                          {label}
                        </span>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
