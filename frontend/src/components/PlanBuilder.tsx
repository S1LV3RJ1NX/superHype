import { useEffect, useRef, useState } from "react";
import { Download, FileSpreadsheet, Loader2, Search, Sparkles } from "lucide-react";

import {
  ApiError,
  type DraftImportPreview,
  type ManualDraftPayload,
  downloadDraftsTemplate,
  previewCampaignDrafts,
} from "@/lib/api";
import { fetchAllTeams } from "@/lib/roster";
import { cn } from "@/lib/utils";

export interface RosterUser {
  id: string;
  name: string | null;
  email: string;
  linkedin_status: string | null;
  x_status: string | null;
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
// Labels shift per platform (a comment is a reply on X, a repost is a quote
// post; X likes also get a paired bookmark server-side).
const AMPLIFY_ACTIONS_BY_PLATFORM = {
  linkedin: [
    { key: "like", label: "Like" },
    { key: "comment", label: "Comment" },
    { key: "repost_comment", label: "Repost" },
  ],
  x: [
    { key: "like", label: "Like + bookmark" },
    { key: "comment", label: "Reply" },
    { key: "repost_comment", label: "Quote" },
  ],
} as const;

const ALL_AMPLIFY_KEYS = AMPLIFY_ACTIONS_BY_PLATFORM.linkedin.map((a) => a.key);

export function PlanBuilder({
  campaignType,
  platform = "linkedin",
  campaignId,
  roster,
  isEditor,
  busy,
  onPlan,
  initialParticipantIds,
  initialActionsByParticipant,
  lockedPosts,
}: {
  campaignType: string;
  platform?: string;
  campaignId?: string;
  roster: RosterUser[];
  isEditor: boolean;
  busy: boolean;
  onPlan: (
    participantIds: string[],
    generate: boolean,
    actionsByParticipant?: Record<string, string[]>,
    manualDrafts?: Record<string, ManualDraftPayload>,
  ) => void;
  initialParticipantIds?: string[];
  initialActionsByParticipant?: Record<string, string[]>;
  lockedPosts?: LockedPost[];
}) {
  const isDistribute = campaignType === "distribute";
  const onX = platform === "x";
  const amplifyActions = onX
    ? AMPLIFY_ACTIONS_BY_PLATFORM.x
    : AMPLIFY_ACTIONS_BY_PLATFORM.linkedin;
  // X pairs a bookmark with every like server-side, so its "Like + bookmark"
  // header needs a wider column than the single-word actions to stay on one line.
  const colWidth = (key: string) => (onX && key === "like" ? "w-28" : "w-14");

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

  // Imported spreadsheet drafts (distribute only). The preview drives the
  // matched/unmatched panel; the drafts ride into onPlan for the selected
  // participants so the backend can skip AI generation for them.
  const [importPreview, setImportPreview] = useState<DraftImportPreview | null>(
    null,
  );
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const connectionStatus = (u: RosterUser) =>
    onX ? u.x_status : u.linkedin_status;

  const isConnected = (u: RosterUser) => !!connectionStatus(u);

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

  // --- spreadsheet draft import (distribute only) ---------------------------

  const importedDrafts: Record<string, ManualDraftPayload> = {};
  if (importPreview) {
    for (const m of importPreview.matched) importedDrafts[m.user_id] = m.draft;
  }

  const handleImportFile = async (file: File) => {
    if (!campaignId) return;
    setImportError(null);
    setImportBusy(true);
    try {
      const preview = await previewCampaignDrafts(campaignId, file);
      setImportPreview(preview);
      // Matched people are almost always meant to take part; select them so
      // their drafts are actually used, and let the user untick exceptions.
      setMembers(
        preview.matched.map((m) => m.user_id),
        true,
      );
    } catch (err) {
      setImportError(
        err instanceof ApiError ? err.message : "Failed to read the file",
      );
    } finally {
      setImportBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDownloadTemplate = async () => {
    setImportError(null);
    try {
      await downloadDraftsTemplate();
    } catch (err) {
      setImportError(
        err instanceof ApiError ? err.message : "Failed to download the sample",
      );
    }
  };

  const selectAllMatched = () => {
    if (!importPreview) return;
    setMembers(
      importPreview.matched.map((m) => m.user_id),
      true,
    );
  };

  const draftSummary = (d: ManualDraftPayload): string => {
    const parts: string[] = [];
    if (d.post_body) parts.push("post");
    if (d.self_comment) parts.push("self-comment");
    if (d.comments.length > 0)
      parts.push(`${d.comments.length} comment${d.comments.length > 1 ? "s" : ""}`);
    return parts.join(", ") || "nothing filled in";
  };

  const handleGenerate = () => {
    // Only the selected people's drafts travel; unselected rows are dropped.
    const drafts: Record<string, ManualDraftPayload> = {};
    for (const uid of participantIds) {
      if (importedDrafts[uid]) drafts[uid] = importedDrafts[uid];
    }
    onPlan(
      participantIds,
      true,
      isDistribute ? undefined : actionsByParticipant(),
      isDistribute && Object.keys(drafts).length > 0 ? drafts : undefined,
    );
  };

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
          ? onX
            ? "Everyone you pick posts their own tweet (from the seed, in their team voice), plus the self reply if set. They also like, bookmark, and reply to each other's tweets, founders' tweets first. On X, replies and quotes are done by hand from a ready-to-paste prompt; likes and bookmarks are automatic."
            : "Everyone you pick posts their own version (from the seed, in their team voice), plus the self comment if set. They also like and comment on each other's posts, founders' posts first."
          : onX
            ? "Pick who takes part and which actions each does. New people default to like (with a bookmark), reply, and quote post; untick any to drop it for that person. On X, replies and quotes are done by hand from a ready-to-paste prompt; likes and bookmarks are automatic."
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

          {isDistribute && campaignId && (
            <div className="mb-3 rounded-md border border-clay/30 bg-clay/5 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,.csv"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void handleImportFile(f);
                  }}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={importBusy}
                  className="inline-flex items-center gap-1.5 rounded-md bg-ink px-3 py-1.5 text-xs font-medium text-paper hover:opacity-90 disabled:opacity-50"
                >
                  {importBusy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <FileSpreadsheet className="h-3.5 w-3.5" />
                  )}
                  {importBusy ? "Reading..." : "Import drafts (.xlsx or .csv)"}
                </button>
                <button
                  type="button"
                  onClick={() => void handleDownloadTemplate()}
                  className="inline-flex items-center gap-1.5 rounded-md border border-clay/40 bg-paper px-3 py-1.5 text-xs font-medium text-clay hover:bg-clay/10"
                >
                  <Download className="h-3.5 w-3.5" />
                  Download sample
                </button>
              </div>
              <p className="mt-2 rounded-md border border-clay/30 bg-clay/10 px-2.5 py-1.5 text-xs font-medium text-clay">
                Optional: fill the sample sheet with pre-written posts and
                comments; matched people keep their text and skip AI
                generation. Blank cells are still AI generated.
              </p>

              {importError && (
                <p className="mt-2 text-xs text-fail">{importError}</p>
              )}

              {importPreview && (
                <div className="mt-2 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-medium text-ink">
                      {importPreview.matched.length} matched
                      {importPreview.unmatched.length > 0 &&
                        `, ${importPreview.unmatched.length} not matched`}
                    </p>
                    {importPreview.matched.length > 0 && (
                      <button
                        type="button"
                        onClick={selectAllMatched}
                        className="text-xs text-muted-ink underline-offset-2 hover:text-ink hover:underline"
                      >
                        Select all matched
                      </button>
                    )}
                  </div>
                  {importPreview.matched.map((m) => (
                    <div
                      key={m.user_id}
                      className="rounded-md border border-border bg-paper px-2 py-1 text-[11px] text-muted-ink"
                    >
                      <span className="font-medium text-ink">
                        {m.user_name ?? m.user_email}
                      </span>{" "}
                      (row {m.row}, by {m.matched_by}): {draftSummary(m.draft)}
                      {m.warnings.map((w) => (
                        <span key={w} className="block text-clay">
                          {w}
                        </span>
                      ))}
                    </div>
                  ))}
                  {importPreview.unmatched.map((u) => (
                    <div
                      key={u.row}
                      className="rounded-md border border-clay/30 bg-clay/10 px-2 py-1 text-[11px] text-clay"
                    >
                      Row {u.row} ({u.email ?? u.name ?? "no email or name"}):{" "}
                      {u.reason} It will fall back to AI if the person is
                      selected.
                    </div>
                  ))}
                </div>
              )}
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
              {amplifyActions.map((a) => {
                const all = filtered.every((u) => hasAction(u.id, a.key));
                return (
                  <label
                    key={a.key}
                    className={cn(
                      "flex flex-col items-center gap-0.5",
                      colWidth(a.key),
                    )}
                    title={`Toggle ${a.label} for everyone listed`}
                  >
                    <span className="whitespace-nowrap">{a.label}</span>
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
              const stale = connected && connectionStatus(u) !== "active";
              const info = (
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-1.5 truncate text-sm text-ink">
                    {u.name ?? u.email}
                    {importedDrafts[u.id] && (
                      <span
                        className="shrink-0 rounded-full border border-clay/40 bg-clay/10 px-1.5 py-px text-[10px] font-medium text-clay"
                        title={`Imported: ${draftSummary(importedDrafts[u.id])}`}
                      >
                        Imported draft
                      </span>
                    )}
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
                  {amplifyActions.map((a) => (
                    <span
                      key={a.key}
                      className={cn(
                        "flex items-center justify-center",
                        colWidth(a.key),
                      )}
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
