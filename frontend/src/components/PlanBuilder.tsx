import { useEffect, useState } from "react";
import { Loader2, Search, Sparkles } from "lucide-react";

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

export interface LockedPost {
  id: string;
  user_id: string;
  action: string;
  status: string;
}

// Amplify actions in canonical order; the key matches the backend action name.
const AMPLIFY_ACTIONS = [
  { key: "like", label: "Like" },
  { key: "comment", label: "Comment" },
  { key: "repost_comment", label: "Repost" },
] as const;

const ALL_AMPLIFY_KEYS = AMPLIFY_ACTIONS.map((a) => a.key);

export function PlanBuilder({
  campaignType,
  roster,
  isEditor,
  busy,
  onPlan,
  initialParticipantIds,
  initialActionsByParticipant,
  lockedPosts,
}: {
  campaignType: string;
  roster: RosterUser[];
  isEditor: boolean;
  busy: boolean;
  onPlan: (
    participantIds: string[],
    generate: boolean,
    actionsByParticipant?: Record<string, string[]>,
  ) => void;
  initialParticipantIds?: string[];
  initialActionsByParticipant?: Record<string, string[]>;
  lockedPosts?: LockedPost[];
}) {
  const isDistribute = campaignType === "distribute";

  // Distribute tracks membership only (actions are derived from the type).
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(initialParticipantIds ?? []),
  );
  // Amplify tracks each person's chosen actions; membership = a non-empty set.
  const [actions, setActions] = useState<Record<string, Set<string>>>(() => {
    const init: Record<string, Set<string>> = {};
    if (initialActionsByParticipant) {
      for (const [uid, acts] of Object.entries(initialActionsByParticipant)) {
        if (acts.length > 0) init[uid] = new Set(acts);
      }
    } else if (initialParticipantIds) {
      for (const uid of initialParticipantIds) init[uid] = new Set(ALL_AMPLIFY_KEYS);
    }
    return init;
  });

  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "connected" | "unconnected">(
    "all",
  );
  const [teamFilter, setTeamFilter] = useState<string>("all");
  const [teams, setTeams] = useState<TeamOption[]>([]);
  const [teamsLoading, setTeamsLoading] = useState(true);

  useEffect(() => {
    fetchAllTeams()
      .then(setTeams)
      .catch(() => setTeams([]))
      .finally(() => setTeamsLoading(false));
  }, []);

  // Only show team controls for teams that actually have someone in the roster.
  const teamsInRoster = teams.filter((t) =>
    roster.some((u) => u.team_id === t.id),
  );

  const isConnected = (u: RosterUser) => !!u.linkedin_status;

  const teamMembers = (teamId: string) =>
    roster.filter((u) => u.team_id === teamId);

  // --- membership helpers (branch on campaign type) ------------------------

  const isMember = (uid: string) =>
    isDistribute ? selected.has(uid) : (actions[uid]?.size ?? 0) > 0;

  const memberIds = (): string[] =>
    isDistribute
      ? Array.from(selected)
      : Object.keys(actions).filter((uid) => (actions[uid]?.size ?? 0) > 0);

  // Add or remove people wholesale. On amplify, adding a person defaults them to
  // every action; removing clears their set.
  const setMembers = (uids: string[], on: boolean) => {
    if (isDistribute) {
      setSelected((prev) => {
        const next = new Set(prev);
        uids.forEach((u) => (on ? next.add(u) : next.delete(u)));
        return next;
      });
    } else {
      setActions((prev) => {
        const next = { ...prev };
        uids.forEach((u) => {
          if (on) next[u] = new Set(ALL_AMPLIFY_KEYS);
          else delete next[u];
        });
        return next;
      });
    }
  };

  const toggleMember = (uid: string) => setMembers([uid], !isMember(uid));

  // --- amplify per-action helpers ------------------------------------------

  const hasAction = (uid: string, action: string) =>
    actions[uid]?.has(action) ?? false;

  const toggleAction = (uid: string, action: string) =>
    setActions((prev) => {
      const next = { ...prev };
      const set = new Set(next[uid] ?? []);
      if (set.has(action)) set.delete(action);
      else set.add(action);
      if (set.size === 0) delete next[uid];
      else next[uid] = set;
      return next;
    });

  // Column toggle: if every filtered person already has this action, drop it from
  // all of them; otherwise add it to all (which also selects them).
  const toggleActionColumn = (action: string, filteredUsers: RosterUser[]) => {
    const all =
      filteredUsers.length > 0 &&
      filteredUsers.every((u) => hasAction(u.id, action));
    setActions((prev) => {
      const next = { ...prev };
      filteredUsers.forEach((u) => {
        const set = new Set(next[u.id] ?? []);
        if (all) set.delete(action);
        else set.add(action);
        if (set.size === 0) delete next[u.id];
        else next[u.id] = set;
      });
      return next;
    });
  };

  // Clicking a team chip selects all its roster members; clicking again when all
  // are already members deselects them.
  const toggleTeam = (teamId: string) => {
    const members = teamMembers(teamId);
    if (members.length === 0) return;
    const allSelected = members.every((u) => isMember(u.id));
    setMembers(
      members.map((u) => u.id),
      !allSelected,
    );
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
    filtered.length > 0 && filtered.every((u) => isMember(u.id));

  const toggleSelectAll = () =>
    setMembers(
      filtered.map((u) => u.id),
      !allFilteredSelected,
    );

  const participantIds = memberIds();
  const total = participantIds.length;
  const canGenerate = (isDistribute ? isEditor : true) && total > 0;

  const actionsByParticipant = (): Record<string, string[]> => {
    const out: Record<string, string[]> = {};
    for (const uid of Object.keys(actions)) {
      const set = actions[uid];
      if (set && set.size > 0) {
        out[uid] = ALL_AMPLIFY_KEYS.filter((k) => set.has(k));
      }
    }
    return out;
  };

  const handleGenerate = () =>
    onPlan(
      participantIds,
      true,
      isDistribute ? undefined : actionsByParticipant(),
    );

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

      <div className="mb-3 rounded-md border border-clay/30 bg-clay/10 px-3 py-2 text-xs font-medium text-clay">
        {isDistribute
          ? "Everyone you pick posts their own version (from the seed, in their team voice), plus the self comment if set. They also like and comment on each other's posts, founders' posts first."
          : "Pick who takes part and which actions each does. New people default to like, comment, and repost; untick any to drop it for that person."}
      </div>

      {teamsLoading ? (
        <div className="flex items-center justify-center gap-2 rounded-md border border-border bg-sand/30 px-3 py-10 text-xs text-muted-ink">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading teams...
        </div>
      ) : (
        <>
          {teamsInRoster.length > 0 && (
            <div className="mb-2">
              <p className="mb-1.5 text-xs text-muted-ink">
                Add a whole team, or pick people below.
              </p>
              <div className="flex flex-wrap gap-1.5">
                {teamsInRoster.map((t) => {
                  const members = teamMembers(t.id);
                  const allSelected =
                    members.length > 0 && members.every((u) => isMember(u.id));
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
            <span className="text-xs text-muted-ink">{total} selected</span>
          </div>

          {/* Amplify: per-action column toggles select/clear that action across
              everyone currently in the filtered list. */}
          {!isDistribute && filtered.length > 0 && (
            <div className="mb-1 flex items-center gap-2 pl-2 pr-10 text-[11px] font-medium uppercase tracking-wide text-muted-ink">
              <span aria-hidden className="w-4 shrink-0" />
              <span className="flex-1">Actions (untick to drop for a person)</span>
              {AMPLIFY_ACTIONS.map((a) => {
                const all = filtered.every((u) => hasAction(u.id, a.key));
                return (
                  <label
                    key={a.key}
                    className="flex w-14 flex-col items-center gap-0.5"
                    title={`Toggle ${a.label} for everyone listed`}
                  >
                    <span>{a.label}</span>
                    <input
                      type="checkbox"
                      checked={all}
                      onChange={() => toggleActionColumn(a.key, filtered)}
                    />
                  </label>
                );
              })}
            </div>
          )}

          <div className="max-h-80 divide-y divide-border overflow-y-auto rounded-md border border-border">
            {filtered.length === 0 && (
              <p className="px-3 py-4 text-xs text-muted-ink">
                No people match your search.
              </p>
            )}
            {filtered.map((u) => {
              const connected = isConnected(u);
              const stale = connected && u.linkedin_status !== "active";
              const info = (
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
              );

              if (isDistribute) {
                return (
                  <label
                    key={u.id}
                    className="flex cursor-pointer items-center gap-2 px-2 py-1.5"
                  >
                    <input
                      type="checkbox"
                      checked={isMember(u.id)}
                      onChange={() => toggleMember(u.id)}
                    />
                    {info}
                  </label>
                );
              }

              // Amplify: a member checkbox plus one checkbox per action. The row
              // is a div (not a label) so ticking an action does not also toggle
              // the member checkbox.
              return (
                <div
                  key={u.id}
                  className="flex items-center gap-2 py-1.5 pl-2 pr-8"
                >
                  <input
                    type="checkbox"
                    className="shrink-0"
                    checked={isMember(u.id)}
                    onChange={() => toggleMember(u.id)}
                    title="Include this person (all actions)"
                  />
                  {info}
                  {AMPLIFY_ACTIONS.map((a) => (
                    <span
                      key={a.key}
                      className="flex w-14 items-center justify-center"
                    >
                      <input
                        type="checkbox"
                        checked={hasAction(u.id, a.key)}
                        onChange={() => toggleAction(u.id, a.key)}
                        aria-label={`${a.label} for ${u.name ?? u.email}`}
                      />
                    </span>
                  ))}
                </div>
              );
            })}
          </div>

          <div className="mt-3 text-xs text-muted-ink">
            {total === 0
              ? "Pick people or a team above to include them."
              : `${total} ${total === 1 ? "person" : "people"} selected.`}
          </div>

          <div className="mt-3 flex gap-2">
            <button
              onClick={handleGenerate}
              disabled={busy || !canGenerate}
              title={
                isDistribute && !isEditor
                  ? "Generation requires the editor role"
                  : undefined
              }
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
        </>
      )}
    </div>
  );
}

function nameFor(roster: RosterUser[], uid: string) {
  const u = roster.find((x) => x.id === uid);
  return u?.name ?? u?.email ?? "Unknown";
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
