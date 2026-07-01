import { useEffect, useState } from "react";
import { Loader2, Pencil, Search, Sparkles, Star } from "lucide-react";

import { fetchAllTeams } from "@/lib/roster";
import { cn } from "@/lib/utils";

export interface RosterUser {
  id: string;
  name: string | null;
  email: string;
  linkedin_status: string | null;
  team_id: string | null;
}

export interface TeamOption {
  id: string;
  name: string;
}

export interface AssignmentDraft {
  user_id: string;
  action: string;
  target_post_index?: number;
  body?: string;
}

export interface LockedPost {
  id: string;
  user_id: string;
  action: string;
  status: string;
}

type ActionKey = "like" | "comment" | "repost_comment";

const ACTION_META: { key: ActionKey; label: string }[] = [
  { key: "like", label: "Like" },
  { key: "comment", label: "Comment" },
  { key: "repost_comment", label: "Repost thought" },
];

export const ACTIONS = ["like", "comment", "repost_comment"] as const;

interface Variation {
  user_id: string;
  body: string;
}

interface UserAssign {
  like: boolean;
  comment: boolean;
  repost_comment: boolean;
  note: string;
  target: number;
}

const blankAssign = (): UserAssign => ({
  like: false,
  comment: false,
  repost_comment: false,
  note: "",
  target: 0,
});

