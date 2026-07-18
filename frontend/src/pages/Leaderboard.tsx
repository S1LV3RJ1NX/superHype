import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Trophy } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

interface LeaderboardEntry {
  rank: number;
  user_id: string;
  name: string | null;
  avatar_url: string | null;
  team_name: string | null;
  likes: number;
  bookmarks: number;
  comments: number;
  reposts: number;
  direct_posts: number;
  brand_posts: number;
  impressions: number;
  score: number;
}

interface LeaderboardResponse {
  start: string | null;
  end: string | null;
  entries: LeaderboardEntry[];
}

type PresetKey = "all" | "month" | "quarter" | "year";

const PRESETS: { key: PresetKey; label: string }[] = [
  { key: "all", label: "All time" },
  { key: "month", label: "This month" },
  { key: "quarter", label: "This quarter" },
  { key: "year", label: "This year" },
];

// Local YYYY-MM-DD, the value shape the native date input expects.
function toInput(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

const TODAY = toInput(new Date());

// Never let a bound run past today: there is no future data and every search is
// capped at today, in the pickers too.
function clampToday(value: string): string {
  return value && value > TODAY ? TODAY : value;
}

// Each preset resolves to concrete From/To dates so the pickers below always
// show the exact window being queried. From is the first day of the calendar
// month, quarter, or year; To is the calendar period end clamped to today, so a
// window that has not finished yet (this quarter, this year) still stops today.
// "All time" clears both bounds.
function presetRange(key: PresetKey): { from: string; to: string } {
  const now = new Date();
  const y = now.getFullYear();
  if (key === "month") {
    return {
      from: toInput(new Date(y, now.getMonth(), 1)),
      to: clampToday(toInput(new Date(y, now.getMonth() + 1, 0))),
    };
  }
  if (key === "quarter") {
    const q = Math.floor(now.getMonth() / 3) * 3;
    return {
      from: toInput(new Date(y, q, 1)),
      to: clampToday(toInput(new Date(y, q + 3, 0))),
    };
  }
  if (key === "year") {
    return {
      from: toInput(new Date(y, 0, 1)),
      to: clampToday(toInput(new Date(y, 11, 31))),
    };
  }
  return { from: "", to: "" };
}

const MEDAL = ["text-clay", "text-muted-ink", "text-clay/60"];

export function Leaderboard() {
  const [preset, setPreset] = useState<PresetKey | null>("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const selectPreset = (key: PresetKey) => {
    const r = presetRange(key);
    setFrom(r.from);
    setTo(r.to);
    setPreset(key);
  };

  // Turn the picked dates into an inclusive-start, exclusive-end ISO range. An
  // empty bound is left off so the backend treats that side as open.
  const range = useMemo(() => {
    const r: { start?: string; end?: string } = {};
    if (from) r.start = new Date(from).toISOString();
    if (to) {
      const end = new Date(to);
      end.setDate(end.getDate() + 1);
      r.end = end.toISOString();
    }
    return r;
  }, [from, to]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = new URLSearchParams();
      p.set("limit", "100");
      if (range.start) p.set("start", range.start);
      if (range.end) p.set("end", range.end);
      const data = await apiFetch<LeaderboardResponse>(
        `/v1/leaderboard?${p.toString()}`,
      );
      setEntries(data.entries);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load leaderboard");
    } finally {
      setLoading(false);
    }
  }, [range.start, range.end]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-clay/10">
            <Trophy className="h-5 w-5 text-clay" />
          </div>
          <div>
            <h1 className="font-serif text-2xl text-ink">Super hyper leaderboard</h1>
            <p className="text-sm text-muted-ink">
              Ranked by the amplification your crew put in. Likes, comments,
              reshares, and brand posts all count.
            </p>
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-2">
          {PRESETS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => selectPreset(key)}
              className={cn(
                "rounded-full px-3 py-1.5 text-sm transition-colors",
                preset === key
                  ? "bg-clay text-paper"
                  : "border border-border text-muted-ink hover:bg-sand",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {/* The pickers always show the exact window, so a preset is just a
            shortcut you can then fine-tune and verify. */}
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-muted-ink">
            From
            <input
              type="date"
              value={from}
              max={to || TODAY}
              onChange={(e) => {
                setFrom(clampToday(e.target.value));
                setPreset(null);
              }}
              className="rounded-md border border-border bg-surface px-2 py-1 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-ink">
            To
            <input
              type="date"
              value={to}
              min={from || undefined}
              max={TODAY}
              onChange={(e) => {
                setTo(clampToday(e.target.value));
                setPreset(null);
              }}
              className="rounded-md border border-border bg-surface px-2 py-1 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </label>
          {(from || to) && (
            <button
              onClick={() => {
                setFrom("");
                setTo("");
                setPreset("all");
              }}
              className="pb-1.5 text-xs text-muted-ink underline underline-offset-2 hover:text-ink"
            >
              Clear
            </button>
          )}
          <p className="pb-1.5 text-xs text-muted-ink">
            {from || to
              ? `Showing ${from || "the beginning"} to ${to || "today"}`
              : "Showing all time"}
          </p>
        </div>

        {error && (
          <div className="mt-4 rounded-md border border-fail/20 bg-fail/5 px-4 py-2 text-sm text-fail">
            {error}
          </div>
        )}

        {loading ? (
          <div className="mt-4 flex justify-center rounded-lg border border-border py-16">
            <Loader2 className="h-5 w-5 animate-spin text-muted-ink" />
          </div>
        ) : (
          <div className="mt-4 overflow-hidden rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-sand/50 text-left text-xs font-medium uppercase tracking-wider text-muted-ink">
                  <th className="px-4 py-3">#</th>
                  <th className="px-4 py-3">Member</th>
                  <th className="px-4 py-3 text-right">Likes</th>
                  <th className="px-4 py-3 text-right">Bookmarks</th>
                  <th className="px-4 py-3 text-right">Comments</th>
                  <th className="px-4 py-3 text-right">Reposts</th>
                  <th className="px-4 py-3 text-right">Brand posts</th>
                  <th className="px-4 py-3 text-right">Score</th>
                </tr>
              </thead>
              <tbody>
                {entries.length === 0 && (
                  <tr>
                    <td
                      colSpan={8}
                      className="px-4 py-8 text-center text-sm text-muted-ink"
                    >
                      No activity in this window yet.
                    </td>
                  </tr>
                )}
                {entries.map((e) => (
                  <tr
                    key={e.user_id}
                    className="border-b border-border last:border-b-0"
                  >
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "font-serif text-base font-semibold",
                          e.rank <= 3 ? MEDAL[e.rank - 1] : "text-muted-ink",
                        )}
                      >
                        {e.rank}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        {e.avatar_url ? (
                          <img
                            src={e.avatar_url}
                            alt=""
                            className="h-8 w-8 rounded-full ring-1 ring-border"
                            referrerPolicy="no-referrer"
                          />
                        ) : (
                          <div className="h-8 w-8 rounded-full bg-clay/15 ring-1 ring-border" />
                        )}
                        <div>
                          <p className="font-medium text-ink">
                            {e.name ?? "Unknown"}
                          </p>
                          {e.team_name && (
                            <p className="text-xs text-muted-ink">
                              {e.team_name}
                            </p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-muted-ink">
                      {e.likes}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-muted-ink">
                      {e.bookmarks}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-muted-ink">
                      {e.comments}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-muted-ink">
                      {e.reposts}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-muted-ink">
                      {e.brand_posts}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold tabular-nums text-ink">
                      {e.score}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppShell>
  );
}
