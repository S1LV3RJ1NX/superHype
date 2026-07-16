import { type ReactNode, useCallback, useEffect, useState } from "react";
import { Eye, Loader2, Megaphone, Pencil, Plus, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { AppShell } from "@/components/AppShell";
import { campaignStatusLabel } from "@/components/CampaignFields";
import { DeleteCampaignDialog } from "@/components/DeleteCampaignDialog";
import { ApiError, apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Campaign {
  id: string;
  title: string;
  type: string;
  platform: string;
  status: string;
  created_at: string;
  created_by: string | null;
}

const PLATFORM_LABEL: Record<string, string> = {
  linkedin: "LinkedIn",
  x: "X",
};

const DELETABLE_STATUSES = ["draft", "review", "failed"];
const EDITABLE_STATUSES = ["draft", "review"];

interface CampaignsPage {
  items: Campaign[];
  next_cursor: string | null;
}

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-sand text-muted-ink",
  generating: "bg-pending/15 text-pending",
  review: "bg-clay/15 text-clay",
  publishing: "bg-pending/15 text-pending",
  paused: "bg-pending/15 text-pending",
  completed: "bg-ok/15 text-ok",
  failed: "bg-fail/10 text-fail",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
        STATUS_STYLES[status] ?? "bg-sand text-muted-ink",
      )}
    >
      {campaignStatusLabel(status)}
    </span>
  );
}

export function Campaigns() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Campaign | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Production only deletes un-launched campaigns; local/dev can delete any
  // status (test cleanup), matching the backend gate.
  const canDelete = (c: Campaign) =>
    (import.meta.env.DEV || DELETABLE_STATUSES.includes(c.status)) &&
    (user?.role === "admin" || c.created_by === user?.id);

  const canEdit = (c: Campaign) =>
    EDITABLE_STATUSES.includes(c.status) &&
    (user?.role === "admin" || c.created_by === user?.id);

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setError(null);
    try {
      await apiFetch(`/v1/campaigns/${deleteTarget.id}`, { method: "DELETE" });
      setCampaigns((prev) => prev.filter((c) => c.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to delete campaign",
      );
    } finally {
      setDeleting(false);
    }
  };

  const fetchCampaigns = useCallback(async (nextCursor?: string | null) => {
    setLoading(true);
    try {
      const qs = nextCursor ? `?cursor=${nextCursor}` : "";
      const page = await apiFetch<CampaignsPage>(`/v1/campaigns${qs}`);
      setCampaigns((prev) => (nextCursor ? [...prev, ...page.items] : page.items));
      setCursor(page.next_cursor);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load campaigns");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCampaigns();
  }, [fetchCampaigns]);

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-serif text-2xl text-ink">Campaigns</h1>
            <p className="mt-1 text-sm text-muted-ink">
              Amplify an existing post, or distribute variations across the team.
            </p>
          </div>
          <button
            onClick={() => navigate("/app/campaigns/new")}
            className="inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2 text-sm font-medium text-paper hover:opacity-90"
          >
            <Plus className="h-4 w-4" />
            New campaign
          </button>
        </div>

        {error && (
          <div className="mt-4 rounded-md border border-fail/20 bg-fail/5 px-4 py-2 text-sm text-fail">
            {error}
          </div>
        )}

        <div className="mt-6 overflow-hidden rounded-lg border border-border">
          {loading && campaigns.length === 0 ? (
            <div className="flex flex-col items-center gap-2 p-12 text-center text-muted-ink">
              <Loader2 className="h-6 w-6 animate-spin" />
              <p className="text-sm">Loading campaigns...</p>
            </div>
          ) : campaigns.length === 0 ? (
            <div className="flex flex-col items-center gap-2 p-12 text-center">
              <Megaphone className="h-8 w-8 text-muted-ink" />
              <p className="text-sm text-muted-ink">No campaigns yet.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-sand/50 text-left text-xs font-medium uppercase tracking-wider text-muted-ink">
                  <th className="px-4 py-3">Title</th>
                  <th className="px-4 py-3">Platform</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => navigate(`/app/campaigns/${c.id}`)}
                    className="cursor-pointer border-b border-border last:border-b-0 hover:bg-sand/30"
                  >
                    <td className="px-4 py-3 font-medium text-ink">{c.title}</td>
                    <td className="px-4 py-3 text-muted-ink">
                      {PLATFORM_LABEL[c.platform] ?? "LinkedIn"}
                    </td>
                    <td className="px-4 py-3 capitalize text-muted-ink">{c.type}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={c.status} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <IconAction
                          label="View"
                          onClick={() => navigate(`/app/campaigns/${c.id}`)}
                        >
                          <Eye className="h-3.5 w-3.5" />
                        </IconAction>
                        {canEdit(c) && (
                          <IconAction
                            label="Edit"
                            onClick={() => navigate(`/app/campaigns/${c.id}/edit`)}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </IconAction>
                        )}
                        {canDelete(c) && (
                          <IconAction
                            label="Delete"
                            danger
                            onClick={() => setDeleteTarget(c)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </IconAction>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {cursor && (
          <button
            onClick={() => fetchCampaigns(cursor)}
            disabled={loading}
            className="mt-4 rounded-md border border-border px-4 py-2 text-sm text-muted-ink hover:bg-sand"
          >
            {loading ? "Loading..." : "Load more"}
          </button>
        )}
      </div>

      {deleteTarget && (
        <DeleteCampaignDialog
          title={deleteTarget.title}
          busy={deleting}
          onConfirm={confirmDelete}
          onClose={() => !deleting && setDeleteTarget(null)}
        />
      )}
    </AppShell>
  );
}

function IconAction({
  label,
  onClick,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      title={label}
      aria-label={label}
      className={cn(
        "inline-flex items-center justify-center rounded-md border p-1.5 transition-colors",
        danger
          ? "border-fail/20 bg-fail/5 text-fail hover:bg-fail/10"
          : "border-border text-muted-ink hover:bg-sand hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
