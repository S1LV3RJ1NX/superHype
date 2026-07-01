import { useState } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";

import {
  CampaignFields,
  type CampaignFieldsValue,
  campaignFieldsToPayload,
  emptyCampaignFields,
} from "@/components/CampaignFields";
import {
  type LockedPost,
  PlanBuilder,
  type RosterUser,
} from "@/components/PlanBuilder";
import { ApiError, apiFetch } from "@/lib/api";
import { fetchAllRoster } from "@/lib/roster";

export function CampaignWizard({
  mode,
  isEditor,
  onDone,
  onCancel,
  campaignId,
  campaignType,
  initialFields,
  roster: initialRoster,
  initialParticipantIds,
  lockedPosts,
}: {
  mode: "create" | "edit";
  isEditor: boolean;
  onDone: (id: string) => void;
  onCancel: () => void;
  campaignId?: string;
  campaignType?: string;
  initialFields?: CampaignFieldsValue;
  roster?: RosterUser[];
  initialParticipantIds?: string[];
  lockedPosts?: LockedPost[];
}) {
  const isEdit = mode === "edit";

  const [step, setStep] = useState<1 | 2>(1);
  const [fields, setFields] = useState<CampaignFieldsValue>(
    initialFields ?? emptyCampaignFields(),
  );
  const [created, setCreated] = useState<{ id: string; type: string } | null>(
    isEdit && campaignId
      ? { id: campaignId, type: campaignType ?? fields.type }
      : null,
  );
  const [roster, setRoster] = useState<RosterUser[]>(initialRoster ?? []);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submitDetails = async () => {
    setError(null);
    if (!fields.title.trim()) {
      setError("Title is required.");
      return;
    }
    // Automation-first: a campaign is generated, so it needs source material.
    if (fields.type === "amplify") {
      if (!fields.seedUrl.trim()) {
        setError("Add the URL of the post to amplify.");
        return;
      }
      if (!fields.seedContent.trim()) {
        setError(
          "Paste the post text so the AI can write comments and reshares.",
        );
        return;
      }
    } else if (!fields.seedContent.trim()) {
      setError("Add seed text so the AI can generate the posts.");
      return;
    }
    setSubmitting(true);
    try {
      if (isEdit) {
        if (!campaignId) return;
        await apiFetch(`/v1/campaigns/${campaignId}`, {
          method: "PATCH",
          body: JSON.stringify(campaignFieldsToPayload(fields)),
        });
        setStep(2);
      } else {
        // Create first; only after the campaign exists do we fetch the roster,
        // so a roster failure can never cause a duplicate campaign on retry.
        const c = await apiFetch<{ id: string; type: string }>("/v1/campaigns", {
          method: "POST",
          body: JSON.stringify(campaignFieldsToPayload(fields)),
        });
        setCreated(c);
        try {
          setRoster(await fetchAllRoster());
        } catch {
          setError(
            "Campaign created, but loading the team list failed. You can still continue.",
          );
        }
        setStep(2);
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : isEdit
            ? "Failed to save campaign"
            : "Failed to create campaign",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const savePlan = async (participantIds: string[], generate: boolean) => {
    if (!created) return;
    setError(null);
    setSubmitting(true);
    try {
      await apiFetch(
        `/v1/campaigns/${created.id}/${generate ? "generate" : "plan"}`,
        {
          method: "POST",
          body: JSON.stringify({ participant_ids: participantIds }),
        },
      );
      onDone(created.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save plan");
      setSubmitting(false);
    }
  };

  const type = created?.type ?? campaignType ?? fields.type;

  return (
    <div className="rounded-lg border border-border bg-surface p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-ink">
        Step {step} of 2 &middot; {step === 1 ? "Details" : "Assign people"}
      </p>

      {step === 1 ? (
        <div className="mt-3">
          <CampaignFields
            value={fields}
            onChange={(patch) => setFields((f) => ({ ...f, ...patch }))}
            isEditor={isEditor}
            lockType={isEdit}
          />

          {error && <p className="mt-3 text-sm text-fail">{error}</p>}

          <div className="mt-4 flex justify-end gap-2">
            <button
              onClick={onCancel}
              disabled={submitting}
              className="rounded-md border border-border px-4 py-2 text-sm text-muted-ink hover:bg-sand disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={submitDetails}
              disabled={submitting}
              className="inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2 text-sm font-medium text-paper hover:opacity-90 disabled:opacity-50"
            >
              {submitting
                ? "Saving..."
                : isEdit
                  ? "Save and continue"
                  : "Create and continue"}
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3">
          <p className="mb-3 text-sm text-muted-ink">
            Pick who takes part. Actions are automatic based on the campaign type.
          </p>

          <PlanBuilder
            campaignType={type}
            roster={roster}
            isEditor={isEditor}
            busy={submitting}
            onPlan={savePlan}
            initialParticipantIds={initialParticipantIds}
            lockedPosts={lockedPosts}
          />

          {error && <p className="mt-3 text-sm text-fail">{error}</p>}

          <div className="mt-4 flex justify-between">
            <button
              onClick={() => setStep(1)}
              disabled={submitting}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-4 py-2 text-sm text-muted-ink hover:bg-sand disabled:opacity-50"
            >
              <ArrowLeft className="h-4 w-4" />
              Back
            </button>
            <button
              onClick={() => created && onDone(created.id)}
              disabled={submitting || !created}
              className="rounded-md border border-border px-4 py-2 text-sm text-muted-ink hover:bg-sand disabled:opacity-50"
            >
              {isEdit ? "Done" : "Save as draft"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
