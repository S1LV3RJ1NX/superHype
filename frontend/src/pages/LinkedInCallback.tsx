import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { Wordmark } from "@/components/Wordmark";
import { apiFetch, ApiError } from "@/lib/api";

export function LinkedInCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const exchanging = useRef(false);

  useEffect(() => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    if (!code || !state) {
      setError("Missing authorization code or state from LinkedIn.");
      return;
    }

    if (exchanging.current) return;
    exchanging.current = true;

    (async () => {
      try {
        const result = await apiFetch<{ resumed_campaign_id?: string | null }>(
          "/v1/connections/linkedin/callback",
          {
            method: "POST",
            body: JSON.stringify({ code, state }),
          },
        );
        if (result.resumed_campaign_id) {
          // Reconnected as part of approving a post: return to that campaign,
          // where the queued action is now publishing.
          navigate(`/app/campaigns/${result.resumed_campaign_id}?reconnected=1`, {
            replace: true,
          });
        } else {
          navigate("/app/connections", { replace: true });
        }
      } catch (err) {
        exchanging.current = false;
        setError(
          err instanceof ApiError
            ? err.message
            : "LinkedIn connection failed. Please try again.",
        );
      }
    })();
  }, [searchParams, navigate]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-paper text-ink">
        <Wordmark className="text-2xl" />
        <p className="max-w-md text-center text-sm text-fail">{error}</p>
        <a
          href="/app/connections"
          className="text-sm text-clay underline underline-offset-2"
        >
          Back to Connectors
        </a>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-paper text-ink">
      <Wordmark className="text-2xl" />
      <p className="text-sm text-muted-ink">Connecting your LinkedIn account...</p>
    </div>
  );
}
