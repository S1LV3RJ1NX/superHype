import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Info, Loader2, Upload, X } from "lucide-react";

import { MarkdownEditor } from "@/components/MarkdownEditor";
import { ApiError, fetchAssetObjectUrl, uploadAsset } from "@/lib/api";
import { cn } from "@/lib/utils";

const ACCEPTED_MEDIA = "image/png,image/jpeg,image/gif,image/webp,video/mp4,video/quicktime";

export const TONE_OPTIONS = [
  "Professional",
  "Warm",
  "Candid",
  "Bold",
  "Witty",
  "Analytical",
  "Supportive",
  "Contrarian",
] as const;

export const LENGTH_OPTIONS = [
  "Short (~30 words)",
  "Medium (~60 words)",
  "Long (~120 words)",
] as const;

// "publishing" reads as "Active" in the UI: the campaign is launched and posts
// are flowing out as people approve.
const CAMPAIGN_STATUS_LABEL: Record<string, string> = {
  publishing: "Active",
};

export function campaignStatusLabel(status: string): string {
  return CAMPAIGN_STATUS_LABEL[status] ?? status;
}

export interface CampaignFieldsValue {
  type: "amplify" | "distribute";
  title: string;
  seedUrl: string;
  seedContent: string;
  tones: string[];
  length: string;
  imageUrl: string;
  // Ordered pool of uploaded media asset ids. Each distribute participant is
  // assigned one by rotation at plan build. Order is the rotation order.
  mediaAssetIds: string[];
  selfComment: string;
  campaignRules: string;
  applyGlobalRules: boolean;
  // Native datetime-local string ("YYYY-MM-DDTHH:MM") for the scheduled launch,
  // or "" when the campaign is launched manually. Read in the team timezone.
  scheduledAt: string;
}

export function emptyCampaignFields(): CampaignFieldsValue {
  return {
    type: "amplify",
    title: "",
    seedUrl: "",
    seedContent: "",
    tones: [],
    length: "",
    imageUrl: "",
    mediaAssetIds: [],
    selfComment: "",
    campaignRules: "",
    applyGlobalRules: true,
    scheduledAt: "",
  };
}

export function campaignFieldsToPayload(v: CampaignFieldsValue) {
  return {
    title: v.title,
    type: v.type,
    // Distribute generates its own posts and never reads a URL, so a seed URL is
    // only meaningful for amplify.
    seed_url: v.type === "amplify" ? v.seedUrl || null : null,
    seed_content: v.seedContent || null,
    tone: v.tones.join(", ") || null,
    length: v.length || null,
    // image_url is carried through untouched; media is now the ordered pool.
    image_url: v.imageUrl || null,
    media: v.mediaAssetIds.map((id) => ({ asset_id: id, alt: null })),
    self_comment: v.selfComment || null,
    custom_rules: v.campaignRules || null,
    apply_global_rules: v.applyGlobalRules,
    // A naive datetime-local value is read by the backend in the team timezone.
    scheduled_at: v.scheduledAt || null,
  };
}

