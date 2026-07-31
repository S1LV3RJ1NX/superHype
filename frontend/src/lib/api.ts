const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const TOKEN_KEY = "sh_token";
const ONBOARDING_PATH = "/app/onboarding";

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
    // The API now enforces onboarding too. Hitting this means the client-side
    // gate was bypassed (a stale tab, a direct call), so send them to finish it
    // rather than surfacing a permission error they cannot act on.
    if (
      res.status === 403 &&
      detail?.code === "onboarding_incomplete" &&
      !skipAuthRedirect &&
      window.location.pathname !== ONBOARDING_PATH
    ) {
      window.location.href = ONBOARDING_PATH;
    }
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

export async function uploadAsset(file: File): Promise<{ id: string }> {
  const token = getToken();
  const form = new FormData();
  form.append("file", file);
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}/v1/assets`, {
    method: "POST",
    body: form,
    headers,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail;
    const message =
      typeof detail === "string" ? detail : (detail?.message ?? "Upload failed");
    throw new ApiError(res.status, message, detail);
  }
  return res.json() as Promise<{ id: string }>;
}

export interface ManualDraftPayload {
  post_body: string | null;
  self_comment: string | null;
  comments: string[];
}

export interface DraftRowMatch {
  row: number;
  email: string | null;
  name: string | null;
  user_id: string;
  user_name: string | null;
  user_email: string;
  matched_by: string;
  draft: ManualDraftPayload;
  warnings: string[];
}

export interface DraftRowUnmatched {
  row: number;
  email: string | null;
  name: string | null;
  reason: string;
}

export interface DraftImportPreview {
  matched: DraftRowMatch[];
  unmatched: DraftRowUnmatched[];
}

export async function previewCampaignDrafts(
  campaignId: string,
  file: File,
): Promise<DraftImportPreview> {
  const token = getToken();
  const form = new FormData();
  form.append("file", file);
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(
    `${API_BASE}/v1/campaigns/${campaignId}/drafts/preview`,
    { method: "POST", body: form, headers },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail;
    const message =
      typeof detail === "string" ? detail : (detail?.message ?? "Upload failed");
    throw new ApiError(res.status, message, detail);
  }
  return res.json() as Promise<DraftImportPreview>;
}

export async function downloadDraftsTemplate(): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}/v1/campaigns/drafts/template`, {
    headers,
  });
  if (!res.ok) {
    throw new ApiError(res.status, "Failed to download the sample template");
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "super-hype-drafts.xlsx";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function fetchAssetObjectUrl(
  id: string,
): Promise<{ url: string; contentType: string }> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}/v1/assets/${id}`, { headers });
  if (!res.ok) {
    throw new ApiError(res.status, "Failed to load media");
  }
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), contentType: blob.type };
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
