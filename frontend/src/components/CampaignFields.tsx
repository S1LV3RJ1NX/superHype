import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Info, Loader2, Upload, X } from "lucide-react";

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
  imageAssetId: string;
  selfComment: string;
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
    imageAssetId: "",
    selfComment: "",
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
    // image_url is carried through untouched; media is now set via image_asset_id.
    image_url: v.imageUrl || null,
    image_asset_id: v.imageAssetId || null,
    self_comment: v.selfComment || null,
  };
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
          <Field label="Post URL to amplify" required>
            <input
              value={value.seedUrl}
              onChange={(e) => onChange({ seedUrl: e.target.value })}
              placeholder="https://www.linkedin.com/feed/update/urn:li:share:..."
              className="input"
            />
            {seedUrlLooksLikeActivity(value.seedUrl) && (
              <div className="mt-2 flex items-start gap-2 rounded-md border border-pending/30 bg-pending/5 px-3 py-2 text-xs font-medium text-pending">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  This looks like a feed activity link. Likes and comments work,
                  but LinkedIn will not reshare an activity URN, so the repost step
                  will fail. Open the post, use its share or ugcPost link (the
                  direct post URL), and paste that instead.
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

        {type === "distribute" && (
          <>
            <Field label="Campaign media (optional)">
              <MediaUpload
                assetId={value.imageAssetId}
                onChange={(id) => onChange({ imageAssetId: id })}
              />
              <div className="mt-2">
                <Hint>
                  One image or short video applied to every generated post. PNG,
                  JPEG, GIF, WebP, or MP4/MOV.
                </Hint>
              </div>
            </Field>
            <Field label="Self comment (optional)">
              <textarea
                value={value.selfComment}
                onChange={(e) => onChange({ selfComment: e.target.value })}
                rows={2}
                placeholder="For more details: https://www.truefoundry.com/blog/..."
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

function MediaUpload({
  assetId,
  onChange,
}: {
  assetId: string;
  onChange: (id: string) => void;
}) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [kind, setKind] = useState<"image" | "video">("image");
  const [busy, setBusy] = useState(false);
  // True while the preview for an already-attached asset (edit mode) is loading,
  // so we show a spinner instead of flashing the empty "upload" state.
  const [hydrating, setHydrating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const setObjectUrl = (url: string | null) => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
    }
    objectUrlRef.current = url;
    setPreviewUrl(url);
  };

  // Load a preview for an already-attached asset (edit mode) that has no local
  // file yet. Skipped once a fresh file provides its own object URL.
  useEffect(() => {
    let cancelled = false;
    if (assetId && !objectUrlRef.current) {
      setHydrating(true);
      fetchAssetObjectUrl(assetId)
        .then(({ url, contentType }) => {
          if (cancelled) {
            URL.revokeObjectURL(url);
            return;
          }
          setKind(contentType.startsWith("video/") ? "video" : "image");
          setObjectUrl(url);
        })
        .catch(() => {
          /* preview is best-effort */
        })
        .finally(() => {
          if (!cancelled) setHydrating(false);
        });
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId]);

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
      }
    };
  }, []);

  const handleFile = async (file: File) => {
    setError(null);
    setKind(file.type.startsWith("video/") ? "video" : "image");
    setObjectUrl(URL.createObjectURL(file));
    setBusy(true);
    try {
      const { id } = await uploadAsset(file);
      onChange(id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
      setObjectUrl(null);
    } finally {
      setBusy(false);
    }
  };

  const clear = () => {
    setObjectUrl(null);
    setError(null);
    onChange("");
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  };

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_MEDIA}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handleFile(file);
        }}
      />
      {!previewUrl && hydrating ? (
        <div className="flex h-28 w-28 items-center justify-center rounded-md border border-border bg-sand/40">
          <Loader2 className="h-5 w-5 animate-spin text-muted-ink" />
        </div>
      ) : previewUrl ? (
        <div className="flex items-start gap-3">
          {kind === "video" ? (
            <video
              src={previewUrl}
              controls
              className="h-28 w-28 rounded-md border border-border object-cover"
            />
          ) : (
            <img
              src={previewUrl}
              alt="Campaign media preview"
              className="h-28 w-28 rounded-md border border-border object-cover"
            />
          )}
          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-ink hover:bg-sand disabled:opacity-50"
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Upload className="h-3.5 w-3.5" />
              )}
              Replace
            </button>
            <button
              type="button"
              onClick={clear}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-ink hover:bg-sand disabled:opacity-50"
            >
              <X className="h-3.5 w-3.5" />
              Remove
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-md border border-dashed border-border px-4 py-3 text-sm text-muted-ink hover:bg-sand disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Upload className="h-4 w-4" />
          )}
          {busy ? "Uploading..." : "Upload image or video"}
        </button>
      )}
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
