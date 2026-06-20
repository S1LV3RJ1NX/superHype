import { type ReactNode } from "react";
import { Info } from "lucide-react";

import { cn } from "@/lib/utils";

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
  link: string;
  imageUrl: string;
}

export function emptyCampaignFields(): CampaignFieldsValue {
  return {
    type: "amplify",
    title: "",
    seedUrl: "",
    seedContent: "",
    tones: [],
    length: "",
    link: "",
    imageUrl: "",
  };
}

export function campaignFieldsToPayload(v: CampaignFieldsValue) {
  return {
    title: v.title,
    type: v.type,
    seed_url: v.seedUrl || null,
    seed_content: v.seedContent || null,
    tone: v.tones.join(", ") || null,
    length: v.length || null,
    link: v.link || null,
    image_url: v.imageUrl || null,
  };
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
              hint="Generate variations, publish, then amplify"
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
        <Field label="Title">
          <input
            value={value.title}
            onChange={(e) => onChange({ title: e.target.value })}
            placeholder="Q3 launch amplification"
            className="input"
          />
        </Field>
        <Field
          label={
            type === "amplify" ? "Post URL to amplify" : "Seed post URL (optional)"
          }
        >
          <input
            value={value.seedUrl}
            onChange={(e) => onChange({ seedUrl: e.target.value })}
            placeholder="https://www.linkedin.com/feed/update/urn:li:activity:..."
            className="input"
          />
        </Field>
        <Field
          label={
            type === "amplify"
              ? "Paste the post text (powers AI comments)"
              : "Seed / reference text (optional)"
          }
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
          <div className="grid grid-cols-2 gap-3">
            <Field label="Link (optional)">
              <input
                value={value.link}
                onChange={(e) => onChange({ link: e.target.value })}
                placeholder="https://..."
                className="input"
              />
            </Field>
            <Field label="Default image URL (optional)">
              <input
                value={value.imageUrl}
                onChange={(e) => onChange({ imageUrl: e.target.value })}
                placeholder="https://..."
                className="input"
              />
            </Field>
          </div>
        )}
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

export function Hint({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-clay/30 bg-clay/10 px-3 py-2 text-xs font-medium text-clay">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted-ink">
        {label}
      </span>
      {children}
    </label>
  );
}
