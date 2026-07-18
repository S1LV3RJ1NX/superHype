// The per-item cards on the campaign detail page: a single post/interaction
// card, the merged assisted like+comment card, and their shared badge and
// action-label helpers. All actions are callbacks; data fetching stays in the
// page.
import { useEffect, useState } from "react";
import {
  Check,
  Copy,
  ExternalLink,
  Loader2,
  RotateCcw,
  SkipForward,
} from "lucide-react";

import { type RosterUser, SmallButton } from "@/components/PlanBuilder";

export interface Post {
  id: string;
  user_id: string;
  platform: string;
  action: string;
  body: string | null;
  status: string;
  target_post_id: string | null;
  target_external_id: string | null;
  engagement_url: string | null;
  acknowledged_at: string | null;
  error: string | null;
  // True when the action is a guided human step (comment/like/self_comment while
  // the Community Management API is off), so the client can merge the assisted
  // like+comment pair into one card.
  assisted: boolean;
}

export function PostCard({
  post,
  roster,
  meId,
  isAdmin,
  isCreator,
  launched,
  busy,
  onEdit,
  onApprove,
  onAck,
  onSkip,
}: {
  post: Post;
  roster: RosterUser[];
  meId?: string;
  isAdmin: boolean;
  isCreator: boolean;
  launched: boolean;
  busy: boolean;
  onEdit: (body: string) => void;
  onApprove: () => void;
  onAck: () => void;
  onSkip: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(post.body ?? "");
  // Which action is mid-flight, so only the clicked button spins (busy is shared
  // across this card's buttons). Cleared once the action settles.
  const [acting, setActing] = useState<string | null>(null);
  useEffect(() => {
    if (!busy) setActing(null);
  }, [busy]);
  const owner = roster.find((u) => u.id === post.user_id);
  const isOwner = post.user_id === meId;
  const canAct = isAdmin || isOwner;
  // The campaign creator can refine anyone's text before launch, but approving
  // and publishing stay with the owner or an admin.
  const canEditText = canAct || isCreator;
  const pending = post.status === "pending" || post.status === "scheduled";
  // Assisted-manual engagement: a comment or like the person performs by hand.
  const actionRequired = post.status === "action_required";

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="rounded bg-sand px-2 py-0.5 text-xs font-medium capitalize text-muted-ink">
            {actionLabel(post.action, post.platform)}
          </span>
          <span className="text-sm text-ink">
            {owner?.name ?? owner?.email ?? "Unknown"}
          </span>
        </div>
        <StatusBadge status={post.status} />
      </div>

      {post.action !== "like" && post.action !== "bookmark" && (
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

      {/* "approved" is a transient state: the worker is either publishing this
          item or about to raise the assisted comment/like ask. Show a spinner so
          the person does not read the brief "Approved" badge as fully done. */}
      {post.status === "approved" && (
        <div className="mt-3 flex items-center gap-2 rounded-md border border-ok/20 bg-ok/5 px-3 py-2 text-xs text-muted-ink">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-ok" />
          Processing your approval...
        </div>
      )}

      {actionRequired && (
        <EngagementAsk
          post={post}
          isOwner={isOwner}
          busy={busy}
          onAck={onAck}
          onSkip={canAct ? onSkip : undefined}
        />
      )}

      {post.error && <p className="mt-2 text-xs text-fail">{post.error}</p>}

      {pending && (canEditText || (canAct && launched)) && (
        <div className="mt-3 flex flex-wrap gap-2">
          {canEditText &&
            post.action !== "like" &&
            post.action !== "bookmark" &&
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
          {canAct && launched && (
            <>
              <button
                onClick={() => {
                  setActing("approve");
                  onApprove();
                }}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-md bg-ok/10 px-3 py-1.5 text-xs font-medium text-ok hover:bg-ok/20 disabled:opacity-50"
              >
                {busy && acting === "approve" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="h-3.5 w-3.5" />
                )}
                Approve
              </button>
              <button
                onClick={() => {
                  setActing("skip");
                  onSkip();
                }}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-ink hover:bg-sand disabled:opacity-50"
              >
                {busy && acting === "skip" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <SkipForward className="h-3.5 w-3.5" />
                )}
                Skip
              </button>
            </>
          )}
        </div>
      )}

      {/* A failed post can be retried by its owner (e.g. after reconnecting a
          stale LinkedIn token); owner or admin can skip it to settle it. */}
      {canAct && post.status === "failed" && (
        <div className="mt-3 flex flex-wrap gap-2">
          {isOwner && (
            <button
              onClick={() => {
                setActing("approve");
                onApprove();
              }}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-md bg-clay px-3 py-1.5 text-xs font-medium text-paper hover:bg-clay-press disabled:opacity-50"
            >
              {busy && acting === "approve" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RotateCcw className="h-3.5 w-3.5" />
              )}
              Retry
            </button>
          )}
          <button
            onClick={() => {
              setActing("skip");
              onSkip();
            }}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-ink hover:bg-sand disabled:opacity-50"
          >
            {busy && acting === "skip" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <SkipForward className="h-3.5 w-3.5" />
            )}
            Skip
          </button>
        </div>
      )}
    </div>
  );
}

