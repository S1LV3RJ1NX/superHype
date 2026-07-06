import { useCallback, useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { AppShell } from "@/components/AppShell";
import {
  type CampaignFieldsValue,
  emptyCampaignFields,
  isoToDateTimeLocal,
} from "@/components/CampaignFields";
import { CampaignWizard } from "@/components/CampaignWizard";
import { type LockedPost, type RosterUser } from "@/components/PlanBuilder";
import { apiFetch } from "@/lib/api";
import { fetchAllRoster } from "@/lib/roster";

const EDITABLE_STATUSES = ["draft", "review"];

interface Campaign {
  id: string;
  title: string;
  type: string;
  status: string;
  seed_url: string | null;
  seed_content: string | null;
  tone: string | null;
  length: string | null;
  image_url: string | null;
  image_asset_id: string | null;
  media: { asset_id: string; alt: string | null }[];
  self_comment: string | null;
  custom_rules: string | null;
  apply_global_rules: boolean;
  scheduled_at: string | null;
  created_by: string | null;
}

interface Post {
  id: string;
  user_id: string;
  action: string;
  body: string | null;
  status: string;
  target_post_id: string | null;
}

function fieldsFromCampaign(c: Campaign): CampaignFieldsValue {
  return {
    type: c.type === "distribute" ? "distribute" : "amplify",
    title: c.title,
    seedUrl: c.seed_url ?? "",
    seedContent: c.seed_content ?? "",
    tones: c.tone
      ? c.tone
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
      : [],
    length: c.length ?? "",
    imageUrl: c.image_url ?? "",
    // Prefer the media pool; fall back to a one-item list from the legacy single
    // asset for campaigns created before the pool existed.
    mediaAssetIds: c.media?.length
      ? c.media.map((m) => m.asset_id)
      : c.image_asset_id
        ? [c.image_asset_id]
        : [],
    selfComment: c.self_comment ?? "",
    campaignRules: c.custom_rules ?? "",
    applyGlobalRules: c.apply_global_rules ?? true,
    scheduledAt: isoToDateTimeLocal(c.scheduled_at),
  };
}

function participantIdsFromPosts(posts: Post[]): string[] {
  // Distinct users who still have pending (re-plannable) posts.
  const ids = new Set<string>();
  for (const p of posts) {
    if (p.status === "pending") ids.add(p.user_id);
  }
  return Array.from(ids);
}

const AMPLIFY_ACTION_KEYS = ["like", "comment", "repost_comment"];

// Seed the amplify action matrix from the current pending posts so an edit opens
// with each person's existing action selection, not a reset to all three.
function actionsByParticipantFromPosts(
  posts: Post[],
): Record<string, string[]> {
  const map: Record<string, Set<string>> = {};
  for (const p of posts) {
    if (p.status !== "pending") continue;
    if (!AMPLIFY_ACTION_KEYS.includes(p.action)) continue;
    (map[p.user_id] ??= new Set()).add(p.action);
  }
  const out: Record<string, string[]> = {};
  for (const [uid, set] of Object.entries(map)) {
    out[uid] = AMPLIFY_ACTION_KEYS.filter((k) => set.has(k));
  }
  return out;
}

export function CampaignEditor() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const isEditor = user?.role === "editor" || user?.role === "admin";
  const mode: "create" | "edit" = id ? "edit" : "create";

  const [loading, setLoading] = useState(mode === "edit");
  const [error, setError] = useState<string | null>(null);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [roster, setRoster] = useState<RosterUser[]>([]);
  const [initialFields, setInitialFields] = useState<CampaignFieldsValue>(
    emptyCampaignFields(),
  );
  const [initialParticipantIds, setInitialParticipantIds] = useState<string[]>(
    [],
  );
  const [initialActionsByParticipant, setInitialActionsByParticipant] =
    useState<Record<string, string[]>>({});
  const [lockedPosts, setLockedPosts] = useState<LockedPost[]>([]);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const [c, p, r] = await Promise.all([
        apiFetch<Campaign>(`/v1/campaigns/${id}`),
        apiFetch<{ items: Post[] }>(`/v1/campaigns/${id}/posts`),
        fetchAllRoster(),
      ]);
      setCampaign(c);
      setRoster(r);
      setInitialFields(fieldsFromCampaign(c));
      setInitialParticipantIds(participantIdsFromPosts(p.items));
      setInitialActionsByParticipant(actionsByParticipantFromPosts(p.items));
      setLockedPosts(
        p.items
          .filter((post) => post.status !== "pending")
          .map((post) => ({
            id: post.id,
            user_id: post.user_id,
            action: post.action,
            status: post.status,
          })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load campaign");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    if (mode === "edit") load();
  }, [mode, load]);

  const backTo = id ? `/app/campaigns/${id}` : "/app/campaigns";

  const editable =
    !!campaign &&
    EDITABLE_STATUSES.includes(campaign.status) &&
    (user?.role === "admin" || campaign.created_by === user?.id);

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl">
        <Link
          to={backTo}
          className="inline-flex items-center gap-1.5 text-sm text-muted-ink hover:text-ink"
        >
          <ArrowLeft className="h-4 w-4" />
          {mode === "edit" ? "Back to campaign" : "Campaigns"}
        </Link>

        <h1 className="mt-2 font-serif text-2xl text-ink">
          {mode === "edit" ? "Edit campaign" : "New campaign"}
        </h1>

        {mode === "edit" && loading && (
          <p className="mt-6 text-sm text-muted-ink">Loading...</p>
        )}

        {error && (
          <div className="mt-4 rounded-md border border-fail/20 bg-fail/5 px-4 py-2 text-sm text-fail">
            {error}
          </div>
        )}

        {mode === "edit" && !loading && campaign && !editable && (
          <div className="mt-6 rounded-lg border border-border bg-surface p-5">
            <p className="text-sm text-ink">
              This campaign can no longer be edited.
            </p>
            <Link
              to={backTo}
              className="mt-3 inline-flex items-center gap-1.5 text-sm text-clay hover:underline"
            >
              View campaign
            </Link>
          </div>
        )}

        {mode === "create" && (
          <div className="mt-6">
            <CampaignWizard
              mode="create"
              isEditor={isEditor}
              onDone={(cid) => navigate(`/app/campaigns/${cid}`)}
              onCancel={() => navigate("/app/campaigns")}
            />
          </div>
        )}

        {mode === "edit" && !loading && campaign && editable && (
          <div className="mt-6">
            <CampaignWizard
              mode="edit"
              isEditor={isEditor}
              campaignId={campaign.id}
              campaignType={campaign.type}
              initialFields={initialFields}
              roster={roster}
              initialParticipantIds={initialParticipantIds}
              initialActionsByParticipant={initialActionsByParticipant}
              lockedPosts={lockedPosts}
              onDone={(cid) => navigate(`/app/campaigns/${cid}`)}
              onCancel={() => navigate(backTo)}
            />
          </div>
        )}
      </div>
    </AppShell>
  );
}
