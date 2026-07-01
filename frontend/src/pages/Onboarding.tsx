import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Check, Loader2, Rocket } from "lucide-react";

import { useAuth } from "@/auth/AuthContext";
import { Wordmark } from "@/components/Wordmark";
import { apiFetch, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Team {
  id: string;
  name: string;
}

export function Onboarding() {
  const navigate = useNavigate();
  const { user, refresh } = useAuth();
  const [teams, setTeams] = useState<Team[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [step, setStep] = useState<1 | 2>(1);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const page = await apiFetch<{ items: Team[] }>("/v1/teams?limit=100");
        setTeams(page.items);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load teams");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const selectedTeam = teams.find((t) => t.id === selected) ?? null;

  const confirm = async () => {
    if (!selected) return;
    setSaving(true);
    setError(null);
    try {
      await apiFetch("/v1/users/me", {
        method: "PATCH",
        body: JSON.stringify({ team_id: selected }),
      });
      await refresh();
      navigate("/app", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your team");
      setSaving(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center bg-paper px-4 py-16 text-ink">
      <div className="w-full max-w-lg">
        <Wordmark className="text-xl" />

        <div className="mt-6 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-ink">
          <span className={cn(step === 1 && "text-ink")}>1. Your team</span>
          <span className="text-border">/</span>
          <span className={cn(step === 2 && "text-ink")}>2. Join in</span>
        </div>

        {error && (
          <div className="mt-4 rounded-md border border-fail/20 bg-fail/5 px-4 py-2 text-sm text-fail">
            {error}
          </div>
        )}

        {step === 1 ? (
          <>
            <h1 className="mt-4 font-serif text-2xl text-ink">
              Welcome{user?.name ? `, ${user.name.split(" ")[0]}` : ""}
            </h1>
            <p className="mt-1 text-sm text-muted-ink">
              Pick your team so campaigns can reach the right people. You can
              change this later from your profile.
            </p>

            {loading ? (
              <div className="mt-10 flex justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-muted-ink" />
              </div>
            ) : (
              <div className="mt-6 grid grid-cols-1 gap-2 sm:grid-cols-2">
                {teams.map((t) => {
                  const active = selected === t.id;
                  return (
                    <button
                      key={t.id}
                      onClick={() => setSelected(t.id)}
                      className={cn(
                        "flex items-center justify-between rounded-lg border px-4 py-3 text-left text-sm transition-colors",
                        active
                          ? "border-clay bg-clay/5 font-medium text-ink"
                          : "border-border text-muted-ink hover:bg-sand",
                      )}
                    >
                      {t.name}
                      {active && <Check className="h-4 w-4 text-clay" />}
                    </button>
                  );
                })}
              </div>
            )}

            <button
              onClick={() => setStep(2)}
              disabled={!selected}
              className="mt-8 inline-flex items-center gap-2 rounded-md bg-clay px-5 py-2.5 text-sm font-medium text-paper hover:bg-clay-press disabled:opacity-50"
            >
              Continue
            </button>
          </>
        ) : (
          <>
            <div className="mt-6 flex h-14 w-14 items-center justify-center rounded-full bg-clay/10">
              <Rocket className="h-7 w-7 text-clay" />
            </div>
            <h1 className="mt-4 font-serif text-2xl text-ink">
              Become a TrueHyper
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-muted-ink">
              You are joining the{" "}
              <span className="font-medium text-ink">{selectedTeam?.name}</span>{" "}
              crew in this community. As a TrueHyper you help your teammates' best
              work travel further: liking, commenting, and resharing so great
              ideas reach more people. Nothing ever goes out under your name until
              you approve it.
            </p>
            <p className="mt-3 text-sm font-medium text-ink">
              Ready to hype your team?
            </p>

            <div className="mt-8 flex items-center gap-3">
              <button
                onClick={() => setStep(1)}
                disabled={saving}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-4 py-2.5 text-sm text-muted-ink hover:bg-sand disabled:opacity-50"
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </button>
              <button
                onClick={confirm}
                disabled={saving}
                className="inline-flex items-center gap-2 rounded-md bg-clay px-5 py-2.5 text-sm font-medium text-paper hover:bg-clay-press disabled:opacity-50"
              >
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                I am in. Let's hype.
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
