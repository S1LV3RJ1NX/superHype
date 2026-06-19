import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import type { ReactNode } from "react";

import { apiFetch, clearToken, getToken, setToken } from "@/lib/api";

export interface AppUser {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
  role: string;
  is_active: boolean;
}

interface AuthContextValue {
  user: AppUser | null;
  loading: boolean;
  login: (token: string) => Promise<void>;
  logout: () => void;
}

const AuthCtx = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AppUser | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchMe = useCallback(async () => {
    try {
      const me = await apiFetch<AppUser>("/v1/users/me");
      setUser(me);
    } catch {
      clearToken();
      setUser(null);
    }
  }, []);

  useEffect(() => {
    if (getToken()) {
      fetchMe().finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [fetchMe]);

  const login = useCallback(
    async (token: string) => {
      setToken(token);
      await fetchMe();
    },
    [fetchMe],
  );

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    window.location.href = "/";
  }, []);

  return (
    <AuthCtx.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