export function PlanBuilder({
  campaignType,
  roster,
  isEditor,
  busy,
  onPlan,
  initialRows,
  lockedPosts,
}: {
  campaignType: string;
  roster: RosterUser[];
  isEditor: boolean;
  busy: boolean;
  onPlan: (assignments: AssignmentDraft[], generate: boolean) => void;
  initialRows?: AssignmentDraft[];
  lockedPosts?: LockedPost[];
}) {
  const isDistribute = campaignType === "distribute";

  const [variations, setVariations] = useState<Variation[]>(() =>
    (initialRows ?? [])
      .filter((r) => r.action === "post")
      .map((r) => ({ user_id: r.user_id, body: r.body ?? "" })),
  );

  // The "hero" post is the one variation everyone rallies around (a founder's
  // announcement, say). Marking it lets us one-click point commenters at it.
  const [heroIndex, setHeroIndex] = useState<number | null>(null);

  const [assigns, setAssigns] = useState<Record<string, UserAssign>>(() => {
    const a: Record<string, UserAssign> = {};
    for (const u of roster) a[u.id] = blankAssign();
    for (const r of initialRows ?? []) {
      if (r.action === "post") continue;
      const cur = a[r.user_id] ?? blankAssign();
      if (r.action === "like") cur.like = true;
      if (r.action === "comment") cur.comment = true;
      if (r.action === "repost_comment") cur.repost_comment = true;
      if (r.body) cur.note = r.body;
      if (r.target_post_index != null) cur.target = r.target_post_index;
      a[r.user_id] = cur;
    }
    return a;
  });

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "connected" | "unconnected">(
    "all",
  );
  const [teamFilter, setTeamFilter] = useState<string>("all");
  const [teams, setTeams] = useState<TeamOption[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchAllTeams()
      .then(setTeams)
      .catch(() => setTeams([]));
  }, []);

  // Only show team controls for teams that actually have someone in the roster.
  const teamsInRoster = teams.filter((t) =>
    roster.some((u) => u.team_id === t.id),
  );

  const getA = (uid: string) => assigns[uid] ?? blankAssign();

  const toggleAction = (uid: string, key: ActionKey) => {
    const turningOn = !getA(uid)[key];
    setAssigns((prev) => {
      const cur = prev[uid] ?? blankAssign();
      return { ...prev, [uid]: { ...cur, [key]: !cur[key] } };
    });
    // Keep the checkbox in sync: anyone with an action is part of the plan.
    if (turningOn) {
      setSelected((prev) => {
        if (prev.has(uid)) return prev;
        const next = new Set(prev);
        next.add(uid);
        return next;
      });
    }
  };

  const clearActions = (uid: string) =>
    setAssigns((prev) => {
      const cur = prev[uid] ?? blankAssign();
      return {
        ...prev,
        [uid]: { ...cur, like: false, comment: false, repost_comment: false },
      };
    });

  const setNote = (uid: string, note: string) =>
    setAssigns((prev) => {
      const cur = prev[uid] ?? blankAssign();
      return { ...prev, [uid]: { ...cur, note } };
    });

  const setTarget = (uid: string, target: number) =>
    setAssigns((prev) => {
      const cur = prev[uid] ?? blankAssign();
      return { ...prev, [uid]: { ...cur, target } };
    });

  const bulkApply = (key: ActionKey) =>
    setAssigns((prev) => {
      const next = { ...prev };
      selected.forEach((id) => {
        const cur = next[id] ?? blankAssign();
        next[id] = { ...cur, [key]: true };
      });
      return next;
    });

  // With a single variation it is implicitly the hero; otherwise use the
  // explicitly marked one.
  const effectiveHero =
    heroIndex != null && heroIndex < variations.length
      ? heroIndex
      : variations.length === 1
        ? 0
        : null;

  const bulkCommentOnHero = () => {
    if (effectiveHero == null) return;
    setAssigns((prev) => {
      const next = { ...prev };
      selected.forEach((id) => {
        const cur = next[id] ?? blankAssign();
        next[id] = { ...cur, comment: true, target: effectiveHero };
      });
      return next;
    });
  };

  const bulkClear = () =>
    setAssigns((prev) => {
      const next = { ...prev };
      selected.forEach((id) => {
        const cur = next[id] ?? blankAssign();
        next[id] = {
          ...cur,
          like: false,
          comment: false,
          repost_comment: false,
        };
      });
      return next;
    });

  const toggleSelect = (uid: string) => {
    const wasSelected = selected.has(uid);
    setSelected((prev) => {
      const next = new Set(prev);
      if (wasSelected) next.delete(uid);
      else next.add(uid);
      return next;
    });
    // Deselecting a person drops their queued actions too.
    if (wasSelected) clearActions(uid);
  };

  const toggleExpand = (uid: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });

  const isConnected = (u: RosterUser) => !!u.linkedin_status;

  // Clicking a team chip selects every roster member on that team into the
  // per-person picker (the bulk action buttons then apply as usual). Clicking it
  // again when all are already selected deselects them and clears their actions.
  const teamMembers = (teamId: string) =>
    roster.filter((u) => u.team_id === teamId);

  const toggleTeam = (teamId: string) => {
    const members = teamMembers(teamId);
    if (members.length === 0) return;
    const allSelected = members.every((u) => selected.has(u.id));
    if (allSelected) {
      setSelected((prev) => {
        const next = new Set(prev);
        members.forEach((u) => next.delete(u.id));
        return next;
      });
      setAssigns((prev) => {
        const next = { ...prev };
        members.forEach((u) => {
          const cur = next[u.id] ?? blankAssign();
          next[u.id] = {
            ...cur,
            like: false,
            comment: false,
            repost_comment: false,
          };
        });
        return next;
      });
    } else {
      setSelected((prev) => {
        const next = new Set(prev);
        members.forEach((u) => next.add(u.id));
        return next;
      });
    }
  };

  const filtered = roster.filter((u) => {
    const q = search.trim().toLowerCase();
    const matchesQuery =
      !q ||
      (u.name ?? "").toLowerCase().includes(q) ||
      u.email.toLowerCase().includes(q);
    const connected = isConnected(u);
    const matchesFilter =
      filter === "all" ||
      (filter === "connected" && connected) ||
      (filter === "unconnected" && !connected);
    const matchesTeam = teamFilter === "all" || u.team_id === teamFilter;
    return matchesQuery && matchesFilter && matchesTeam;
  });

  const allFilteredSelected =
    filtered.length > 0 && filtered.every((u) => selected.has(u.id));

  const toggleSelectAll = () => {
    if (allFilteredSelected) {
      setSelected((prev) => {
        const next = new Set(prev);
        filtered.forEach((u) => next.delete(u.id));
        return next;
      });
      setAssigns((prev) => {
        const next = { ...prev };
        filtered.forEach((u) => {
          const cur = next[u.id] ?? blankAssign();
          next[u.id] = {
            ...cur,
            like: false,
            comment: false,
            repost_comment: false,
          };
        });
        return next;
      });
    } else {
      setSelected((prev) => {
        const next = new Set(prev);
        filtered.forEach((u) => next.add(u.id));
        return next;
      });
    }
  };

  const addVariation = () =>
    setVariations((v) => [...v, { user_id: roster[0]?.id ?? "", body: "" }]);

  const updateVariation = (i: number, patch: Partial<Variation>) =>
    setVariations((v) =>
      v.map((row, idx) => (idx === i ? { ...row, ...patch } : row)),
    );

  const removeVariation = (i: number) =>
    setVariations((v) => v.filter((_, idx) => idx !== i));

  const buildAssignments = (): AssignmentDraft[] => {
    const out: AssignmentDraft[] = [];
    variations.forEach((v) => {
      if (v.user_id)
        out.push({
          user_id: v.user_id,
          action: "post",
          body: v.body || undefined,
        });
    });
    const hasVariations = isDistribute && variations.length > 0;
    for (const u of roster) {
      const ua = assigns[u.id];
      if (!ua) continue;
      const target = hasVariations
        ? Math.min(ua.target, variations.length - 1)
        : undefined;
      if (ua.like)
        out.push({ user_id: u.id, action: "like", target_post_index: target });
      if (ua.comment)
        out.push({
          user_id: u.id,
          action: "comment",
          body: ua.note || undefined,
          target_post_index: target,
        });
      if (ua.repost_comment)
        out.push({
          user_id: u.id,
          action: "repost_comment",
          body: ua.note || undefined,
          target_post_index: target,
        });
    }
    return out;
  };

  const assignments = buildAssignments();
  const total = assignments.length;
  const peopleCount = new Set(
    assignments.filter((a) => a.action !== "post").map((a) => a.user_id),
  ).size;
  const canGenerate = isDistribute ? isEditor : true;

  return (
    <div>
      {lockedPosts && lockedPosts.length > 0 && (
        <div className="mb-4 space-y-1.5">
          <p className="text-xs font-medium text-muted-ink">
            Already in progress (locked)
          </p>
          {lockedPosts.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between rounded-md border border-border bg-sand/30 px-2.5 py-1.5 text-xs text-muted-ink"
            >
              <span>
                <span className="capitalize">{p.action.replace("_", " ")}</span>{" "}
                &middot; {nameFor(roster, p.user_id)}
              </span>
              <span className="capitalize">{p.status}</span>
            </div>
          ))}
        </div>
      )}

      {isDistribute && isEditor && (
        <div className="mb-4">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-muted-ink">
              Post variations
            </p>
            <SmallButton label="+ Add variation" onClick={addVariation} />
          </div>
          <div className="mt-2 space-y-2">
            {variations.length === 0 && (
              <p className="text-xs text-muted-ink">
                No variations yet. Add at least one post to publish, then assign
                people to amplify it.
              </p>
            )}
            {variations.map((v, i) => (
              <div
                key={i}
                className="rounded-md border border-border bg-paper p-2"
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-ink">#{i + 1}</span>
                  <select
                    value={v.user_id}
                    onChange={(e) =>
                      updateVariation(i, { user_id: e.target.value })
                    }
                    className="input flex-1"
                  >
                    {roster.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name ?? u.email}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() =>
                      setHeroIndex((cur) => (cur === i ? null : i))
                    }
                    aria-pressed={effectiveHero === i}
                    title="Mark this as the hero post everyone comments on"
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors",
                      effectiveHero === i
                        ? "border-clay bg-clay text-paper"
                        : "border-border bg-sand/40 text-muted-ink hover:bg-sand",
                    )}
                  >
                    <Star
                      className={cn(
                        "h-3.5 w-3.5",
                        effectiveHero === i && "fill-current",
                      )}
                    />
                    {effectiveHero === i ? "Hero" : "Set hero"}
                  </button>
                  <button
                    onClick={() => removeVariation(i)}
                    className="text-xs text-fail hover:underline"
                  >
                    Remove
                  </button>
                </div>
                <textarea
                  value={v.body}
                  onChange={(e) => updateVariation(i, { body: e.target.value })}
                  rows={2}
                  placeholder="Optional post text (or leave blank and Generate)."
                  className="input mt-2"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="mb-2 text-xs font-medium text-muted-ink">Engagement</p>

      {teamsInRoster.length > 0 && (
        <div className="mb-2">
          <p className="mb-1.5 text-xs text-muted-ink">
            Add a whole team, then pick actions below.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {teamsInRoster.map((t) => {
              const members = teamMembers(t.id);
              const allSelected =
                members.length > 0 && members.every((u) => selected.has(u.id));
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => toggleTeam(t.id)}
                  aria-pressed={allSelected}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs transition-colors",
                    allSelected
                      ? "border-clay bg-clay text-paper"
                      : "border-border bg-sand/40 text-muted-ink hover:bg-sand",
                  )}
                >
                  {t.name} ({members.length})
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="relative mb-2">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-ink" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name or email"
          className="input pl-8"
        />
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <FilterChip
          label="All"
          active={filter === "all"}
          onClick={() => setFilter("all")}
        />
        <FilterChip
          label="Connected"
          active={filter === "connected"}
          onClick={() => setFilter("connected")}
        />
        <FilterChip
          label="Not connected"
          active={filter === "unconnected"}
          onClick={() => setFilter("unconnected")}
        />
        {teamsInRoster.length > 0 && (
          <select
            value={teamFilter}
            onChange={(e) => setTeamFilter(e.target.value)}
            className="ml-auto rounded-full border border-border bg-sand/40 px-3 py-1 text-xs text-muted-ink focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="all">All teams</option>
            {teamsInRoster.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        )}
      </div>

      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-sand/30 px-2 py-1.5">
        <label className="flex items-center gap-2 text-xs text-ink">
          <input
            type="checkbox"
            checked={allFilteredSelected}
            onChange={toggleSelectAll}
          />
          Select all ({filtered.length})
        </label>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-ink">
            {selected.size} selected
          </span>
          {ACTION_META.map((a) => (
            <SmallButton
              key={a.key}
              label={`+ ${a.label}`}
              onClick={() => bulkApply(a.key)}
              disabled={selected.size === 0}
            />
          ))}
          {isDistribute && effectiveHero != null && (
            <SmallButton
              label="+ Comment on hero"
              onClick={bulkCommentOnHero}
              disabled={selected.size === 0}
            />
          )}
          <SmallButton
            label="Clear"
            onClick={bulkClear}
            disabled={selected.size === 0}
          />
        </div>
      </div>

      <div className="max-h-80 divide-y divide-border overflow-y-auto rounded-md border border-border">
        {filtered.length === 0 && (
          <p className="px-3 py-4 text-xs text-muted-ink">
            No people match your search.
          </p>
        )}
        {filtered.map((u) => {
          const ua = getA(u.id);
          const open = expanded.has(u.id);
          const connected = isConnected(u);
          const stale = connected && u.linkedin_status !== "active";
          const canExpand =
            ua.comment ||
            ua.repost_comment ||
            (isDistribute && variations.length > 1);
          return (
            <div key={u.id} className="px-2 py-1.5">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={selected.has(u.id)}
                  onChange={() => toggleSelect(u.id)}
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-ink">
                    {u.name ?? u.email}
                  </p>
                  <p
                    className={cn(
                      "truncate text-xs",
                      stale ? "text-clay" : "text-muted-ink",
                    )}
                  >
                    {connected
                      ? stale
                        ? "Needs reconnect"
                        : "Connected"
                      : "Not connected"}
                  </p>
                </div>
                {ACTION_META.map((a) => (
                  <TogglePill
                    key={a.key}
                    active={ua[a.key]}
                    label={a.label}
                    onClick={() => toggleAction(u.id, a.key)}
                  />
                ))}
                {canExpand ? (
                  <button
                    onClick={() => toggleExpand(u.id)}
                    className={cn(
                      "hover:text-ink",
                      open ? "text-ink" : "text-muted-ink",
                    )}
                    title="Edit note or target"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                ) : (
                  <span className="w-4" />
                )}
              </div>
              {open && canExpand && (
                <div className="mt-2 space-y-2 pl-6">
                  {isDistribute &&
                    variations.length > 1 &&
                    (ua.like || ua.comment || ua.repost_comment) && (
                      <select
                        value={Math.min(ua.target, variations.length - 1)}
                        onChange={(e) =>
                          setTarget(u.id, Number(e.target.value))
                        }
                        className="input"
                      >
                        {variations.map((_, idx) => (
                          <option key={idx} value={idx}>
                            Target variation #{idx + 1}
                          </option>
                        ))}
                      </select>
                    )}
                  {(ua.comment || ua.repost_comment) && (
                    <textarea
                      value={ua.note}
                      onChange={(e) => setNote(u.id, e.target.value)}
                      rows={2}
                      placeholder="Add micro instruction for this person to nudge the text generation. for this person (or leave blank and Generate)."
                      className="input"
                    />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-3 text-xs text-muted-ink">
        {total === 0
          ? "No actions yet. Toggle Like, Comment, or Repost thought for people above."
          : `${total} action${total === 1 ? "" : "s"} across ${peopleCount} ${
              peopleCount === 1 ? "person" : "people"
            }${
              isDistribute && variations.length
                ? ` and ${variations.length} variation${
                    variations.length === 1 ? "" : "s"
                  }`
                : ""
            }.`}
      </div>

      <div className="mt-3 flex gap-2">
        <button
          onClick={() => onPlan(assignments, true)}
          disabled={busy || total === 0 || !canGenerate}
          title={!canGenerate ? "Generation requires the editor role" : undefined}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-ink px-3 py-2 text-sm font-medium text-paper hover:opacity-90 disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {busy ? "Generating..." : "Generate"}
        </button>
      </div>
    </div>
  );
}

function nameFor(roster: RosterUser[], uid: string) {
  const u = roster.find((x) => x.id === uid);
  return u?.name ?? u?.email ?? "Unknown";
}

function TogglePill({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-full border px-2.5 py-1 text-xs transition-colors",
        active
          ? "border-ink bg-ink text-paper"
          : "border-border bg-sand/40 text-muted-ink hover:bg-sand",
      )}
    >
      {label}
    </button>
  );
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1 text-xs transition-colors",
        active
          ? "border-ink bg-paper text-ink"
          : "border-border bg-sand/40 text-muted-ink hover:bg-sand",
      )}
    >
      {label}
    </button>
  );
}

export function SmallButton({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-md border border-border px-2.5 py-1 text-xs text-muted-ink hover:bg-sand",
        "capitalize disabled:opacity-50",
      )}
    >
      {label}
    </button>
  );
}
