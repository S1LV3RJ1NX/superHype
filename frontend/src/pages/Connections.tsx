import { useEffect, useState } from "react";
import { AlertTriangle, Link2, Loader2, Trash2, Unplug } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { LinkedInLogo, XLogo } from "@/components/PlatformLogos";
import { apiFetch } from "@/lib/api";

interface Connection {
  id: string;
  platform: string;
  external_urn: string | null;
  display_name: string | null;
  status: string;
  needs_reconnect: boolean;
  connected_at: string;
  updated_at: string;
}

interface PlatformMeta {
  key: string;
  name: string;
  logo: () => JSX.Element;
  logoBg: string;
}

const PLATFORMS: PlatformMeta[] = [
  {
    key: "linkedin",
    name: "LinkedIn",
    logo: LinkedInLogo,
    logoBg: "bg-[#0A66C2]/10",
  },
  { key: "x", name: "X (Twitter)", logo: XLogo, logoBg: "bg-ink/10" },
];

export function Connections() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);

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

  return (
    <AppShell>
      <div className="mx-auto max-w-2xl">
        <h1 className="font-serif text-2xl text-ink">Connectors</h1>
        <p className="mt-1 text-sm text-muted-ink">
          Connector accounts to publish posts through super-hype.
        </p>

        {loading ? (
          <div className="mt-8 flex items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-ink" />
          </div>
        ) : (
          <div className="mt-6 space-y-4">
            {PLATFORMS.map((meta) => (
              <ConnectionCard
                key={meta.key}
                meta={meta}
                connection={
                  connections.find((c) => c.platform === meta.key) ?? null
                }
                onDisconnected={() =>
                  setConnections((prev) =>
                    prev.filter((c) => c.platform !== meta.key),
                  )
                }
              />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}

function ConnectionCard({
  meta,
  connection,
  onDisconnected,
}: {
  meta: PlatformMeta;
  connection: Connection | null;
  onDisconnected: () => void;
}) {
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const base = `/v1/connections/${meta.key}`;

  const handleConnect = async () => {
    setActionLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ authorize_url: string }>(
        `${base}/authorize`,
      );
      window.location.href = data.authorize_url;
      return;
    } catch (err) {
      setError(
        err instanceof Error ? err.message : `Could not start ${meta.name}.`,
      );
    }
    setActionLoading(false);
  };

  const handleReconnect = async () => {
    setActionLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ authorize_url: string }>(
        `${base}/reconnect`,
        { method: "POST" },
      );
      window.location.href = data.authorize_url;
      return;
    } catch (err) {
      setError(
        err instanceof Error ? err.message : `Could not start ${meta.name}.`,
      );
    }
    setActionLoading(false);
  };

  const handleDisconnect = async () => {
    if (!confirm(`Disconnect your ${meta.name} account? You can reconnect later.`))
      return;
    setActionLoading(true);
    try {
      await apiFetch(base, { method: "DELETE" });
      onDisconnected();
    } catch {
      // handled by apiFetch
    } finally {
      setActionLoading(false);
    }
  };

  const Logo = meta.logo;
  return (
    <div className="rounded-lg border border-border bg-surface p-6">
      <div className="flex items-center gap-3">
        <div
          className={`flex h-10 w-10 items-center justify-center rounded-lg ${meta.logoBg}`}
        >
          <Logo />
        </div>
        <div className="flex-1">
          <h2 className="font-medium text-ink">{meta.name}</h2>
          {connection ? (
            <p className="text-sm text-muted-ink">
              {connection.display_name ?? connection.external_urn ?? "Connected"}
            </p>
          ) : (
            <p className="text-sm text-muted-ink">Not connected</p>
          )}
        </div>

        {!connection && (
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

        {connection && !connection.needs_reconnect && (
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

        {connection && connection.needs_reconnect && (
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

      {error && <p className="mt-3 text-sm text-fail">{error}</p>}

      {connection && connection.needs_reconnect && (
        <div className="mt-4 flex items-start gap-2 rounded-md border border-pending/30 bg-pending/5 p-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-pending" />
          <div className="text-sm">
            <p className="font-medium text-ink">Reconnect needed</p>
            <p className="mt-0.5 text-muted-ink">
              {connection.status === "stale"
                ? `Your ${meta.name} access has expired. Reconnect to keep publishing posts.`
                : `Your ${meta.name} access is expiring soon. Reconnect now so approvals do not fail.`}
            </p>
          </div>
        </div>
      )}

      {connection && !connection.needs_reconnect && (
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
              {new Date(connection.connected_at).toLocaleDateString()}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
