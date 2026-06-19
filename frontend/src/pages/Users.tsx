import { useCallback, useEffect, useState } from "react";
import { Shield, ShieldAlert, User } from "lucide-react";

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

  const fetchUsers = useCallback(async (nextCursor?: string | null) => {
    setLoading(true);
    try {
      const qs = nextCursor ? `?cursor=${nextCursor}` : "";
      const page = await apiFetch<UsersPage>(`/v1/users${qs}`);
      setUsers((prev) =>
        nextCursor ? [...prev, ...page.items] : page.items,
      );
      setCursor(page.next_cursor);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

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

        <div className="mt-6 overflow-hidden rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-sand/50 text-left text-xs font-medium uppercase tracking-wider text-muted-ink">
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Role</th>
              </tr>
            </thead>
            <tbody>
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

        {cursor && (
          <button
            onClick={() => fetchUsers(cursor)}
            disabled={loading}
            className="mt-4 rounded-md border border-border px-4 py-2 text-sm text-muted-ink hover:bg-sand"
          >
            {loading ? "Loading..." : "Load more"}
          </button>
        )}
      </div>
    </AppShell>
  );
}
