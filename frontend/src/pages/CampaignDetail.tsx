import { type ReactNode, useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Check,
  Rocket,
  Sparkles,
  SkipForward,
  Save,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { AppShell } from "@/components/AppShell";
import { ApiError, apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Campaign {
  id: string;
  title: string;
  type: string;
  status: string;
  seed_url: string | null;
  seed_urn: string | null;
  seed_content: string | null;
  tone: string | null;
  length: string | null;
  language: string;
  created_by: string | null;
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

interface RosterUser {
  id: string;
  name: string | null;
  email: string;
  linkedin_status: string | null;
}

interface AssignmentDraft {
  user_id: string;
  action: string;
  target_post_index?: number;
  body?: string;
}

const ACTIONS = ["like", "comment", "repost_comment"] as const;

export function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const isEditor = user?.role === "editor" || user?.role === "admin";

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [roster, setRoster] = useState<RosterUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
  const canPlan = campaign.status === "draft" || campaign.status === "review";

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
            <p className="mt-1 text-sm capitalize text-muted-ink">
              {campaign.type} &middot; {campaign.status}
            </p>
          </div>
          {campaign.status === "review" && (
            <button
              onClick={() => run(() => apiFetch(`/v1/campaigns/${id}/launch`, { method: "POST" }))}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-md bg-clay px-4 py-2 text-sm font-medium text-paper hover:bg-clay-press disabled:opacity-50"
            >
              <Rocket className="h-4 w-4" />
              Launch
            </button>
          )}
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

            {canPlan && (
              <PlanBuilder
                campaign={campaign}
                roster={roster}
                isEditor={isEditor}
                busy={busy}
                onPlan={(assignments, generate) =>
                  run(() =>
                    apiFetch(
                      `/v1/campaigns/${id}/${generate ? "generate" : "plan"}`,
                      {
                        method: "POST",
                        body: JSON.stringify({ assignments }),
                      },
                    ),
                  )
                }
              />
            )}
          </div>

          <div>
            <h2 className="text-sm font-medium text-ink">
              Posts &amp; interactions
            </h2>
            <div className="mt-3 space-y-3">
              {posts.length === 0 && (
                <p className="text-sm text-muted-ink">
                  No posts yet. Build a plan to assign participants.
                </p>
              )}
              {posts.map((post) => (
                <PostCard
                  key={post.id}
                  post={post}
                  roster={roster}
                  meId={user?.id}
                  isAdmin={user?.role === "admin"}
                  busy={busy}
                  onEdit={(body) =>
                    run(() =>
                      apiFetch(`/v1/posts/${post.id}`, {
                        method: "PATCH",
                        body: JSON.stringify({ body }),
                      }),
                    )
                  }
                  onApprove={() =>
                    run(() =>
                      apiFetch(`/v1/posts/${post.id}/approve`, { method: "POST" }),
                    )
                  }
                  onSkip={() =>
                    run(() =>
                      apiFetch(`/v1/posts/${post.id}/skip`, { method: "POST" }),
                    )
                  }
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

function PlanBuilder({
  campaign,
  roster,
  isEditor,
  busy,
  onPlan,
}: {
  campaign: Campaign;
  roster: RosterUser[];
  isEditor: boolean;
  busy: boolean;
  onPlan: (assignments: AssignmentDraft[], generate: boolean) => void;
}) {
  const [rows, setRows] = useState<AssignmentDraft[]>([]);

  const addRow = (action: string) =>
    setRows((r) => [...r, { user_id: roster[0]?.id ?? "", action }]);

  const update = (i: number, patch: Partial<AssignmentDraft>) =>
    setRows((r) => r.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));

  const remove = (i: number) =>
    setRows((r) => r.filter((_, idx) => idx !== i));

  const posterRows = rows.filter((r) => r.action === "post");
  const canGenerate =
    campaign.type === "amplify" ? true : isEditor;

  return (
    <Panel title="Plan">
      <div className="space-y-2">
        {rows.map((row, i) => (
          <div
            key={i}
            className="rounded-md border border-border bg-paper p-2 text-sm"
          >
            <div className="flex items-center gap-2">
              <select
                value={row.user_id}
                onChange={(e) => update(i, { user_id: e.target.value })}
                className="input flex-1"
              >
                {roster.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name ?? u.email}
                  </option>
                ))}
              </select>
              <span className="rounded bg-sand px-2 py-1 text-xs capitalize text-muted-ink">
                {row.action.replace("_", " ")}
              </span>
              <button
                onClick={() => remove(i)}
                className="text-xs text-fail hover:underline"
              >
                Remove
              </button>
            </div>
            {campaign.type === "distribute" && row.action !== "post" && (
              <select
                value={row.target_post_index ?? 0}
                onChange={(e) =>
                  update(i, { target_post_index: Number(e.target.value) })
                }
                className="input mt-2"
              >
                {posterRows.map((_, idx) => (
                  <option key={idx} value={idx}>
                    Variation #{idx + 1}
                  </option>
                ))}
              </select>
            )}
            {(row.action === "comment" || row.action === "repost_comment") && (
              <textarea
                value={row.body ?? ""}
                onChange={(e) => update(i, { body: e.target.value })}
                rows={2}
                placeholder="Optional text (or leave blank and Generate)."
                className="input mt-2"
              />
            )}
          </div>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {campaign.type === "distribute" && isEditor && (
          <SmallButton onClick={() => addRow("post")} label="+ Variation" />
        )}
        {ACTIONS.map((a) => (
          <SmallButton
            key={a}
            onClick={() => addRow(a)}
            label={`+ ${a.replace("_", " ")}`}
          />
        ))}
      </div>

      <div className="mt-4 flex gap-2">
        <button
          onClick={() => onPlan(rows, false)}
          disabled={busy || rows.length === 0}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-border px-3 py-2 text-sm text-ink hover:bg-sand disabled:opacity-50"
        >
          <Save className="h-4 w-4" />
          Save plan
        </button>
        <button
          onClick={() => onPlan(rows, true)}
          disabled={busy || rows.length === 0 || !canGenerate}
          title={!canGenerate ? "Generation requires the editor role" : undefined}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-ink px-3 py-2 text-sm font-medium text-paper hover:opacity-90 disabled:opacity-50"
        >
          <Sparkles className="h-4 w-4" />
          Generate
        </button>
      </div>
    </Panel>
  );
}

function PostCard({
  post,
  roster,
  meId,
  isAdmin,
  busy,
  onEdit,
  onApprove,
  onSkip,
}: {
  post: Post;
  roster: RosterUser[];
  meId?: string;
  isAdmin: boolean;
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
            {post.action.replace("_", " ")}
          </span>
          <span className="text-sm text-ink">
            {owner?.name ?? owner?.email ?? "Unknown"}
          </span>
        </div>
        <span className="text-xs capitalize text-muted-ink">{post.status}</span>
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
        </div>
      )}
    </div>
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

function SmallButton({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-md border border-border px-2.5 py-1 text-xs text-muted-ink hover:bg-sand",
        "capitalize disabled:opacity-50",
      )}
    >
      {label}
    </button>
  );
}
