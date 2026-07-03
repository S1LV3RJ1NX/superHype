import { useCallback, useEffect, useState } from "react";
import { Check, Loader2, ScrollText } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { apiFetch, ApiError } from "@/lib/api";

interface ContentRule {
  body: string | null;
  updated_by: string | null;
  updated_at: string;
}

export function ContentRules() {
  const [body, setBody] = useState("");
  const [initial, setInitial] = useState("");
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rule = await apiFetch<ContentRule>("/v1/content-rules");
      setBody(rule.body ?? "");
      setInitial(rule.body ?? "");
      setUpdatedAt(rule.updated_at);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load content rules");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const rule = await apiFetch<ContentRule>("/v1/content-rules", {
        method: "PUT",
        body: JSON.stringify({ body }),
      });
      setInitial(rule.body ?? "");
      setBody(rule.body ?? "");
      setUpdatedAt(rule.updated_at);
      setSavedAt(Date.now());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save content rules");
    } finally {
      setSaving(false);
    }
  };

  const dirty = body !== initial;

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl">
        <h1 className="flex items-center gap-2 font-serif text-2xl text-ink">
          <ScrollText className="h-6 w-6 text-muted-ink" />
          Content Rules
        </h1>
        <p className="mt-1 text-sm text-muted-ink">
          Global rules applied to every campaign's generated self-posts, comments,
          and reshares, for both amplify and distribute. Write them in Markdown.
          Campaign creators can add campaign-specific rules on top when creating a
          campaign. Only admins can edit these.
        </p>

        {error && (
          <div className="mt-4 rounded-md border border-fail/20 bg-fail/5 px-4 py-2 text-sm text-fail">
            {error}
          </div>
        )}

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-ink" />
          </div>
        ) : (
          <>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={20}
              placeholder={
                "e.g.\n- Always write in English.\n- Refer to the company as Acme.\n- Never promise timelines or unreleased features.\n- Keep a grounded, practitioner voice."
              }
              className="mt-6 w-full rounded-md border border-border bg-surface px-3 py-2 font-mono text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <div className="mt-3 flex items-center justify-between">
              <span className="text-xs text-muted-ink">
                {updatedAt
                  ? `Last updated ${new Date(updatedAt).toLocaleString()}`
                  : "Not set yet"}
              </span>
              <div className="flex items-center gap-3">
                {savedAt && !dirty && (
                  <span className="inline-flex items-center gap-1 text-xs text-ok">
                    <Check className="h-3.5 w-3.5" />
                    Saved
                  </span>
                )}
                <button
                  onClick={save}
                  disabled={saving || !dirty}
                  className="inline-flex items-center gap-2 rounded-md bg-clay px-4 py-2 text-sm font-medium text-paper hover:bg-clay-press disabled:opacity-50"
                >
                  {saving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Check className="h-4 w-4" />
                  )}
                  Save rules
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
