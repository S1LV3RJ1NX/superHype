const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const TOKEN_KEY = "sh_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export async function apiFetch<T = unknown>(
  path: string,
  opts: RequestInit & { skipAuthRedirect?: boolean } = {},
): Promise<T> {
  const { skipAuthRedirect, ...fetchOpts } = opts;
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(fetchOpts.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { ...fetchOpts, headers });

  if (res.status === 401 && !skipAuthRedirect) {
    clearToken();
    window.location.href = "/";
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail;
    const message =
      typeof detail === "string"
        ? detail
        : (detail?.message ?? "Request failed");
    throw new ApiError(res.status, message, detail);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
