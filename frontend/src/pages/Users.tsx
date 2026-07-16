import { useCallback, useEffect, useState } from "react";
import { Link2, Loader2, Search, Shield, ShieldAlert, User } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { useAuth } from "@/auth/AuthContext";
import { apiFetch, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

interface UserRecord {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
  team_id: string | null;
  team_name: string | null;
  linkedin_status: string | null;
  x_status: string | null;
}

// Shared connection-status cell for the LinkedIn and X columns.
function ConnectionCell({ status }: { status: string | null }) {
  if (status === "active") {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-ok">
        <span className="h-2 w-2 rounded-full bg-ok" />
        Connected
      </span>
    );
  }
  if (status === "stale") {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-pending">
        <span className="h-2 w-2 rounded-full bg-pending" />
        Stale
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-muted-ink">
      <Link2 className="h-3.5 w-3.5" />
      Not connected
    </span>
  );
}

interface UsersPage {
  items: UserRecord[];
  next_cursor: string | null;
}

const ROLES = ["viewer", "editor", "admin"] as const;
const ROLE_ICONS = {
  admin: ShieldAlert,
  editor: Shield,
  viewer: User,
} as const;

export function Users() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const fetchUsers = useCallback(
    async (opts?: { cursor?: string | null; search?: string }) => {
      setLoading(true);
      try {
        const p = new URLSearchParams();
        p.set("limit", "20");
        if (opts?.cursor) p.set("cursor", opts.cursor);
        const q = (opts?.search ?? "").trim();
        if (q) p.set("search", q);
        const page = await apiFetch<UsersPage>(`/v1/users?${p.toString()}`);
        setUsers((prev) =>
          opts?.cursor ? [...prev, ...page.items] : page.items,
        );
        setCursor(page.next_cursor);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load users");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  // Search hits the server so it spans every user, not just loaded pages. This
  // also drives the initial load (search starts empty). Debounced so we do not
  // fire a request on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      fetchUsers({ search });
    }, 300);
    return () => clearTimeout(t);
  }, [search, fetchUsers]);

  const handleRoleChange = async (userId: string, newRole: string) => {
    setError(null);
    try {
      const updated = await apiFetch<UserRecord>(`/v1/users/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ role: newRole }),
      });
      setUsers((prev) =>
        prev.map((u) => (u.id === updated.id ? updated : u)),
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : "Role change failed");
      }
    }
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl">
        <h1 className="font-serif text-2xl text-ink">Team members</h1>
        <p className="mt-1 text-sm text-muted-ink">
          Manage roles. Only admins can access this page.
        </p>

        {error && (
          <div className="mt-4 rounded-md border border-fail/20 bg-fail/5 px-4 py-2 text-sm text-fail">
            {error}
          </div>
        )}

        <div className="relative mt-6">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-ink" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, email, or role"
            className="w-full rounded-md border border-border bg-surface py-2 pl-9 pr-3 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        {loading && users.length === 0 ? (
          <div className="mt-4 flex justify-center rounded-lg border border-border py-16">
            <Loader2 className="h-5 w-5 animate-spin text-muted-ink" />
          </div>
        ) : (
        <div className="mt-4 overflow-hidden rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-sand/50 text-left text-xs font-medium uppercase tracking-wider text-muted-ink">
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Team</th>
                <th className="px-4 py-3">LinkedIn</th>
                <th className="px-4 py-3">X</th>
                <th className="px-4 py-3">Role</th>
              </tr>
            </thead>
            <tbody>
              {users.length === 0 && !loading && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-8 text-center text-sm text-muted-ink"
                  >
                    No users match your search.
                  </td>
                </tr>
              )}
              {users.map((u) => {
                const RoleIcon =
                  ROLE_ICONS[u.role as keyof typeof ROLE_ICONS] ?? User;
                return (
                  <tr
                    key={u.id}
                    className="border-b border-border last:border-b-0"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        {u.avatar_url ? (
                          <img
                            src={u.avatar_url}
                            alt=""
                            className="h-8 w-8 rounded-full ring-1 ring-border"
                            referrerPolicy="no-referrer"
                          />
                        ) : (
                          <div className="h-8 w-8 rounded-full bg-clay/15 ring-1 ring-border" />
                        )}
                        <div>
                          <p className="font-medium text-ink">
                            {u.name ?? u.email}
                          </p>
                          {u.name && (
                            <p className="text-xs text-muted-ink">{u.email}</p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {u.team_name ? (
                        <span className="inline-flex items-center rounded-full bg-sand px-2.5 py-0.5 text-xs font-medium text-ink ring-1 ring-border">
                          {u.team_name}
                        </span>
                      ) : (
                        <span className="text-sm text-muted-ink">No team</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <ConnectionCell status={u.linkedin_status} />
                    </td>
                    <td className="px-4 py-3">
                      <ConnectionCell status={u.x_status} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <RoleIcon
                          className={cn(
                            "h-4 w-4",
                            u.role === "admin"
                              ? "text-clay"
                              : "text-muted-ink",
                          )}
                        />
                        <select
                          value={u.role}
                          onChange={(e) =>
                            handleRoleChange(u.id, e.target.value)
                          }
                          disabled={u.id === me?.id}
                          className={cn(
                            "rounded-md border border-border bg-surface px-2 py-1 text-sm text-ink",
                            "focus:outline-none focus:ring-2 focus:ring-ring",
                            u.id === me?.id && "cursor-not-allowed opacity-50",
                          )}
                        >
                          {ROLES.map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        )}

        {cursor && (
          <button
            onClick={() => fetchUsers({ cursor, search })}
            disabled={loading}
            className="mt-4 rounded-md border border-border px-4 py-2 text-sm text-muted-ink hover:bg-sand disabled:opacity-50"
          >
            {loading ? "Loading..." : "Load more"}
          </button>
        )}
      </div>
    </AppShell>
  );
}