// The assisted like and comment on one target, merged into a single card: open
// the post once, like it, paste the comment, and settle both rows together. The
// two rows share a status (the parent only groups matching-status rows), so this
// reads the comment row for text/state and acts on both via the batch endpoint.
export function CombinedEngagementCard({
  comment,
  like,
  roster,
  meId,
  isAdmin,
  isCreator,
  launched,
  busy,
  onEditComment,
  onApprove,
  onAck,
  onSkip,
}: {
  comment: Post;
  like: Post;
  roster: RosterUser[];
  meId?: string;
  isAdmin: boolean;
  isCreator: boolean;
  launched: boolean;
  busy: boolean;
  onEditComment: (body: string) => void;
  onApprove: () => void;
  onAck: () => void;
  onSkip: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(comment.body ?? "");
  const [acting, setActing] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!busy) setActing(null);
  }, [busy]);

  const status = comment.status;
  const owner = roster.find((u) => u.id === comment.user_id);
  const isOwner = comment.user_id === meId;
  const canAct = isAdmin || isOwner;
  // Creator can refine the comment text before launch; approve stays owner/admin.
  const canEditText = canAct || isCreator;
  const pending = status === "pending" || status === "scheduled";
  const actionRequired = status === "action_required";
  const engagementUrl = comment.engagement_url ?? like.engagement_url;

  const copyText = async () => {
    if (!comment.body) return;
    try {
      await navigator.clipboard.writeText(comment.body);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard can be blocked; the text is still visible above to copy by hand.
    }
  };

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="rounded bg-sand px-2 py-0.5 text-xs font-medium text-muted-ink">
            like + comment
          </span>
          <span className="text-sm text-ink">
            {owner?.name ?? owner?.email ?? "Unknown"}
          </span>
        </div>
        <StatusBadge status={status} />
      </div>

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
            {comment.body || <span className="text-muted-ink">No text yet.</span>}
          </p>
        )}
      </div>

      {status === "approved" && (
        <div className="mt-3 flex items-center gap-2 rounded-md border border-ok/20 bg-ok/5 px-3 py-2 text-xs text-muted-ink">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-ok" />
          Processing your approval...
        </div>
      )}

      {actionRequired && (
        <div className="mt-3 rounded-md border border-pending/30 bg-pending/5 p-3">
          <p className="text-xs text-muted-ink">
            Open the post, like it and add this comment, then mark both done.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {engagementUrl && (
              <a
                href={engagementUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md bg-clay px-3 py-1.5 text-xs font-medium text-paper hover:bg-clay-press"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Open on LinkedIn
              </a>
            )}
            {comment.body && (
              <button
                onClick={copyText}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-ink hover:bg-sand"
              >
                <Copy className="h-3.5 w-3.5" />
                {copied ? "Copied" : "Copy comment"}
              </button>
            )}
            {isOwner && (
              <button
                onClick={() => {
                  setActing("ack");
                  onAck();
                }}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-md bg-ok/10 px-3 py-1.5 text-xs font-medium text-ok hover:bg-ok/20 disabled:opacity-50"
              >
                {busy && acting === "ack" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="h-3.5 w-3.5" />
                )}
                Mark done
              </button>
            )}
            {canAct && (
              <button
                onClick={() => {
                  setActing("skip");
                  onSkip();
                }}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-ink hover:bg-sand disabled:opacity-50"
              >
                {busy && acting === "skip" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <SkipForward className="h-3.5 w-3.5" />
                )}
                Skip
              </button>
            )}
          </div>
        </div>
      )}

      {(comment.error || like.error) && (
        <p className="mt-2 text-xs text-fail">{comment.error || like.error}</p>
      )}

      {pending && (canEditText || (canAct && launched)) && (
        <div className="mt-3 flex flex-wrap gap-2">
          {canEditText &&
            (editing ? (
              <>
                <SmallButton
                  label="Save"
                  onClick={() => {
                    onEditComment(draft);
                    setEditing(false);
                  }}
                  disabled={busy}
                />
                <SmallButton label="Cancel" onClick={() => setEditing(false)} />
              </>
            ) : (
              <SmallButton label="Edit" onClick={() => setEditing(true)} />
            ))}
          {canAct && launched && (
            <>
              <button
                onClick={() => {
                  setActing("approve");
                  onApprove();
                }}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-md bg-ok/10 px-3 py-1.5 text-xs font-medium text-ok hover:bg-ok/20 disabled:opacity-50"
              >
                {busy && acting === "approve" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="h-3.5 w-3.5" />
                )}
                Approve
              </button>
              <button
                onClick={() => {
                  setActing("skip");
                  onSkip();
                }}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-ink hover:bg-sand disabled:opacity-50"
              >
                {busy && acting === "skip" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <SkipForward className="h-3.5 w-3.5" />
                )}
                Skip
              </button>
            </>
          )}
        </div>
      )}

      {canAct && status === "failed" && (
        <div className="mt-3 flex flex-wrap gap-2">
          {isOwner && (
            <button
              onClick={() => {
                setActing("approve");
                onApprove();
              }}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-md bg-clay px-3 py-1.5 text-xs font-medium text-paper hover:bg-clay-press disabled:opacity-50"
            >
              {busy && acting === "approve" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RotateCcw className="h-3.5 w-3.5" />
              )}
              Retry
            </button>
          )}
          <button
            onClick={() => {
              setActing("skip");
              onSkip();
            }}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-ink hover:bg-sand disabled:opacity-50"
          >
            {busy && acting === "skip" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <SkipForward className="h-3.5 w-3.5" />
            )}
            Skip
          </button>
        </div>
      )}
    </div>
  );
}

