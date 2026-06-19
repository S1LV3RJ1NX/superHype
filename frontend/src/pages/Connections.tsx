import { useEffect, useState } from "react";
import { AlertTriangle, Link2, Loader2, Trash2, Unplug } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { apiFetch } from "@/lib/api";

interface Connection {
  id: string;
  platform: string;
  external_urn: string | null;
  display_name: string | null;
  status: string;
  connected_at: string;
  updated_at: string;
}

export function Connections() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);

  const fetchConnections = async () => {
    try {
      const data = await apiFetch<Connection[]>("/v1/connections");
      setConnections(data);
    } catch {
      // handled by apiFetch (401 redirect)
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConnections();
  }, []);

  const linkedin = connections.find((c) => c.platform === "linkedin");

  const handleConnect = async () => {
    setActionLoading(true);
    try {
      const data = await apiFetch<{ authorize_url: string }>(
        "/v1/connections/linkedin/authorize",
      );
      window.location.href = data.authorize_url;
      return;
    } catch {
      // fall through
    }
    setActionLoading(false);
  };

  const handleReconnect = async () => {
    setActionLoading(true);
    try {
      const data = await apiFetch<{ authorize_url: string }>(
        "/v1/connections/linkedin/reconnect",
        { method: "POST" },
      );
      window.location.href = data.authorize_url;
      return;
    } catch {
      // fall through
    }
    setActionLoading(false);
  };

  const handleDisconnect = async () => {
    if (!confirm("Disconnect your LinkedIn account? You can reconnect later.")) return;
    setActionLoading(true);
    try {
      await apiFetch("/v1/connections/linkedin", { method: "DELETE" });
      setConnections((prev) => prev.filter((c) => c.platform !== "linkedin"));
    } catch {
      // handled by apiFetch
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-2xl">
        <h1 className="font-serif text-2xl text-ink">Connections</h1>
        <p className="mt-1 text-sm text-muted-ink">
          Connect your LinkedIn account to publish posts through super-hype.
        </p>

        {loading ? (
          <div className="mt-8 flex items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-ink" />
          </div>
        ) : (
          <div className="mt-6 rounded-lg border border-border bg-surface p-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#0A66C2]/10">
                <LinkedInLogo />
              </div>
              <div className="flex-1">
                <h2 className="font-medium text-ink">LinkedIn</h2>
                {linkedin ? (
                  <p className="text-sm text-muted-ink">
                    {linkedin.display_name ?? linkedin.external_urn ?? "Connected"}
                  </p>
                ) : (
                  <p className="text-sm text-muted-ink">Not connected</p>
                )}
              </div>

              {!linkedin && (
                <button
                  onClick={handleConnect}
                  disabled={actionLoading}
                  className="inline-flex items-center gap-2 rounded-md bg-clay px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-clay-press disabled:opacity-60"
                >
                  {actionLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Link2 className="h-4 w-4" />
                  )}
                  Connect
                </button>
              )}

              {linkedin && linkedin.status === "active" && (
                <button
                  onClick={handleDisconnect}
                  disabled={actionLoading}
                  className="inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm text-muted-ink transition-colors hover:bg-sand disabled:opacity-60"
                >
                  {actionLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                  Disconnect
                </button>
              )}

              {linkedin && linkedin.status === "stale" && (
                <button
                  onClick={handleReconnect}
                  disabled={actionLoading}
                  className="inline-flex items-center gap-2 rounded-md bg-clay px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-clay-press disabled:opacity-60"
                >
                  {actionLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Unplug className="h-4 w-4" />
                  )}
                  Reconnect
                </button>
              )}
            </div>

            {linkedin && linkedin.status === "stale" && (
              <div className="mt-4 flex items-start gap-2 rounded-md border border-pending/30 bg-pending/5 p-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-pending" />
                <div className="text-sm">
                  <p className="font-medium text-ink">Token expired</p>
                  <p className="mt-0.5 text-muted-ink">
                    Your LinkedIn access has expired. Reconnect to continue
                    publishing posts.
                  </p>
                </div>
              </div>
            )}

            {linkedin && linkedin.status === "active" && (
              <div className="mt-4 grid grid-cols-2 gap-4 border-t border-border pt-4 text-sm">
                <div>
                  <p className="text-muted-ink">Status</p>
                  <p className="mt-0.5 flex items-center gap-1.5 font-medium text-ok">
                    <span className="h-2 w-2 rounded-full bg-ok" />
                    Active
                  </p>
                </div>
                <div>
                  <p className="text-muted-ink">Connected</p>
                  <p className="mt-0.5 text-ink">
                    {new Date(linkedin.connected_at).toLocaleDateString()}
                  </p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}

function LinkedInLogo() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="#0A66C2">
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  );
}
