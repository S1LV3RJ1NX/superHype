import { useState } from "react";
import { AlertTriangle } from "lucide-react";

interface DeleteCampaignDialogProps {
  title: string;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export function DeleteCampaignDialog({
  title,
  busy,
  onConfirm,
  onClose,
}: DeleteCampaignDialogProps) {
  const [typed, setTyped] = useState("");
  // Exact, case-sensitive match: deleting is destructive and cannot be undone,
  // so the typed title must match the campaign title character for character.
  const matches = typed === title;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg border border-border bg-surface p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <span className="mt-0.5 rounded-full bg-fail/10 p-1.5 text-fail">
            <AlertTriangle className="h-4 w-4" />
          </span>
          <div>
            <h2 className="font-serif text-lg text-ink">Delete campaign</h2>
            <p className="mt-1 text-sm text-muted-ink">
              This permanently deletes{" "}
              <span className="font-medium text-ink">{title}</span> and all of its
              posts, interactions, and history. This cannot be undone.
            </p>
          </div>
        </div>

        <label className="mt-4 block">
          <span className="mb-1 block text-xs font-medium text-muted-ink">
            Type the campaign title to confirm
          </span>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={title}
            autoFocus
            className="input"
          />
        </label>

        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={busy}
            className="rounded-md border border-border px-4 py-2 text-sm text-muted-ink hover:bg-sand disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={!matches || busy}
            className="rounded-md bg-fail px-4 py-2 text-sm font-medium text-paper hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Deleting..." : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}
