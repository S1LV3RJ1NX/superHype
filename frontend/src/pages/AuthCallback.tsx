import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { Wordmark } from "@/components/Wordmark";
import { useAuth } from "@/auth/AuthContext";
import { apiFetch, ApiError } from "@/lib/api";

export function AuthCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { login } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const exchanging = useRef(false);

  useEffect(() => {
    const code = searchParams.get("code");
    if (!code) {
      setError("No authorization code received from Google.");
      return;
    }

    if (exchanging.current) return;
    exchanging.current = true;

    (async () => {
      try {
        const res = await apiFetch<{ access_token: string }>(
          "/v1/google/callback",
          { method: "POST", body: JSON.stringify({ code }), skipAuthRedirect: true },
        );
        await login(res.access_token);
        navigate("/app", { replace: true });
      } catch (err) {
        exchanging.current = false;
        setError(
          err instanceof ApiError
            ? err.message
            : "Login failed. Please try again.",
        );
      }
    })();
  }, [searchParams, login, navigate]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-paper text-ink">
        <Wordmark className="text-2xl" />
        <p className="max-w-md text-center text-sm text-fail">{error}</p>
        <a href="/" className="text-sm text-clay underline underline-offset-2">
          Back to home
        </a>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-paper text-ink">
      <Wordmark className="text-2xl" />
      <p className="text-sm text-muted-ink">Signing you in...</p>
    </div>
  );
}
