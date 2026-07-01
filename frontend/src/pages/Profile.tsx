import { useEffect, useState } from "react";
import { Check, Loader2, Shield, ShieldAlert, User } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { useAuth } from "@/auth/AuthContext";
import { apiFetch, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Team {
  id: string;
  name: string;
}

const ROLE_ICONS = {
  admin: ShieldAlert,
  editor: Shield,
  viewer: User,
} as const;

export function Profile() {
  const { user, refresh } = useAuth();
  const [teams, setTeams] = useState<Team[]>([]);
  const [selected, setSelected] = useState<string | null>(user?.team_id ?? null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const page = await apiFetch<{ items: Team[] }>("/v1/teams?limit=100");
        setTeams(page.items);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load teams");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    setSelected(user?.team_id ?? null);
  }, [user?.team_id]);

  const save = async () => {
    if (!selected || selected === user?.team_id) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await apiFetch("/v1/users/me", {
        method: "PATCH",
        body: JSON.stringify({ team_id: selected }),
      });
      await refresh();
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your team");
    } finally {
      setSaving(false);
    }
  };

  const RoleIcon =
    ROLE_ICONS[(user?.role ?? "viewer") as keyof typeof ROLE_ICONS] ?? User;
  const dirty = selected !== null && selected !== user?.team_id;

  return (
    <AppShell>
      <div className="mx-auto max-w-2xl">
        <h1 className="font-serif text-2xl text-ink">Your profile</h1>
        <p className="mt-1 text-sm text-muted-ink">
          Your identity and team. Changing your team updates who campaigns can
          reach through you.
        </p>

        {error && (
          <div className="mt-4 rounded-md border border-fail/20 bg-fail/5 px-4 py-2 text-sm text-fail">
            {error}
          </div>
        )}

        <div className="mt-6 flex items-center gap-4 rounded-lg border border-border p-4">
          {user?.avatar_url ? (
            <img
              src={user.avatar_url}
              alt=""
              className="h-12 w-12 rounded-full ring-1 ring-border"
              referrerPolicy="no-referrer"
            />
          ) : (
            <div className="h-12 w-12 rounded-full bg-clay/15 ring-1 ring-border" />
          )}
          <div className="min-w-0">
            <p className="font-medium text-ink">{user?.name ?? user?.email}</p>
            <p className="text-sm text-muted-ink">{user?.email}</p>
          </div>
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs text-muted-ink">
            <RoleIcon className="h-3.5 w-3.5" />
            {user?.role}
          </span>
        </div>

        <h2 className="mt-8 font-serif text-lg text-ink">Team</h2>
        {loading ? (
          <div className="mt-4 flex justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-ink" />
          </div>
        ) : (
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {teams.map((t) => {
              const active = selected === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => {
                    setSelected(t.id);
                    setSaved(false);
                  }}
                  className={cn(
                    "flex items-center justify-between rounded-lg border px-4 py-3 text-left text-sm transition-colors",
                    active
                      ? "border-clay bg-clay/5 font-medium text-ink"
                      : "border-border text-muted-ink hover:bg-sand",
                  )}
                >
                  {t.name}
                  {active && <Check className="h-4 w-4 text-clay" />}
                </button>
              );
            })}
          </div>
        )}

        <div className="mt-6 flex items-center gap-3">
          <button
            onClick={save}
            disabled={!dirty || saving}
            className="inline-flex items-center gap-2 rounded-md bg-clay px-5 py-2.5 text-sm font-medium text-paper hover:bg-clay-press disabled:opacity-50"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            Save team
          </button>
          {saved && !dirty && (
            <span className="inline-flex items-center gap-1.5 text-sm text-ok">
              <Check className="h-4 w-4" />
              Saved
            </span>
          )}
        </div>
      </div>
    </AppShell>
  );
}