// The guided human step for a comment, like, or X reply/quote: open the post on
// LinkedIn or X, paste the suggested text (comment/quote only), act, then mark it
// done. Only the owner can mark it done since only they can perform the action.
function EngagementAsk({
  post,
  isOwner,
  busy,
  onAck,
  onSkip,
}: {
  post: Post;
  isOwner: boolean;
  busy: boolean;
  onAck: () => void;
  onSkip?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  useEffect(() => {
    if (!busy) setActing(null);
  }, [busy]);
  const isSelfComment = post.action === "self_comment";
  const isQuote = post.action === "repost_comment";
  const isX = post.platform === "x";
  const hasText = post.action === "comment" || isSelfComment || isQuote;

  const copyText = async () => {
    if (!post.body) return;
    try {
      await navigator.clipboard.writeText(post.body);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard can be blocked; the text is still visible above to copy by hand.
    }
  };

  return (
    <div className="mt-3 rounded-md border border-pending/30 bg-pending/5 p-3">
      <p className="text-xs text-muted-ink">
        {isSelfComment
          ? "Open your post, paste your self-comment, then mark it done."
          : isQuote
            ? "Open the post, quote it with your comment, then mark it done."
            : isX && hasText
              ? "Open the post, paste your reply, then mark it done."
              : hasText
                ? "Open the post, paste your comment, then mark it done."
                : "Open the post, like it, then mark it done."}
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {post.engagement_url && (
          <a
            href={post.engagement_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md bg-clay px-3 py-1.5 text-xs font-medium text-paper hover:bg-clay-press"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            {isSelfComment
              ? "Open your post"
              : isX
                ? "Open on X"
                : "Open on LinkedIn"}
          </a>
        )}
        {hasText && post.body && (
          <button
            onClick={copyText}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-ink hover:bg-sand"
          >
            <Copy className="h-3.5 w-3.5" />
            {copied ? "Copied" : "Copy text"}
          </button>
        )}
        {isOwner && (
          <button
            onClick={() => {
              setActing("ack");
              onAck();
            }}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md bg-ok/10 px-3 py-1.5 text-xs font-medium text-ok hover:bg-ok/20 disabled:opacity-50"
          >
            {busy && acting === "ack" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Check className="h-3.5 w-3.5" />
            )}
            Mark done
          </button>
        )}
        {onSkip && (
          <button
            onClick={() => {
              setActing("skip");
              onSkip();
            }}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-ink hover:bg-sand disabled:opacity-50"
          >
            {busy && acting === "skip" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <SkipForward className="h-3.5 w-3.5" />
            )}
            Skip
          </button>
        )}
      </div>
    </div>
  );
}

// Each platform's own vocabulary: a comment is a reply on X, a repost is a
// quote post, and an X like carries a paired bookmark row.
const ACTION_LABELS_BY_PLATFORM: Record<string, Record<string, string>> = {
  linkedin: {
    like: "like",
    comment: "comment",
    repost_comment: "repost thought",
    post: "post",
    self_comment: "self comment",
  },
  x: {
    like: "like",
    bookmark: "bookmark",
    comment: "reply",
    repost_comment: "quote post",
    post: "post",
    self_comment: "self reply",
  },
};

function actionLabel(action: string, platform: string): string {
  const labels =
    ACTION_LABELS_BY_PLATFORM[platform] ?? ACTION_LABELS_BY_PLATFORM.linkedin;
  return labels[action] ?? action.replace("_", " ");
}

const STATUS_BADGE: Record<string, string> = {
  pending: "bg-pending/15 text-pending",
  scheduled: "bg-pending/15 text-pending",
  approved: "bg-ok/15 text-ok",
  action_required: "bg-clay/15 text-clay",
  acknowledged: "bg-ok text-paper",
  published: "bg-ok text-paper",
  failed: "bg-fail/15 text-fail",
  skipped: "bg-sand text-muted-ink",
};

// Friendlier wording for the assisted-manual states than the raw status.
const STATUS_LABEL: Record<string, string> = {
  action_required: "action needed",
  acknowledged: "done",
};

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_BADGE[status] ?? "bg-sand text-muted-ink";
  const label = STATUS_LABEL[status] ?? status.replace("_", " ");
  return (
    <span
      className={`rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${style}`}
    >
      {label}
    </span>
  );
}
