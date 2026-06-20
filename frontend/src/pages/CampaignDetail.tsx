import { type ReactNode, useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Check,
  Pencil,
  RefreshCw,
  Rocket,
  SkipForward,
  Trash2,
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { AppShell } from "@/components/AppShell";
import { campaignStatusLabel, Hint } from "@/components/CampaignFields";
import { DeleteCampaignDialog } from "@/components/DeleteCampaignDialog";
import { type RosterUser, SmallButton } from "@/components/PlanBuilder";
import { ApiError, apiFetch } from "@/lib/api";

const DELETABLE_STATUSES = ["draft", "review", "failed"];
const EDITABLE_STATUSES = ["draft", "review"];

interface Campaign {
  id: string;
  title: string;
  type: string;
  status: string;
  seed_urn: string | null;
  seed_content: string | null;
  created_by: string | null;
  launched_at: string | null;
  post_count: number;
  counts: Record<string, number>;
}

interface Post {
  id: string;
  user_id: string;
  action: string;
  body: string | null;
  status: string;
  target_post_id: string | null;
  error: string | null;
}

export function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [roster, setRoster] = useState<RosterUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [actingIds, setActingIds] = useState<Set<string>>(new Set());
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const startActing = (postId: string) =>
    setActingIds((prev) => new Set(prev).add(postId));
  const stopActing = (postId: string) =>
    setActingIds((prev) => {
      const next = new Set(prev);
      next.delete(postId);
      return next;
    });

  const canDelete =
    !!campaign &&
    DELETABLE_STATUSES.includes(campaign.status) &&
    (user?.role === "admin" || campaign.created_by === user?.id);

  const canEdit =
    !!campaign &&
    EDITABLE_STATUSES.includes(campaign.status) &&
    (user?.role === "admin" || campaign.created_by === user?.id);

  const confirmDelete = async () => {
    if (!campaign) return;
    setDeleting(true);
    setError(null);
    try {
      await apiFetch(`/v1/campaigns/${campaign.id}`, { method: "DELETE" });
      navigate("/app/campaigns");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to delete campaign",
      );
      setDeleting(false);
    }
  };

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [c, p, r] = await Promise.all([
        apiFetch<Campaign>(`/v1/campaigns/${id}`),
        apiFetch<{ items: Post[] }>(`/v1/campaigns/${id}/posts`),
        apiFetch<{ items: RosterUser[] }>(`/v1/users/roster`),
      ]);
      setCampaign(c);
      setPosts(p.items);
      setRoster(r.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load campaign");
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  // Campaign-level action (Launch): blocks the header while it runs.
  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  // Per-post action: only the acted-on card is disabled while it runs.
  const runPost = async (postId: string, fn: () => Promise<unknown>) => {
    setError(null);
    startActing(postId);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed");
    } finally {
      stopActing(postId);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  // Approve, but if the user's LinkedIn token needs re-consent, send them through
  // the authorize flow carrying this post so the callback resumes the approve.
  const approvePost = async (postId: string) => {
    setError(null);
    startActing(postId);
    try {
      await apiFetch(`/v1/posts/${postId}/approve`, { method: "POST" });
      await load();
    } catch (err) {
      const code =
        err instanceof ApiError
          ? (err.detail as { code?: string } | undefined)?.code
          : undefined;
      if (err instanceof ApiError && code === "linkedin_reconnect_required") {
        try {
          const { authorize_url } = await apiFetch<{ authorize_url: string }>(
            `/v1/connections/linkedin/authorize?resume_post_id=${postId}`,
          );
          window.location.href = authorize_url;
          return;
        } catch {
          setError("Could not start LinkedIn reconnect. Please try again.");
        }
      } else {
        setError(err instanceof ApiError ? err.message : "Action failed");
      }
    } finally {
      stopActing(postId);
    }
  };

  if (!campaign) {
    return (
      <AppShell>
        <div className="mx-auto max-w-5xl">
          {error ? (
            <p className="text-sm text-fail">{error}</p>
          ) : (
            <p className="text-sm text-muted-ink">Loading...</p>
          )}
        </div>
      </AppShell>
    );
  }

  const published = campaign.counts.published ?? 0;
  const total = campaign.post_count;

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl">
        <Link
          to="/app/campaigns"
          className="inline-flex items-center gap-1.5 text-sm text-muted-ink hover:text-ink"
        >
          <ArrowLeft className="h-4 w-4" />
          Campaigns
        </Link>

        <div className="mt-2 flex items-start justify-between">
          <div>
            <h1 className="font-serif text-2xl text-ink">{campaign.title}</h1>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex rounded-full bg-sand px-2.5 py-0.5 text-xs font-medium capitalize text-muted-ink">
              {campaign.type}
            </span>
            <span
              className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${
                CAMPAIGN_STATUS_STYLES[campaign.status] ??
                "bg-sand text-muted-ink"
              }`}
            >
              {campaignStatusLabel(campaign.status)}
            </span>
            <button
              onClick={refresh}
              disabled={refreshing}
              title="Refresh to see newly generated or published items"
              className="inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm font-medium text-ink hover:bg-sand disabled:opacity-50"
            >
              <RefreshCw
                className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
              />
              Refresh
            </button>
            {canEdit && (
              <button
                onClick={() => navigate(`/app/campaigns/${id}/edit`)}
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm font-medium text-ink hover:bg-sand disabled:opacity-50"
              >
                <Pencil className="h-4 w-4" />
                Edit
              </button>
            )}
            {canDelete && (
              <button
                onClick={() => setDeleteOpen(true)}
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm font-medium text-fail hover:bg-fail/10 disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" />
                Delete
              </button>
            )}
            {campaign.status === "review" && (
              <button
                onClick={() =>
                  run(() =>
                    apiFetch(`/v1/campaigns/${id}/launch`, { method: "POST" }),
                  )
                }
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-md bg-clay px-4 py-2 text-sm font-medium text-paper hover:bg-clay-press disabled:opacity-50"
              >
                <Rocket className="h-4 w-4" />
                Launch
              </button>
            )}
          </div>
        </div>

        {error && (
          <div className="mt-4 rounded-md border border-fail/20 bg-fail/5 px-4 py-2 text-sm text-fail">
            {error}
          </div>
        )}

        {total > 0 && (
          <div className="mt-4">
            <div className="flex justify-between text-xs text-muted-ink">
              <span>Published</span>
              <span className="tabular">
                {published} of {total}
              </span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-sand">
              <div
                className="h-full bg-ok transition-all"
                style={{ width: total ? `${(published / total) * 100}%` : "0%" }}
              />
            </div>
          </div>
        )}

        <div className="mt-6 grid gap-6 md:grid-cols-[340px_1fr]">
          <div>
            <Panel title="Seed">
              {campaign.seed_urn && (
                <p className="break-all text-xs text-muted-ink">
                  {campaign.seed_urn}
                </p>
              )}
              {campaign.seed_content && (
                <p className="mt-2 whitespace-pre-wrap text-sm text-ink">
                  {campaign.seed_content}
                </p>
              )}
              {!campaign.seed_urn && !campaign.seed_content && (
                <p className="text-sm text-muted-ink">No seed provided.</p>
              )}
            </Panel>
          </div>

          <div>
            <h2 className="text-sm font-medium text-ink">
              Posts &amp; interactions
            </h2>
            {posts.length > 0 && !campaign.launched_at && (
              <div className="mt-3">
                <Hint>
                  Approvals unlock after you launch. Until then you can edit the
                  plan. Launch notifies each person to approve, and approving is
                  what publishes their item.
                </Hint>
              </div>
            )}
            <div className="mt-3 space-y-3">
              {posts.length === 0 && (
                <p className="text-sm text-muted-ink">
                  {canEdit
                    ? "No posts yet. Use Edit to build the plan."
                    : "No posts yet."}
                </p>
              )}
              {posts.map((post) => (
                <PostCard
                  key={post.id}
                  post={post}
                  roster={roster}
                  meId={user?.id}
                  isAdmin={user?.role === "admin"}
                  launched={!!campaign.launched_at}
                  busy={actingIds.has(post.id)}
                  onEdit={(body) =>
                    runPost(post.id, () =>
                      apiFetch(`/v1/posts/${post.id}`, {
                        method: "PATCH",
                        body: JSON.stringify({ body }),
                      }),
                    )
                  }
                  onApprove={() => approvePost(post.id)}
                  onSkip={() =>
                    runPost(post.id, () =>
                      apiFetch(`/v1/posts/${post.id}/skip`, { method: "POST" }),
                    )
                  }
                />
              ))}
            </div>
          </div>
        </div>
      </div>

      {deleteOpen && (
        <DeleteCampaignDialog
          title={campaign.title}
          busy={deleting}
          onConfirm={confirmDelete}
          onClose={() => !deleting && setDeleteOpen(false)}
        />
      )}
    </AppShell>
  );
}

function PostCard({
  post,
  roster,
  meId,
  isAdmin,
  launched,
  busy,
  onEdit,
  onApprove,
  onSkip,
}: {
  post: Post;
  roster: RosterUser[];
  meId?: string;
  isAdmin: boolean;
  launched: boolean;
  busy: boolean;
  onEdit: (body: string) => void;
  onApprove: () => void;
  onSkip: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(post.body ?? "");
  const owner = roster.find((u) => u.id === post.user_id);
  const canAct = isAdmin || post.user_id === meId;
  const pending = post.status === "pending" || post.status === "scheduled";

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="rounded bg-sand px-2 py-0.5 text-xs font-medium capitalize text-muted-ink">
            {ACTION_LABEL[post.action] ?? post.action.replace("_", " ")}
          </span>
          <span className="text-sm text-ink">
            {owner?.name ?? owner?.email ?? "Unknown"}
          </span>
        </div>
        <StatusBadge status={post.status} />
      </div>

      {post.action !== "like" && (
        <div className="mt-2">
          {editing ? (
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={3}
              className="input"
            />
          ) : (
            <p className="whitespace-pre-wrap text-sm text-ink">
              {post.body || (
                <span className="text-muted-ink">No text yet.</span>
              )}
            </p>
          )}
        </div>
      )}

      {post.error && <p className="mt-2 text-xs text-fail">{post.error}</p>}

      {canAct && pending && (
        <div className="mt-3 flex flex-wrap gap-2">
          {post.action !== "like" &&
            (editing ? (
              <>
                <SmallButton
                  label="Save"
                  onClick={() => {
                    onEdit(draft);
                    setEditing(false);
                  }}
                  disabled={busy}
                />
                <SmallButton label="Cancel" onClick={() => setEditing(false)} />
              </>
            ) : (
              <SmallButton label="Edit" onClick={() => setEditing(true)} />
            ))}
          {launched && (
            <>
              <button
                onClick={onApprove}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-md bg-ok/10 px-3 py-1.5 text-xs font-medium text-ok hover:bg-ok/20 disabled:opacity-50"
              >
                <Check className="h-3.5 w-3.5" />
                Approve
              </button>
              <button
                onClick={onSkip}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-ink hover:bg-sand disabled:opacity-50"
              >
                <SkipForward className="h-3.5 w-3.5" />
                Skip
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

const ACTION_LABEL: Record<string, string> = {
  like: "like",
  comment: "comment",
  repost_comment: "repost thought",
  post: "post",
};

const CAMPAIGN_STATUS_STYLES: Record<string, string> = {
  draft: "bg-sand text-muted-ink",
  generating: "bg-pending/15 text-pending",
  review: "bg-clay/15 text-clay",
  publishing: "bg-ok/15 text-ok",
  completed: "bg-ok text-paper",
  failed: "bg-fail/10 text-fail",
};

const STATUS_BADGE: Record<string, string> = {
  pending: "bg-pending/15 text-pending",
  scheduled: "bg-pending/15 text-pending",
  approved: "bg-ok/15 text-ok",
  published: "bg-ok text-paper",
  failed: "bg-fail/15 text-fail",
  skipped: "bg-sand text-muted-ink",
};

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_BADGE[status] ?? "bg-sand text-muted-ink";
  return (
    <span
      className={`rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${style}`}
    >
      {status}
    </span>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mb-4 rounded-lg border border-border bg-surface p-4">
      <h2 className="mb-2 text-sm font-medium text-ink">{title}</h2>
      {children}
    </div>
  );
}
