import { useCallback, useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { AppShell } from "@/components/AppShell";
import {
  type CampaignFieldsValue,
  emptyCampaignFields,
} from "@/components/CampaignFields";
import { CampaignWizard } from "@/components/CampaignWizard";
import {
  type AssignmentDraft,
  type LockedPost,
  type RosterUser,
} from "@/components/PlanBuilder";
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
  self_comment: string | null;
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
    imageAssetId: c.image_asset_id ?? "",
    selfComment: c.self_comment ?? "",
  };
}

function rowsFromPosts(posts: Post[]): AssignmentDraft[] {
  const posterPosts = posts.filter((p) => p.action === "post");
  return posts
    .filter((p) => p.status === "pending")
    .map((p) => ({
      user_id: p.user_id,
      action: p.action,
      body: p.body ?? undefined,
      target_post_index: p.target_post_id
        ? Math.max(
            0,
            posterPosts.findIndex((pp) => pp.id === p.target_post_id),
          )
        : undefined,
    }));
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
  const [initialRows, setInitialRows] = useState<AssignmentDraft[]>([]);
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
      setInitialRows(rowsFromPosts(p.items));
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
              initialRows={initialRows}
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
