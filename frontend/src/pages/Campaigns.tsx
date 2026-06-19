import { type ReactNode, useCallback, useEffect, useState } from "react";
import { Megaphone, Plus, Send } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { AppShell } from "@/components/AppShell";
import { ApiError, apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Campaign {
  id: string;
  title: string;
  type: string;
  status: string;
  created_at: string;
}

interface CampaignsPage {
  items: Campaign[];
  next_cursor: string | null;
}

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-sand text-muted-ink",
  generating: "bg-pending/15 text-pending",
  review: "bg-clay/15 text-clay",
  publishing: "bg-pending/15 text-pending",
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
      {status}
    </span>
  );
}

export function Campaigns() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isEditor = user?.role === "editor" || user?.role === "admin";

  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

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
            onClick={() => setShowForm((s) => !s)}
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

        {showForm && (
          <NewCampaignForm
            isEditor={isEditor}
            onCancel={() => setShowForm(false)}
            onCreated={(id) => navigate(`/app/campaigns/${id}`)}
          />
        )}

        <div className="mt-6 overflow-hidden rounded-lg border border-border">
          {campaigns.length === 0 && !loading ? (
            <div className="flex flex-col items-center gap-2 p-12 text-center">
              <Megaphone className="h-8 w-8 text-muted-ink" />
              <p className="text-sm text-muted-ink">No campaigns yet.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-sand/50 text-left text-xs font-medium uppercase tracking-wider text-muted-ink">
                  <th className="px-4 py-3">Title</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c) => (
                  <tr
                    key={c.id}
                    className="border-b border-border last:border-b-0 hover:bg-sand/30"
                  >
                    <td className="px-4 py-3">
                      <Link
                        to={`/app/campaigns/${c.id}`}
                        className="font-medium text-ink hover:underline"
                      >
                        {c.title}
                      </Link>
                    </td>
                    <td className="px-4 py-3 capitalize text-muted-ink">{c.type}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={c.status} />
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
    </AppShell>
  );
}

function NewCampaignForm({
  isEditor,
  onCancel,
  onCreated,
}: {
  isEditor: boolean;
  onCancel: () => void;
  onCreated: (id: string) => void;
}) {
  const [type, setType] = useState<"amplify" | "distribute">("amplify");
  const [title, setTitle] = useState("");
  const [seedUrl, setSeedUrl] = useState("");
  const [seedContent, setSeedContent] = useState("");
  const [tone, setTone] = useState("");
  const [length, setLength] = useState("");
  const [language, setLanguage] = useState("en");
  const [link, setLink] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    if (!title.trim()) {
      setError("Title is required.");
      return;
    }
    setSubmitting(true);
    try {
      const created = await apiFetch<{ id: string }>("/v1/campaigns", {
        method: "POST",
        body: JSON.stringify({
          title,
          type,
          seed_url: seedUrl || null,
          seed_content: seedContent || null,
          tone: tone || null,
          length: length || null,
          language,
          link: link || null,
          image_url: imageUrl || null,
        }),
      });
      onCreated(created.id);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to create campaign",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-4 rounded-lg border border-border bg-surface p-5">
      <div className="flex gap-2">
        <TypeToggle
          active={type === "amplify"}
          label="Amplify"
          hint="Interactions on an existing post"
          onClick={() => setType("amplify")}
        />
        <TypeToggle
          active={type === "distribute"}
          label="Distribute"
          hint="Generate variations, publish, then amplify"
          disabled={!isEditor}
          onClick={() => isEditor && setType("distribute")}
        />
      </div>
      {!isEditor && (
        <p className="mt-2 text-xs text-muted-ink">
          Distribute campaigns require the editor role.
        </p>
      )}

      <div className="mt-4 grid gap-3">
        <Field label="Title">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Q3 launch amplification"
            className="input"
          />
        </Field>
        <Field
          label={type === "amplify" ? "Post URL to amplify" : "Seed post URL (optional)"}
        >
          <input
            value={seedUrl}
            onChange={(e) => setSeedUrl(e.target.value)}
            placeholder="https://www.linkedin.com/feed/update/urn:li:activity:..."
            className="input"
          />
        </Field>
        <Field label="Seed / reference text (optional)">
          <textarea
            value={seedContent}
            onChange={(e) => setSeedContent(e.target.value)}
            rows={3}
            placeholder="Paste the post text to use as generation context."
            className="input"
          />
        </Field>

        <div className="grid grid-cols-3 gap-3">
          <Field label="Tone">
            <input
              value={tone}
              onChange={(e) => setTone(e.target.value)}
              placeholder="warm, candid"
              className="input"
            />
          </Field>
          <Field label="Length">
            <input
              value={length}
              onChange={(e) => setLength(e.target.value)}
              placeholder="short"
              className="input"
            />
          </Field>
          <Field label="Language">
            <input
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="input"
            />
          </Field>
        </div>

        {type === "distribute" && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Link (optional)">
              <input
                value={link}
                onChange={(e) => setLink(e.target.value)}
                placeholder="https://..."
                className="input"
              />
            </Field>
            <Field label="Default image URL (optional)">
              <input
                value={imageUrl}
                onChange={(e) => setImageUrl(e.target.value)}
                placeholder="https://..."
                className="input"
              />
            </Field>
          </div>
        )}
      </div>

      {error && <p className="mt-3 text-sm text-fail">{error}</p>}

      <div className="mt-4 flex justify-end gap-2">
        <button
          onClick={onCancel}
          className="rounded-md border border-border px-4 py-2 text-sm text-muted-ink hover:bg-sand"
        >
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={submitting}
          className="inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2 text-sm font-medium text-paper hover:opacity-90 disabled:opacity-50"
        >
          <Send className="h-4 w-4" />
          {submitting ? "Creating..." : "Create"}
        </button>
      </div>
    </div>
  );
}

function TypeToggle({
  active,
  label,
  hint,
  disabled,
  onClick,
}: {
  active: boolean;
  label: string;
  hint: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex-1 rounded-md border px-4 py-3 text-left transition-colors",
        active ? "border-ink bg-paper" : "border-border bg-sand/40",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <p className="text-sm font-medium text-ink">{label}</p>
      <p className="text-xs text-muted-ink">{hint}</p>
    </button>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted-ink">{label}</span>
      {children}
    </label>
  );
}
