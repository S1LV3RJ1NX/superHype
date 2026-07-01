import { Fragment, useCallback, useEffect, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  Check,
  Loader2,
  MessageSquareText,
  Pencil,
  Plus,
  UsersRound,
  X,
} from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { apiFetch, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Team {
  id: string;
  name: string;
  is_active: boolean;
  persona: string | null;
  member_count: number;
  created_at: string;
}

export function Teams() {
  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [personaId, setPersonaId] = useState<string | null>(null);
  const [personaText, setPersonaText] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const fetchTeams = useCallback(async () => {
    setLoading(true);
    try {
      const page = await apiFetch<{ items: Team[] }>("/v1/teams/all?limit=100");
      setTeams(page.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load teams");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTeams();
  }, [fetchTeams]);

  const upsert = (team: Team) =>
    setTeams((prev) => {
      const exists = prev.some((t) => t.id === team.id);
      return exists
        ? prev.map((t) => (t.id === team.id ? team : t))
        : [team, ...prev];
    });

  const create = async () => {
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    setError(null);
    try {
      const team = await apiFetch<Team>("/v1/teams", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      upsert(team);
      setNewName("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create team");
    } finally {
      setCreating(false);
    }
  };

  const patch = async (id: string, body: Record<string, unknown>) => {
    setBusyId(id);
    setError(null);
    try {
      const team = await apiFetch<Team>(`/v1/teams/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      upsert(team);
      setEditingId(null);
      setPersonaId(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl">
        <h1 className="font-serif text-2xl text-ink">Teams</h1>
        <p className="mt-1 text-sm text-muted-ink">
          Org groups members pick in onboarding and that campaigns target. Only
          admins can manage them. Archive instead of deleting to keep members
          safe.
        </p>

        {error && (
          <div className="mt-4 rounded-md border border-fail/20 bg-fail/5 px-4 py-2 text-sm text-fail">
            {error}
          </div>
        )}

        <div className="mt-6 flex gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
            placeholder="New team name"
            className="flex-1 rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <button
            onClick={create}
            disabled={creating || !newName.trim()}
            className="inline-flex items-center gap-2 rounded-md bg-clay px-4 py-2 text-sm font-medium text-paper hover:bg-clay-press disabled:opacity-50"
          >
            {creating ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            Add
          </button>
        </div>

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-ink" />
          </div>
        ) : (
          <div className="mt-6 overflow-hidden rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-sand/50 text-left text-xs font-medium uppercase tracking-wider text-muted-ink">
                  <th className="px-4 py-3">Team</th>
                  <th className="px-4 py-3">Members</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {teams.map((t) => {
                  const busy = busyId === t.id;
                  return (
                    <Fragment key={t.id}>
                    <tr
                      className="border-b border-border last:border-b-0"
                    >
                      <td className="px-4 py-3">
                        {editingId === t.id ? (
                          <div className="flex items-center gap-2">
                            <input
                              value={editName}
                              onChange={(e) => setEditName(e.target.value)}
                              onKeyDown={(e) =>
                                e.key === "Enter" &&
                                patch(t.id, { name: editName.trim() })
                              }
                              autoFocus
                              className="rounded-md border border-border bg-surface px-2 py-1 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ring"
                            />
                            <button
                              onClick={() =>
                                patch(t.id, { name: editName.trim() })
                              }
                              disabled={busy || !editName.trim()}
                              className="rounded p-1 text-ok hover:bg-ok/10 disabled:opacity-50"
                              title="Save"
                            >
                              <Check className="h-4 w-4" />
                            </button>
                            <button
                              onClick={() => setEditingId(null)}
                              className="rounded p-1 text-muted-ink hover:bg-sand"
                              title="Cancel"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </div>
                        ) : (
                          <span className="inline-flex items-center gap-2 font-medium text-ink">
                            <UsersRound className="h-4 w-4 text-muted-ink" />
                            {t.name}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted-ink">
                        {t.member_count}
                      </td>
                      <td className="px-4 py-3">
                        {t.is_active ? (
                          <span className="inline-flex items-center gap-1.5 text-sm text-ok">
                            <span className="h-2 w-2 rounded-full bg-ok" />
                            Active
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-sm text-muted-ink">
                            <span className="h-2 w-2 rounded-full bg-muted-ink" />
                            Archived
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1">
                          {editingId !== t.id && (
                            <button
                              onClick={() => {
                                setEditingId(t.id);
                                setEditName(t.name);
                              }}
                              disabled={busy}
                              className="rounded p-1.5 text-muted-ink hover:bg-sand disabled:opacity-50"
                              title="Rename"
                            >
                              <Pencil className="h-4 w-4" />
                            </button>
                          )}
                          <button
                            onClick={() => {
                              const opening = personaId !== t.id;
                              setPersonaId(opening ? t.id : null);
                              if (opening) setPersonaText(t.persona ?? "");
                            }}
                            disabled={busy}
                            className={cn(
                              "rounded p-1.5 hover:bg-sand disabled:opacity-50",
                              personaId === t.id ? "text-clay" : "text-muted-ink",
                            )}
                            title="Edit persona"
                          >
                            <MessageSquareText className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() =>
                              patch(t.id, { is_active: !t.is_active })
                            }
                            disabled={busy}
                            className={cn(
                              "rounded p-1.5 hover:bg-sand disabled:opacity-50",
                              t.is_active ? "text-muted-ink" : "text-clay",
                            )}
                            title={t.is_active ? "Archive" : "Restore"}
                          >
                            {busy ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : t.is_active ? (
                              <Archive className="h-4 w-4" />
                            ) : (
                              <ArchiveRestore className="h-4 w-4" />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                    {personaId === t.id && (
                      <tr className="border-b border-border bg-sand/20 last:border-b-0">
                        <td colSpan={4} className="px-4 py-3">
                          <label className="mb-1 block text-xs font-medium text-muted-ink">
                            Persona: the voice injected into this team's generated
                            comments and reshares.
                          </label>
                          <textarea
                            value={personaText}
                            onChange={(e) => setPersonaText(e.target.value)}
                            rows={3}
                            maxLength={2000}
                            placeholder="e.g. An engineer's voice: precise, curious about how it works, skeptical of marketing spin."
                            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ring"
                          />
                          <div className="mt-2 flex justify-end gap-2">
                            <button
                              onClick={() => setPersonaId(null)}
                              className="rounded-md border border-border px-3 py-1.5 text-xs text-muted-ink hover:bg-sand"
                            >
                              Cancel
                            </button>
                            <button
                              onClick={() =>
                                patch(t.id, { persona: personaText.trim() })
                              }
                              disabled={busy}
                              className="inline-flex items-center gap-1.5 rounded-md bg-clay px-3 py-1.5 text-xs font-medium text-paper hover:bg-clay-press disabled:opacity-50"
                            >
                              {busy ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Check className="h-3.5 w-3.5" />
                              )}
                              Save persona
                            </button>
                          </div>
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppShell>
  );
}
