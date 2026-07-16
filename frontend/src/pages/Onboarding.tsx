import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Check, Link2, Loader2, Rocket } from "lucide-react";

import { useAuth } from "@/auth/AuthContext";
import { LinkedInLogo, XLogo } from "@/components/PlatformLogos";
import { Wordmark } from "@/components/Wordmark";
import { apiFetch, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Team {
  id: string;
  name: string;
}

// Set before the LinkedIn OAuth hop so the callback knows to return here (to the
// final agreement step) instead of the Connectors page.
const ONBOARDING_RETURN_KEY = "onboarding_return";

type Step = 1 | 2 | 3;

export function Onboarding() {
  const navigate = useNavigate();
  const { user, refresh } = useAuth();
  const [teams, setTeams] = useState<Team[]>([]);
  const [selected, setSelected] = useState<string | null>(
    user?.team_id ?? null,
  );
  // Resume at the right step: no team yet lands on step 1, otherwise on the
  // connect step. Returning from a LinkedIn or X OAuth hop deliberately lands
  // back on step 2 (never auto-skips to 3) so the person can still connect the
  // optional X account; they advance to the agreement with Continue.
  const [step, setStep] = useState<Step>(!user?.team_id ? 1 : 2);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const linkedinConnected = !!user?.linkedin_status;
  const xConnected = !!user?.x_status;

  // LinkedIn is mandatory: the agreement step is unreachable without it. Step
  // 2's Continue is disabled too; this guard catches any other path (stale
  // state, a disconnect in another tab) that would land on step 3 unconnected.
  useEffect(() => {
    if (step === 3 && !linkedinConnected) setStep(2);
  }, [step, linkedinConnected]);

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

  const selectedTeam =
    teams.find((t) => t.id === selected) ?? null;

  // Persist the team before the LinkedIn hop so the choice survives the OAuth
  // redirect, then advance to the connect step.
  const saveTeamAndContinue = async () => {
    if (!selected) return;
    setSaving(true);
    setError(null);
    try {
      if (selected !== user?.team_id) {
        await apiFetch("/v1/users/me", {
          method: "PATCH",
          body: JSON.stringify({ team_id: selected }),
        });
        await refresh();
      }
      setStep(2);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your team");
    } finally {
      setSaving(false);
    }
  };

  const connect = async (platform: "linkedin" | "x") => {
    const label = platform === "x" ? "X" : "LinkedIn";
    setConnecting(true);
    setError(null);
    try {
      sessionStorage.setItem(ONBOARDING_RETURN_KEY, "1");
      const { authorize_url } = await apiFetch<{ authorize_url: string }>(
        `/v1/connections/${platform}/authorize`,
      );
      window.location.href = authorize_url;
    } catch (err) {
      sessionStorage.removeItem(ONBOARDING_RETURN_KEY);
      setError(
        err instanceof ApiError
          ? err.message
          : `Could not start ${label} connect. Please try again.`,
      );
      setConnecting(false);
    }
  };

  const finish = () => {
    navigate("/app", { replace: true });
  };

  return (
    <div className="flex min-h-screen flex-col items-center bg-paper px-4 py-16 text-ink">
      <div className="w-full max-w-lg">
        <Wordmark className="text-xl" />

        <div className="mt-6 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-ink">
          <span className={cn(step === 1 && "text-ink")}>1. Your team</span>
          <span className="text-border">/</span>
          <span className={cn(step === 2 && "text-ink")}>2. Connect accounts</span>
          <span className="text-border">/</span>
          <span className={cn(step === 3 && "text-ink")}>3. Join in</span>
        </div>

        {error && (
          <div className="mt-4 rounded-md border border-fail/20 bg-fail/5 px-4 py-2 text-sm text-fail">
            {error}
          </div>
        )}

        {step === 1 && (
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
              onClick={saveTeamAndContinue}
              disabled={!selected || saving}
              className="mt-8 inline-flex items-center gap-2 rounded-md bg-clay px-5 py-2.5 text-sm font-medium text-paper hover:bg-clay-press disabled:opacity-50"
            >
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              Continue
            </button>
          </>
        )}

        {step === 2 && (
          <>
            <div className="mt-6 flex h-14 w-14 items-center justify-center rounded-full bg-clay/10">
              <Link2 className="h-7 w-7 text-clay" />
            </div>
            <h1 className="mt-4 font-serif text-2xl text-ink">
              Connect your accounts
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-muted-ink">
              Super-hype publishes and engages through your own accounts, so you
              need to connect LinkedIn to take part. X is optional; connect it
              too if your team runs campaigns there. Nothing ever goes out until
              you approve it.
            </p>

            <div className="mt-6 space-y-2">
              <ConnectRow
                label="LinkedIn"
                logo={<LinkedInLogo />}
                logoBg="bg-[#0A66C2]/10"
                required
                connected={linkedinConnected}
                connecting={connecting}
                onConnect={() => connect("linkedin")}
              />
              <ConnectRow
                label="X (Twitter)"
                logo={<XLogo />}
                logoBg="bg-ink/10"
                connected={xConnected}
                connecting={connecting}
                onConnect={() => connect("x")}
              />
            </div>

            <div className="mt-8 flex items-center gap-3">
              <button
                onClick={() => setStep(1)}
                disabled={connecting}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-4 py-2.5 text-sm text-muted-ink hover:bg-sand disabled:opacity-50"
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </button>
              <button
                onClick={() => setStep(3)}
                disabled={!linkedinConnected || connecting}
                title={
                  linkedinConnected
                    ? undefined
                    : "Connect LinkedIn to continue"
                }
                className="inline-flex items-center gap-2 rounded-md bg-clay px-5 py-2.5 text-sm font-medium text-paper hover:bg-clay-press disabled:opacity-50"
              >
                Continue
              </button>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <div className="mt-6 flex h-14 w-14 items-center justify-center rounded-full bg-clay/10">
              <Rocket className="h-7 w-7 text-clay" />
            </div>
            <h1 className="mt-4 font-serif text-2xl text-ink">
              Become a TrueHyper
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-muted-ink">
              You are joining the{" "}
              <span className="font-medium text-ink">
                {selectedTeam?.name ?? user?.team_name ?? "your team"}
              </span>{" "}
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
                onClick={() => setStep(2)}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-4 py-2.5 text-sm text-muted-ink hover:bg-sand"
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </button>
              <button
                onClick={finish}
                className="inline-flex items-center gap-2 rounded-md bg-clay px-5 py-2.5 text-sm font-medium text-paper hover:bg-clay-press"
              >
                I am in. Let's hype.
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// One platform row on the connect step: LinkedIn is required to take part,
// X is optional and can also be connected later from the Connectors page.
function ConnectRow({
  label,
  logo,
  logoBg,
  required = false,
  connected,
  connecting,
  onConnect,
}: {
  label: string;
  logo: React.ReactNode;
  logoBg: string;
  required?: boolean;
  connected: boolean;
  connecting: boolean;
  onConnect: () => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-border px-4 py-3">
      <div className="flex items-center gap-3">
        <span
          className={`flex h-9 w-9 items-center justify-center rounded-full text-ink ${logoBg}`}
        >
          {logo}
        </span>
        <div>
          <p className="text-sm font-medium text-ink">{label}</p>
          <p className="text-xs text-muted-ink">
            {required ? "Required" : "Optional, you can connect it later"}
          </p>
        </div>
      </div>
      {connected ? (
        <span className="inline-flex items-center gap-1.5 rounded-md bg-ok/10 px-3 py-1.5 text-xs font-medium text-ok">
          <Check className="h-3.5 w-3.5" />
          Connected
        </span>
      ) : (
        <button
          onClick={onConnect}
          disabled={connecting}
          className="inline-flex items-center gap-1.5 rounded-md bg-clay px-3 py-1.5 text-xs font-medium text-paper hover:bg-clay-press disabled:opacity-50"
        >
          {connecting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Link2 className="h-3.5 w-3.5" />
          )}
          Connect
        </button>
      )}
    </div>
  );
}
