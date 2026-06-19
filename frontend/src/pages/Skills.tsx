import { useCallback, useEffect, useState } from "react";
import {
  Archive,
  Check,
  Eye,
  Loader2,
  Lock,
  Plus,
  Rocket,
  Save,
  Sparkles,
  Star,
  X,
} from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { apiFetch, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Skill {
  id: string;
  name: string;
  description: string | null;
  instructions: string;
  is_default: boolean;
  is_archived: boolean;
  is_seed: boolean;
  status: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export function Skills() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [selected, setSelected] = useState<Skill | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editInstructions, setEditInstructions] = useState("");

  const [generating, setGenerating] = useState(false);
  const [genPrompt, setGenPrompt] = useState("");
  const [genOpen, setGenOpen] = useState(false);

  const [testing, setTesting] = useState(false);
  const [testOutput, setTestOutput] = useState<object | null>(null);
  const [testBrief, setTestBrief] = useState(
    "We just launched a great new feature that improves onboarding by 3x.",
  );

  const [publishing, setPublishing] = useState(false);

  const fetchSkills = useCallback(async () => {
    setLoading(true);
    try {
      const page = await apiFetch<{ items: Skill[]; next_cursor: string | null }>(
        "/v1/skills?limit=100",
      );
      setSkills(page.items);
      if (!selected && page.items.length > 0) {
        selectSkill(page.items[0]);
      }
    } catch {
      // handled by apiFetch
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  const selectSkill = (s: Skill) => {
    setSelected(s);
    setEditName(s.name);
    setEditDesc(s.description ?? "");
    setEditInstructions(s.instructions);
    setCreating(false);
    setError(null);
    setGenOpen(false);
    setTestOutput(null);
  };

  const startNew = () => {
    setSelected(null);
    setEditName("");
    setEditDesc("");
    setEditInstructions("");
    setCreating(true);
    setError(null);
    setGenOpen(true);
    setTestOutput(null);
  };

  const isLocked = selected?.is_seed === true;

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      if (creating) {
        const created = await apiFetch<Skill>("/v1/skills", {
          method: "POST",
          body: JSON.stringify({
            name: editName,
            description: editDesc || null,
            instructions: editInstructions,
          }),
        });
        setSkills((prev) => [...prev, created]);
        selectSkill(created);
        setCreating(false);
      } else if (selected && !isLocked) {
        const updated = await apiFetch<Skill>(`/v1/skills/${selected.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            name: editName,
            description: editDesc || null,
            instructions: editInstructions,
          }),
        });
        setSkills((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
        selectSkill(updated);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleSetDefault = async () => {
    if (!selected) return;
    setError(null);
    try {
      const updated = await apiFetch<Skill>(
        `/v1/skills/${selected.id}/set-default`,
        { method: "POST" },
      );
      setSkills((prev) =>
        prev.map((s) =>
          s.id === updated.id ? updated : { ...s, is_default: false },
        ),
      );
      selectSkill(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Set default failed");
    }
  };

  const handleArchive = async () => {
    if (!selected || isLocked) return;
    if (!confirm(`Archive "${selected.name}"? It will no longer appear in the list.`))
      return;
    setError(null);
    try {
      await apiFetch(`/v1/skills/${selected.id}`, { method: "DELETE" });
      const remaining = skills.filter((s) => s.id !== selected.id);
      setSkills(remaining);
      if (remaining.length > 0) {
        selectSkill(remaining[0]);
      } else {
        setSelected(null);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Archive failed");
    }
  };

  const handleGenerate = async () => {
    if (!genPrompt.trim()) return;
    setGenerating(true);
    setError(null);
    try {
      const result = await apiFetch<{ instructions: string }>(
        "/v1/skills/generate-instructions",
        {
          method: "POST",
          body: JSON.stringify({ description: genPrompt }),
        },
      );
      setEditInstructions(result.instructions);
      if (!editName) {
        const words = genPrompt.split(/\s+/).slice(0, 4).join(" ");
        setEditName(words.charAt(0).toUpperCase() + words.slice(1));
      }
      if (!editDesc) setEditDesc(genPrompt);
      setGenOpen(false);
      setGenPrompt("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  };

  const handleTest = async () => {
    if (!selected) return;
    setTesting(true);
    setError(null);
    setTestOutput(null);
    try {
      const result = await apiFetch<{ output: object }>(
        `/v1/skills/${selected.id}/test`,
        {
          method: "POST",
          body: JSON.stringify({
            title: "Test Campaign",
            raw_brief: testBrief,
          }),
        },
      );
      setTestOutput(result.output);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Test failed");
    } finally {
      setTesting(false);
    }
  };

  const handlePublish = async () => {
    if (!selected) return;
    setPublishing(true);
    setError(null);
    try {
      const updated = await apiFetch<Skill>(
        `/v1/skills/${selected.id}/publish`,
        { method: "POST" },
      );
      setSkills((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      selectSkill(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Publish failed");
    } finally {
      setPublishing(false);
    }
  };

  const statusBadge = (skill: Skill) => {
    if (skill.is_seed)
      return (
        <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-muted-ink/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-ink">
          <Lock className="h-2.5 w-2.5" />
          Seed
        </span>
      );
    if (skill.status === "draft")
      return (
        <span className="ml-auto rounded-full bg-pending/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-pending">
          Draft
        </span>
      );
    return null;
  };

  return (
    <AppShell>
      <div className="mx-auto flex max-w-6xl gap-6">
        {/* Skill list */}
        <div className="w-60 shrink-0">
          <div className="flex items-center justify-between">
            <h1 className="font-serif text-2xl text-ink">Skills</h1>
            <button
              onClick={startNew}
              className="rounded-md bg-clay p-1.5 text-white transition-colors hover:bg-clay-press"
              title="New skill"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
          <p className="mt-1 text-sm text-muted-ink">Generation profiles</p>

          {loading ? (
            <div className="mt-6 flex justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-muted-ink" />
            </div>
          ) : (
            <ul className="mt-4 space-y-1">
              {skills.map((s) => (
                <li key={s.id}>
                  <button
                    onClick={() => selectSkill(s)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors",
                      selected?.id === s.id && !creating
                        ? "bg-surface font-medium text-ink shadow-sm"
                        : "text-muted-ink hover:bg-surface/60",
                    )}
                  >
                    {s.is_default && (
                      <Star className="h-3.5 w-3.5 shrink-0 text-clay" />
                    )}
                    <span className="min-w-0 truncate">{s.name}</span>
                    {statusBadge(s)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Editor pane */}
        <div className="min-w-0 flex-1">
          {!selected && !creating ? (
            <div className="mt-12 text-center text-sm text-muted-ink">
              Select a skill or create a new one.
            </div>
          ) : (
            <div className="rounded-lg border border-border bg-surface p-6">
              {/* Header: seed lock banner */}
              {isLocked && (
                <div className="mb-4 flex items-center gap-2 rounded-md border border-muted-ink/20 bg-muted-ink/5 px-4 py-2 text-sm text-muted-ink">
                  <Lock className="h-4 w-4 shrink-0" />
                  This is the seed skill. It is read-only and cannot be modified from the UI.
                </div>
              )}

              {error && (
                <div className="mb-4 rounded-md border border-fail/20 bg-fail/5 px-4 py-2 text-sm text-fail">
                  {error}
                </div>
              )}

              <div className="space-y-4">
                <div>
                  <label className="text-xs font-medium uppercase tracking-wider text-muted-ink">
                    Name
                  </label>
                  <input
                    type="text"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    disabled={isLocked}
                    className="mt-1 w-full rounded-md border border-border bg-paper px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
                  />
                </div>

                <div>
                  <label className="text-xs font-medium uppercase tracking-wider text-muted-ink">
                    Description
                  </label>
                  <input
                    type="text"
                    value={editDesc}
                    onChange={(e) => setEditDesc(e.target.value)}
                    placeholder="Optional"
                    disabled={isLocked}
                    className="mt-1 w-full rounded-md border border-border bg-paper px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-medium uppercase tracking-wider text-muted-ink">
                      Instructions (tone, style, and structure)
                    </label>
                    {!isLocked && (
                      <button
                        type="button"
                        onClick={() => setGenOpen(!genOpen)}
                        className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted-ink transition-colors hover:bg-sand hover:text-ink"
                      >
                        <Sparkles className="h-3.5 w-3.5" />
                        Generate with AI
                      </button>
                    )}
                  </div>

                  {genOpen && !isLocked && (
                    <div className="mt-2 rounded-md border border-clay/20 bg-clay/5 p-3">
                      <p className="mb-2 text-xs text-muted-ink">
                        Describe the kind of posts this skill should produce and
                        AI will draft the full system prompt for you.
                      </p>
                      <textarea
                        value={genPrompt}
                        onChange={(e) => setGenPrompt(e.target.value)}
                        rows={3}
                        placeholder='e.g. "Professional yet warm LinkedIn posts for product launches, with hashtags and a conversational tone"'
                        className="w-full rounded-md border border-border bg-paper px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ring"
                      />
                      <div className="mt-2 flex items-center gap-2">
                        <button
                          onClick={handleGenerate}
                          disabled={generating || !genPrompt.trim()}
                          className="inline-flex items-center gap-1.5 rounded-md bg-clay px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-clay-press disabled:opacity-60"
                        >
                          {generating ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Sparkles className="h-3.5 w-3.5" />
                          )}
                          {generating ? "Generating..." : "Generate"}
                        </button>
                        <button
                          onClick={() => {
                            setGenOpen(false);
                            setGenPrompt("");
                          }}
                          className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs text-muted-ink transition-colors hover:bg-sand"
                        >
                          <X className="h-3.5 w-3.5" />
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  <p className="mt-1 text-[11px] text-muted-ink">
                    The JSON output format is appended automatically. Focus on tone, voice, length, and style.
                  </p>
                  <textarea
                    value={editInstructions}
                    onChange={(e) => setEditInstructions(e.target.value)}
                    rows={14}
                    disabled={isLocked}
                    className="mt-1 w-full rounded-md border border-border bg-paper px-3 py-2 font-mono text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
                  />
                </div>
              </div>

              {/* Action bar */}
              <div className="mt-6 flex flex-wrap items-center gap-3">
                {!isLocked && (
                  <button
                    onClick={handleSave}
                    disabled={saving || !editName || !editInstructions}
                    className="inline-flex items-center gap-2 rounded-md bg-clay px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-clay-press disabled:opacity-60"
                  >
                    {saving ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    {creating ? "Create as draft" : "Save"}
                  </button>
                )}

                {/* Test button */}
                {selected && !creating && (
                  <button
                    onClick={handleTest}
                    disabled={testing}
                    className="inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm text-muted-ink transition-colors hover:bg-sand"
                  >
                    {testing ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                    {testing ? "Testing..." : "Test"}
                  </button>
                )}

                {/* Publish button - for draft skills only */}
                {selected && !creating && !isLocked && selected.status === "draft" && (
                  <button
                    onClick={handlePublish}
                    disabled={publishing}
                    className="inline-flex items-center gap-2 rounded-md bg-ok px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-ok/90 disabled:opacity-60"
                  >
                    {publishing ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Rocket className="h-4 w-4" />
                    )}
                    Publish
                  </button>
                )}

                {selected && !creating && !selected.is_default && !isLocked && selected.status === "published" && (
                  <button
                    onClick={handleSetDefault}
                    className="inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm text-muted-ink transition-colors hover:bg-sand"
                  >
                    <Check className="h-4 w-4" />
                    Set as default
                  </button>
                )}

                {selected && !creating && selected.is_default && (
                  <span className="inline-flex items-center gap-1.5 text-sm text-clay">
                    <Star className="h-4 w-4" />
                    Default skill
                  </span>
                )}

                {selected && !creating && !isLocked && (
                  <button
                    onClick={handleArchive}
                    className="ml-auto inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm text-muted-ink transition-colors hover:bg-sand"
                  >
                    <Archive className="h-4 w-4" />
                    Archive
                  </button>
                )}
              </div>

              {/* Test panel */}
              {selected && !creating && (
                <div className="mt-6 border-t border-border pt-4">
                  <label className="text-xs font-medium uppercase tracking-wider text-muted-ink">
                    Test brief
                  </label>
                  <textarea
                    value={testBrief}
                    onChange={(e) => setTestBrief(e.target.value)}
                    rows={2}
                    placeholder="Describe a sample campaign to test this skill..."
                    className="mt-1 w-full rounded-md border border-border bg-paper px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ring"
                  />

                  {testOutput && (
                    <div className="mt-3">
                      <label className="text-xs font-medium uppercase tracking-wider text-muted-ink">
                        Example output
                      </label>
                      <pre className="mt-1 max-h-80 overflow-auto rounded-md border border-border bg-paper p-3 font-mono text-xs text-ink">
                        {JSON.stringify(testOutput, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
