import { useState } from "react";
import { Check, Loader2 } from "lucide-react";

import { useAuth } from "@/auth/AuthContext";
import { apiFetch, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

export function autoApproveDelayLabel(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes >= 60 && minutes % 60 === 0) {
    const hours = minutes / 60;
    return `${hours} hour${hours === 1 ? "" : "s"}`;
  }
  return `${minutes} minute${minutes === 1 ? "" : "s"}`;
}

// Opt-in consent for auto-approve. Renders nothing while the deployment is
// manual-approval-only, so people are only ever asked about a mode that applies.
// Controlled mode (checked + onChange) lets onboarding collect the choice and
// save it on finish; uncontrolled mode saves each toggle straight away.
export function AutoApproveConsent({
  checked,
  onChange,
}: {
  checked?: boolean;
  onChange?: (next: boolean) => void;
}) {
  const { user, refresh } = useAuth();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!user?.auto_approve_available) return null;

  const controlled = onChange !== undefined;
  const on = controlled ? !!checked : !!user.auto_approve_consented_at;
  const delay = autoApproveDelayLabel(user.auto_approve_delay_seconds);

  const toggle = async () => {
    if (controlled) {
      onChange(!on);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await saveAutoApprove(!on);
      await refresh();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not update auto-approve",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <button
        type="button"
        role="checkbox"
        aria-checked={on}
        onClick={toggle}
        disabled={saving}
        className={cn(
          "flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left text-sm transition-colors disabled:opacity-60",
          on ? "border-clay bg-clay/5" : "border-border hover:bg-sand",
        )}
      >
        <span
          className={cn(
            "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border",
            on ? "border-clay bg-clay text-paper" : "border-border",
          )}
        >
          {saving ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            on && <Check className="h-3 w-3" />
          )}
        </span>
        <span>
          <span className="font-medium text-ink">Auto-approve my actions</span>
          <span className="mt-1 block leading-relaxed text-muted-ink">
            When a campaign asks for my posts, reshares, likes or comments, approve
            them automatically {delay} after I am notified, unless I skip them
            first. I can turn this off at any time from my profile.
          </span>
        </span>
      </button>
      {error && <p className="mt-2 text-sm text-fail">{error}</p>}
    </div>
  );
}

export async function saveAutoApprove(enabled: boolean): Promise<void> {
  await apiFetch("/v1/users/me/auto-approve", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}
