import { type ReactNode, useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  Link2,
  Loader2,
  Pause,
  Pencil,
  Play,
  RefreshCw,
  Rocket,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { AppShell } from "@/components/AppShell";
import { campaignStatusLabel, Hint } from "@/components/CampaignFields";
import { DeleteCampaignDialog } from "@/components/DeleteCampaignDialog";
import { type RosterUser } from "@/components/PlanBuilder";
import {
  CombinedEngagementCard,
  type Post,
  PostCard,
} from "@/components/PostCards";
import { ApiError, apiFetch } from "@/lib/api";
import { platformLabel } from "@/lib/platform";

const DELETABLE_STATUSES = ["draft", "review", "failed"];
const EDITABLE_STATUSES = ["draft", "review"];

interface Campaign {
  id: string;
  title: string;
  type: string;
  platform: string;
  status: string;
  seed_urn: string | null;
  seed_content: string | null;
  created_by: string | null;
  launched_at: string | null;
  scheduled_at: string | null;
  schedule_timezone: string | null;
  post_count: number;
  counts: Record<string, number>;
}

interface Readiness {
  pending_count: number;
  platform: string;
  requires_connection: boolean;
  connected: boolean;
  needs_reconnect: boolean;
}

export function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [roster, setRoster] = useState<RosterUser[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [actingIds, setActingIds] = useState<Set<string>>(new Set());
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);

  const startActing = (postId: string) =>
    setActingIds((prev) => new Set(prev).add(postId));
  const stopActing = (postId: string) =>
    setActingIds((prev) => {
      const next = new Set(prev);
      next.delete(postId);
      return next;
    });

  // Admins can delete a campaign in any state (cleanup, pilot resets). A plain
  // creator is limited to un-launched statuses in production (launched campaigns
  // have in-flight posts); local/dev lets the creator delete any status too.
  // Mirrors the backend gate in campaign_controller.delete_campaign.
  const canDelete =
    !!campaign &&
    (user?.role === "admin" ||
      ((import.meta.env.DEV || DELETABLE_STATUSES.includes(campaign.status)) &&
        campaign.created_by === user?.id));

  const canEdit =
    !!campaign &&
    EDITABLE_STATUSES.includes(campaign.status) &&
    (user?.role === "admin" || campaign.created_by === user?.id);

  // Pause/resume a launched campaign: creator or admin only.
  const canManage =
    !!campaign && (user?.role === "admin" || campaign.created_by === user?.id);

  // Reset rewinds a launched campaign back to review so it can be launched
  // again. Gate on launched_at (not just status) so a never-launched campaign
  // that failed during generation does not show a Reset that the backend 409s.
  // Same creator-or-admin gate as pause/resume.
  const canReset =
    canManage &&
    !!campaign &&
    !!campaign.launched_at &&
    ["publishing", "paused", "completed", "failed"].includes(campaign.status);

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

  // Merge a single post returned by an action into local state, so the card
  // updates instantly without refetching the whole page.
  const applyPost = useCallback((updated: Post) => {
    setPosts((prev) =>
      prev.map((p) => (p.id === updated.id ? { ...p, ...updated } : p)),
    );
  }, []);

  // Reconcile campaign-level counts and status (e.g. progress, completion) in
  // the background after a per-post action, without blocking the card's spinner.
  const refreshCampaign = useCallback(async () => {
    if (!id) return;
    try {
      const c = await apiFetch<Campaign>(`/v1/campaigns/${id}`);
      setCampaign(c);
    } catch {
      // Non-fatal: the next poll or manual refresh will catch up.
    }
  }, [id]);

  // Pre-flight LinkedIn check for me on this campaign, so we can prompt a
  // reconnect before I start approving instead of failing mid-flow.
  const refreshReadiness = useCallback(async () => {
    if (!id) return;
    try {
      const r = await apiFetch<Readiness>(
        `/v1/campaigns/${id}/approval-readiness`,
      );
      setReadiness(r);
    } catch {
      // Non-fatal: approval still has its own reconnect-then-act fallback.
    }
  }, [id]);

  // Proactively send me through re-consent (no resume_post_id) so I land back
  // here connected and ready to approve. The connector is the campaign's
  // platform (linkedin or x).
  const reconnect = async () => {
    const platform = readiness?.platform ?? campaign?.platform ?? "linkedin";
    setReconnecting(true);
    try {
      const { authorize_url } = await apiFetch<{ authorize_url: string }>(
        `/v1/connections/${platform}/authorize`,
      );
      window.location.href = authorize_url;
    } catch {
      setError(
        `Could not start ${platformLabel(platform)} reconnect. Please try again.`,
      );
      setReconnecting(false);
    }
  };

  useEffect(() => {
    load();
    refreshReadiness();
  }, [load, refreshReadiness]);

  // While the campaign is doing background work (generating drafts, or
  // publishing after launch), poll so new or published items appear without a
  // manual refresh. Also poll while any single post is mid-flight ("approved"
  // is transient: the worker turns it into published or an assisted ask), so an
  // approved item resolves on screen without a manual refresh. Polling stops as
  // soon as everything settles.
  const hasInFlightPost = posts.some(
    (p) => p.status === "approved" || p.status === "scheduled",
  );
  // Launch is async: the controller stamps launched_at, then a worker flips
  // review -> publishing. Treat that gap as busy so the status settles on screen.
  const launching = campaign?.status === "review" && !!campaign?.launched_at;
  useEffect(() => {
    const status = campaign?.status;
    const busyCampaign = status === "generating" || status === "publishing";
    if (!busyCampaign && !hasInFlightPost && !launching) return;
    const timer = setInterval(() => {
      load();
    }, 3000);
    return () => clearInterval(timer);
  }, [campaign?.status, hasInFlightPost, launching, load]);

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

  // Per-post action: only the acted-on card is disabled while it runs. The
  // action returns the updated post, so we apply it directly (instant) and
  // reconcile campaign counts in the background instead of reloading the page.
  const runPost = async (postId: string, fn: () => Promise<Post>) => {
    setError(null);
    startActing(postId);
    try {
      const updated = await fn();
      applyPost(updated);
      void refreshCampaign();
      void refreshReadiness();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed");
    } finally {
      stopActing(postId);
    }
  };

  // Batch action for the combined like+comment card: approve, ack, or skip both
  // rows in one atomic request. The rows are assisted (own-browser) actions, so
  // approve never hits the reconnect gate; a plain error surface is enough.
  const runBatch = async (
    ids: string[],
    op: "approve" | "ack" | "skip",
  ) => {
    setError(null);
    ids.forEach(startActing);
    try {
      const updated = await apiFetch<Post[]>(`/v1/posts/batch`, {
        method: "POST",
        body: JSON.stringify({ op, post_ids: ids }),
      });
      updated.forEach(applyPost);
      void refreshCampaign();
      void refreshReadiness();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed");
    } finally {
      ids.forEach(stopActing);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  // Approve, but if the user's platform token needs re-consent, send them
  // through the authorize flow carrying this post so the callback resumes the
  // approve. The error detail names the platform (linkedin or x).
  const approvePost = async (postId: string) => {
    setError(null);
    startActing(postId);
    try {
      const updated = await apiFetch<Post>(`/v1/posts/${postId}/approve`, {
        method: "POST",
      });
      applyPost(updated);
      void refreshCampaign();
      void refreshReadiness();
    } catch (err) {
      const detail =
        err instanceof ApiError
          ? (err.detail as { code?: string; platform?: string } | undefined)
          : undefined;
      if (err instanceof ApiError && detail?.code === "linkedin_reconnect_required") {
        const platform = detail.platform ?? "linkedin";
        try {
          const { authorize_url } = await apiFetch<{ authorize_url: string }>(
            `/v1/connections/${platform}/authorize?resume_post_id=${postId}`,
          );
          window.location.href = authorize_url;
          return;
        } catch {
          setError(
            `Could not start ${platformLabel(platform)} reconnect. Please try again.`,
          );
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
            <div className="flex items-center gap-2 text-muted-ink">
              <Loader2 className="h-5 w-5 animate-spin" />
              <p className="text-sm">Loading campaign...</p>
            </div>
          )}
        </div>
      </AppShell>
    );
  }

  // "Done" counts every settled item, not just API-published ones: acknowledged
  // assisted-manual comments/likes and intentionally skipped items are resolved
  // too. Failed items are excluded since they still need a retry or a skip.
  const done =
    (campaign.counts.published ?? 0) +
    (campaign.counts.acknowledged ?? 0) +
    (campaign.counts.skipped ?? 0);
  const total = campaign.post_count;

  // Show each authored post before the rows that depend on it (its self-comment,
  // and distribute interactions targeting it) so the plan reads top-down and a
  // follow-up never appears above the post it belongs to.
  const indexById = new Map(posts.map((p, i) => [p.id, i]));
  const orderKey = (p: Post): number => {
    const own = indexById.get(p.id) ?? 0;
    const parentIdx =
      p.target_post_id !== null ? indexById.get(p.target_post_id) : undefined;
    return parentIdx !== undefined
      ? parentIdx * 1000 + 1 + own / 1e6
      : own * 1000;
  };
  const orderedPosts = [...posts].sort((a, b) => orderKey(a) - orderKey(b));

  // Merge the assisted like+comment pair for one actor+target into a single
  // card so the person opens LinkedIn once, likes and pastes the comment, and
  // settles both together. Only assisted rows (Community Management API off) are
  // merged, and only when both rows share the same status, so a transient
  // divergence during publishing falls back to rendering each row on its own.
  const isAssistedEngagement = (p: Post) =>
    p.assisted && (p.action === "like" || p.action === "comment");
  const groupKeyOf = (p: Post) =>
    `${p.user_id}|${p.target_post_id ?? p.target_external_id ?? "seed"}|${p.status}`;
  const groups = new Map<string, Post[]>();
  for (const p of orderedPosts) {
    if (!isAssistedEngagement(p)) continue;
    const key = groupKeyOf(p);
    const members = groups.get(key);
    if (members) members.push(p);
    else groups.set(key, [p]);
  }

  const meId = user?.id;
  const isAdmin = user?.role === "admin";
  const isCreator = campaign.created_by === meId;
  const launched = !!campaign.launched_at;

  const renderSingle = (post: Post) => (
    <PostCard
      key={post.id}
      post={post}
      roster={roster}
      meId={meId}
      isAdmin={isAdmin}
      isCreator={isCreator}
      launched={launched}
      busy={actingIds.has(post.id)}
      onEdit={(body) =>
        runPost(post.id, () =>
          apiFetch<Post>(`/v1/posts/${post.id}`, {
            method: "PATCH",
            body: JSON.stringify({ body }),
          }),
        )
      }
      onApprove={() => approvePost(post.id)}
      onAck={() =>
        runPost(post.id, () =>
          apiFetch<Post>(`/v1/posts/${post.id}/ack`, { method: "POST" }),
        )
      }
      onSkip={() =>
        runPost(post.id, () =>
          apiFetch<Post>(`/v1/posts/${post.id}/skip`, { method: "POST" }),
        )
      }
    />
  );

  const renderGroup = (comment: Post, like: Post) => {
    const ids = [comment.id, like.id];
    return (
      <CombinedEngagementCard
        key={`grp-${comment.id}-${like.id}`}
        comment={comment}
        like={like}
        roster={roster}
        meId={meId}
        isAdmin={isAdmin}
        isCreator={isCreator}
        launched={launched}
        busy={ids.some((i) => actingIds.has(i))}
        onEditComment={(body) =>
          runPost(comment.id, () =>
            apiFetch<Post>(`/v1/posts/${comment.id}`, {
              method: "PATCH",
              body: JSON.stringify({ body }),
            }),
          )
        }
        onApprove={() => runBatch(ids, "approve")}
        onAck={() => runBatch(ids, "ack")}
        onSkip={() => runBatch(ids, "skip")}
      />
    );
  };

  // Emit combined cards at the position of their first row; everything else on
  // its own. A row already folded into a combined card is not re-rendered.
  const renderItems: ReactNode[] = [];
  const consumed = new Set<string>();
  for (const post of orderedPosts) {
    if (consumed.has(post.id)) continue;
    if (isAssistedEngagement(post)) {
      const members = groups.get(groupKeyOf(post)) ?? [];
      const comment = members.find((m) => m.action === "comment");
      const like = members.find((m) => m.action === "like");
      if (members.length === 2 && comment && like) {
        consumed.add(comment.id);
        consumed.add(like.id);
        renderItems.push(renderGroup(comment, like));
        continue;
      }
    }
    renderItems.push(renderSingle(post));
  }

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
            {campaign.scheduled_at && !campaign.launched_at && (
              <span className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-clay/30 bg-clay/10 px-2.5 py-0.5 text-xs font-medium text-clay">
                <CalendarClock className="h-3.5 w-3.5" />
                Scheduled for{" "}
                {new Date(campaign.scheduled_at).toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                  // Show the time in the campaign's own timezone with its
                  // abbreviation, so it reads the same wherever it is opened.
                  ...(campaign.schedule_timezone
                    ? {
                        timeZone: campaign.schedule_timezone,
                        timeZoneName: "short",
                      }
                    : {}),
                })}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex rounded-full border border-border bg-paper px-2.5 py-0.5 text-xs font-medium text-muted-ink">
              {platformLabel(campaign.platform)}
            </span>
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
            {campaign.status === "review" && !campaign.launched_at && (
              <button
                onClick={() =>
                  run(() =>
                    apiFetch(`/v1/campaigns/${id}/launch`, { method: "POST" }),
                  )
                }
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-md bg-clay px-4 py-2 text-sm font-medium text-paper hover:bg-clay-press disabled:opacity-50"
              >
                {busy ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Launching...
                  </>
                ) : (
                  <>
                    <Rocket className="h-4 w-4" />
                    Launch
                  </>
                )}
              </button>
            )}
            {/* Launched, but the worker has not flipped the status to publishing
                yet. Show progress instead of a second Launch button (which would
                409 with "must be in review to launch"). */}
            {campaign.status === "review" && campaign.launched_at && (
              <span className="inline-flex items-center gap-2 rounded-md bg-clay/10 px-4 py-2 text-sm font-medium text-clay">
                <Loader2 className="h-4 w-4 animate-spin" />
                Launching...
              </span>
            )}
            {canManage && campaign.status === "publishing" && (
              <button
                onClick={() =>
                  run(() =>
                    apiFetch(`/v1/campaigns/${id}/pause`, { method: "POST" }),
                  )
                }
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm font-medium text-ink hover:bg-sand disabled:opacity-50"
              >
                <Pause className="h-4 w-4" />
                Pause
              </button>
            )}
            {canManage && campaign.status === "paused" && (
              <button
                onClick={() =>
                  run(() =>
                    apiFetch(`/v1/campaigns/${id}/resume`, { method: "POST" }),
                  )
                }
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-md bg-clay px-4 py-2 text-sm font-medium text-paper hover:bg-clay-press disabled:opacity-50"
              >
                <Play className="h-4 w-4" />
                Resume
              </button>
            )}
            {canReset && (
              <button
                onClick={() => setResetOpen(true)}
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm font-medium text-ink hover:bg-sand disabled:opacity-50"
                title="Rewind this campaign to review so it can be launched again"
              >
                <RotateCcw className="h-4 w-4" />
                Reset
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
              <span>Done</span>
              <span className="tabular">
                {done} of {total}
              </span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-sand">
              <div
                className="h-full bg-ok transition-all"
                style={{ width: total ? `${(done / total) * 100}%` : "0%" }}
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
            {campaign.status === "generating" && (
              <div className="mt-3">
                <Hint>
                  <span className="inline-flex items-center gap-2">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Generating drafts. This page updates automatically.
                  </span>
                </Hint>
              </div>
            )}
            {posts.length > 0 && !campaign.launched_at && (
              <div className="mt-3">
                <Hint>
                  Approvals unlock after you launch. Until then you can edit the
                  plan. Launch notifies each person to approve, and approving is
                  what publishes their item.
                </Hint>
              </div>
            )}
            {readiness?.needs_reconnect && (
              <div className="mt-3 flex items-start gap-3 rounded-lg border border-pending/30 bg-pending/5 p-4">
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-pending" />
                <div className="flex-1">
                  <p className="text-sm font-medium text-ink">
                    {readiness.connected
                      ? `Reconnect ${platformLabel(readiness.platform)} before approving`
                      : `Connect ${platformLabel(readiness.platform)} before approving`}
                  </p>
                  <p className="mt-0.5 text-sm text-muted-ink">
                    {readiness.connected
                      ? `Your ${platformLabel(readiness.platform)} access is expired or expiring soon, so approvals here would fail. Reconnect now to publish smoothly.`
                      : `You have posts here that publish under your ${platformLabel(readiness.platform)}. Connect your account so you can approve them.`}
                  </p>
                </div>
                <button
                  onClick={reconnect}
                  disabled={reconnecting}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-clay px-3 py-1.5 text-xs font-medium text-paper hover:bg-clay-press disabled:opacity-50"
                >
                  {reconnecting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Link2 className="h-3.5 w-3.5" />
                  )}
                  {readiness.connected ? "Reconnect" : "Connect"}
                </button>
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
              {renderItems}
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
      {resetOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
          onClick={() => !busy && setResetOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-lg border border-border bg-surface p-5 shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <span className="mt-0.5 rounded-full bg-clay/10 p-1.5 text-clay">
                <RotateCcw className="h-4 w-4" />
              </span>
              <div>
                <h2 className="font-serif text-lg text-ink">Reset campaign</h2>
                <p className="mt-1 text-sm text-muted-ink">
                  This rewinds{" "}
                  <span className="font-medium text-ink">{campaign.title}</span>{" "}
                  back to review. Every post returns to pending and its publish
                  results (links, timestamps) are cleared, so you can launch it
                  again from the start. The plan and its text are kept. Posts
                  that already went live on {platformLabel(campaign.platform)}{" "}
                  are not deleted there.
                </p>
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setResetOpen(false)}
                disabled={busy}
                className="rounded-md border border-border px-4 py-2 text-sm text-muted-ink hover:bg-sand disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setResetOpen(false);
                  void run(() =>
                    apiFetch(`/v1/campaigns/${id}/reset`, { method: "POST" }),
                  );
                }}
                disabled={busy}
                className="rounded-md bg-clay px-4 py-2 text-sm font-medium text-paper hover:bg-clay-press disabled:opacity-50"
              >
                Reset campaign
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}

const CAMPAIGN_STATUS_STYLES: Record<string, string> = {
  draft: "bg-sand text-muted-ink",
  generating: "bg-pending/15 text-pending",
  review: "bg-clay/15 text-clay",
  publishing: "bg-ok/15 text-ok",
  paused: "bg-pending/15 text-pending",
  completed: "bg-ok text-paper",
  failed: "bg-fail/10 text-fail",
};

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mb-4 rounded-lg border border-border bg-surface p-4">
      <h2 className="mb-2 text-sm font-medium text-ink">{title}</h2>
      {children}
    </div>
  );
}