// Format an ISO datetime (UTC from the API) as the "YYYY-MM-DDTHH:MM" a native
// datetime-local input expects, in the browser's local time (which matches the
// team timezone for an internal tool). Returns "" for a null/blank input.
export function isoToDateTimeLocal(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

// Mirrors the backend parse_post_urn: a LinkedIn feed link resolves to an
// "activity" URN, but a reshare (which amplify always does) needs the original
// "share" or "ugcPost". Returns true when the pasted URL would reshare-fail so
// we can warn before launch instead of at publish.
function seedUrlLooksLikeActivity(raw: string): boolean {
  const url = raw.trim();
  if (!url) return false;
  const labeled = url.match(/(activity|share|ugcpost)[:-](\d{6,})/i);
  if (labeled) return labeled[1].toLowerCase() === "activity";
  // A bare post id with no namespace is treated as an activity URN.
  return /\d{6,}/.test(url);
}

// LinkedIn's "Embed this post" hands you an <iframe> whose src carries the
// reshareable share URN. Pull the src out so we store a tidy URL instead of the
// whole HTML snippet (the parser copes with either, but the clean URL reads
// better and is what the warnings inspect).
function extractSeedUrl(raw: string): string {
  const iframe = raw.match(/<iframe[^>]*\ssrc=["']([^"']+)["']/i);
  return iframe ? iframe[1] : raw;
}

// Cheap client-side mirror of the backend guard: catch obvious non-URLs (like
// "test") before submit. It is intentionally permissive, since the backend is
// authoritative and is the only side that can expand an lnkd.in short link, so
// those are accepted optimistically here rather than flagged.
function seedUrlLooksResolvable(raw: string): boolean {
  const url = raw.trim();
  if (!url) return true;
  if (/(^|\/\/)([a-z0-9-]+\.)*lnkd\.in\//i.test(url)) return true;
  if (/(activity|share|ugcpost)[:-]\d{6,}/i.test(url)) return true;
  return /\d{17,}/.test(url);
}

export function CampaignFields({
  value,
  onChange,
  isEditor,
  lockType = false,
}: {
  value: CampaignFieldsValue;
  onChange: (patch: Partial<CampaignFieldsValue>) => void;
  isEditor: boolean;
  lockType?: boolean;
}) {
  const { type } = value;

  return (
    <div>
      {!lockType && (
        <>
          <div className="flex gap-2">
            <TypeToggle
              active={type === "amplify"}
              label="Amplify"
              hint="Interactions on an existing post"
              onClick={() => onChange({ type: "amplify" })}
            />
            <TypeToggle
              active={type === "distribute"}
              label="Distribute"
              hint="Generate new posts for each member and amplify"
              disabled={!isEditor}
              onClick={() => isEditor && onChange({ type: "distribute" })}
            />
          </div>
          {!isEditor && (
            <div className="mt-2">
              <Hint>Distribute campaigns require the editor role.</Hint>
            </div>
          )}
        </>
      )}

      <div className={cn("grid gap-3", !lockType && "mt-4")}>
        <Field label="Title" required>
          <input
            value={value.title}
            onChange={(e) => onChange({ title: e.target.value })}
            placeholder="Q3 launch amplification"
            className="input"
          />
        </Field>
        {type === "amplify" && (
          <Field label="Post to amplify" required>
            <input
              value={value.seedUrl}
              onChange={(e) =>
                onChange({ seedUrl: extractSeedUrl(e.target.value) })
              }
              placeholder="Paste the post's Embed code (recommended), or a share / lnkd.in link"
              className="input"
            />
            <div className="mt-1.5">
              <Hint>
                Open the post's "..." menu on LinkedIn, choose "Embed this post",
                and paste the code here. That is the one option that carries a
                reshareable link, so the repost step works. "Copy link to post"
                gives an activity link that cannot be reshared.
              </Hint>
            </div>
            {seedUrlLooksLikeActivity(value.seedUrl) && (
              <div className="mt-2 flex items-start gap-2 rounded-md border border-pending/30 bg-pending/5 px-3 py-2 text-xs font-medium text-pending">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  This is an activity link (from "Copy link to post"). Likes and
                  comments will still work, but LinkedIn cannot reshare an
                  activity URN, so the repost is skipped. To include the repost,
                  open the post's "..." menu, choose "Embed this post", and paste
                  that code here instead.
                </span>
              </div>
            )}
            {value.seedUrl.trim() !== "" &&
              !seedUrlLooksResolvable(value.seedUrl) && (
                <div className="mt-2 flex items-start gap-2 rounded-md border border-pending/30 bg-pending/5 px-3 py-2 text-xs font-medium text-pending">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>
                    This does not look like a LinkedIn post. Use the post's "..."
                    menu, choose "Embed this post", and paste that code (or a
                    share / lnkd.in link).
                  </span>
                </div>
              )}
          </Field>
        )}
        <Field
          label={
            type === "amplify"
              ? "Paste the post text (powers AI comments)"
              : "Seed text (turned into each member's post)"
          }
          required
        >
          <textarea
            value={value.seedContent}
            onChange={(e) => onChange({ seedContent: e.target.value })}
            rows={4}
            placeholder={
              type === "amplify"
                ? "Paste the full text of the post you're amplifying. The AI writes comments and reshares about this, so without it the suggestions will be generic."
                : "Paste the announcement or idea to turn into variations."
            }
            className="input"
          />
          {type === "amplify" && (
            <div className="mt-2">
              <Hint>
                We can only read the post URL, not its text, so paste the content
                here for relevant AI suggestions.
              </Hint>
            </div>
          )}
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Tone">
            <div className="flex flex-wrap gap-1.5">
              {TONE_OPTIONS.map((option) => {
                const selected = value.tones.includes(option);
                return (
                  <button
                    key={option}
                    type="button"
                    onClick={() =>
                      onChange({
                        tones: selected
                          ? value.tones.filter((t) => t !== option)
                          : [...value.tones, option],
                      })
                    }
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs transition-colors",
                      selected
                        ? "border-ink bg-ink text-paper"
                        : "border-border bg-sand/40 text-muted-ink hover:bg-sand",
                    )}
                  >
                    {option}
                  </button>
                );
              })}
            </div>
          </Field>
          <Field label="Length">
            <select
              value={value.length}
              onChange={(e) => onChange({ length: e.target.value })}
              className="input"
            >
              <option value="">No preference</option>
              {LENGTH_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Hint>
          Tone and length shape the reshare message
          {type === "distribute" ? " and the generated posts" : ""}. Comments are
          written from the post content you pasted above.
        </Hint>

        <Field label="Schedule launch (optional)">
          <div className="flex items-center gap-2">
            <input
              type="datetime-local"
              value={value.scheduledAt}
              onChange={(e) => onChange({ scheduledAt: e.target.value })}
              className="input"
            />
            {value.scheduledAt && (
              <button
                type="button"
                onClick={() => onChange({ scheduledAt: "" })}
                className="rounded-md border border-border bg-sand/40 px-3 py-1.5 text-xs text-muted-ink hover:bg-sand"
              >
                Clear
              </button>
            )}
          </div>
          <div className="mt-2">
            <Hint>
              Pick a date and time to auto-launch this campaign (it must be in
              review by then). Only one campaign can be scheduled per day across
              the team, so the chosen day is reserved even while this stays a
              draft. Leave empty to launch manually.
            </Hint>
          </div>
        </Field>

        <Field label="Campaign rules (optional)">
          <MarkdownEditor
            value={value.campaignRules}
            onChange={(campaignRules) => onChange({ campaignRules })}
            minHeight={140}
            placeholder="Rules that apply only to this campaign, e.g. mention the new pricing page, keep it under 150 words."
          />
          <label className="mt-2 flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={value.applyGlobalRules}
              onChange={(e) => onChange({ applyGlobalRules: e.target.checked })}
              className="h-4 w-4 rounded border-border text-clay focus:ring-ring"
            />
            Apply the global content rules to this campaign
          </label>
          <div className="mt-2">
            <Hint>
              Campaign rules are added on top of the org-wide global content rules
              during generation. Uncheck to use only this campaign's rules.
            </Hint>
          </div>
        </Field>

        {type === "distribute" && (
          <>
            <Field label="Campaign media (optional)">
              <MediaGallery
                assetIds={value.mediaAssetIds}
                onChange={(ids) => onChange({ mediaAssetIds: ids })}
              />
              <div className="mt-2">
                <Hint>
                  Add one or more images, GIFs, or videos. Each participant is
                  assigned one by rotation, so a large campaign spreads media
                  across people instead of repeating a single file. PNG, JPEG,
                  GIF, WebP, or MP4/MOV.
                </Hint>
              </div>
            </Field>
            <Field label="Self comment (optional)">
              <textarea
                value={value.selfComment}
                onChange={(e) => onChange({ selfComment: e.target.value })}
                rows={2}
                placeholder="For more details: https://www.example.com/blog/..."
                className="input"
              />
              <div className="mt-2">
                <Hint>
                  The author posts this as a comment on their own post a short
                  while after publishing (a natural "link in the comments").
                </Hint>
              </div>
            </Field>
          </>
        )}
      </div>
    </div>
  );
}

// One preview tile in the media gallery. Loads its own preview from the asset
// API (the asset is already uploaded), so the gallery only tracks asset ids.
function MediaThumb({
  assetId,
  onRemove,
  disabled,
}: {
  assetId: string;
  onRemove: () => void;
  disabled?: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [kind, setKind] = useState<"image" | "video">("image");
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAssetObjectUrl(assetId)
      .then(({ url, contentType }) => {
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        urlRef.current = url;
        setKind(contentType.startsWith("video/") ? "video" : "image");
        setUrl(url);
      })
      .catch(() => {
        /* preview is best-effort */
      });
    return () => {
      cancelled = true;
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current);
        urlRef.current = null;
      }
    };
  }, [assetId]);

  return (
    <div className="relative h-24 w-24">
      {url ? (
        kind === "video" ? (
          <video
            src={url}
            controls
            className="h-24 w-24 rounded-md border border-border object-cover"
          />
        ) : (
          <img
            src={url}
            alt="Campaign media preview"
            className="h-24 w-24 rounded-md border border-border object-cover"
          />
        )
      ) : (
        <div className="flex h-24 w-24 items-center justify-center rounded-md border border-border bg-sand/40">
          <Loader2 className="h-5 w-5 animate-spin text-muted-ink" />
        </div>
      )}
      <button
        type="button"
        onClick={onRemove}
        disabled={disabled}
        aria-label="Remove media"
        className="absolute -right-2 -top-2 rounded-full border border-border bg-paper p-1 text-muted-ink shadow-sm hover:bg-sand disabled:opacity-50"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function MediaGallery({
  assetIds,
  onChange,
}: {
  assetIds: string[];
  onChange: (ids: string[]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = async (files: FileList) => {
    setError(null);
    setBusy(true);
    try {
      const uploaded: string[] = [];
      // Upload sequentially so an early failure does not leave a half-added set.
      for (const file of Array.from(files)) {
        const { id } = await uploadAsset(file);
        uploaded.push(id);
      }
      onChange([...assetIds, ...uploaded]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setBusy(false);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
    }
  };

  const removeAt = (idx: number) => {
    onChange(assetIds.filter((_, i) => i !== idx));
  };

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_MEDIA}
        multiple
        className="hidden"
        onChange={(e) => {
          const files = e.target.files;
          if (files && files.length) void handleFiles(files);
        }}
      />
      <div className="flex flex-wrap items-center gap-3">
        {assetIds.map((id, idx) => (
          <MediaThumb
            key={id}
            assetId={id}
            disabled={busy}
            onRemove={() => removeAt(idx)}
          />
        ))}
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="inline-flex h-24 w-24 flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border text-xs text-muted-ink hover:bg-sand disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <Upload className="h-5 w-5" />
          )}
          {busy ? "Uploading" : "Add media"}
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-fail">{error}</p>}
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

export function Hint({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-clay/30 bg-clay/10 px-3 py-2 text-xs font-medium text-clay">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

function Field({
  label,
  required = false,
  children,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted-ink">
        {label}
        {required && <span className="ml-0.5 text-fail">*</span>}
      </span>
      {children}
    </label>
  );
}
