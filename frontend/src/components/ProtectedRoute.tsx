import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";

const ONBOARDING_PATH = "/app/onboarding";
// The OAuth returns land here to exchange the code; they must stay reachable
// mid-onboarding (the account is not connected yet at that point), otherwise
// the gate would bounce them to onboarding before the exchange runs.
const OAUTH_CALLBACK_PATHS = [
  "/connections/linkedin/callback",
  "/connections/x/callback",
];

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper">
        <p className="text-sm text-muted-ink">Loading...</p>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/" replace />;
  }

  // Onboarding is required: a user must pick a team and connect LinkedIn before
  // using the app (they publish and engage through their own account). The
  // onboarding route and the LinkedIn callback are exempt to avoid a loop.
  const onboarded = !!user.team_id && !!user.linkedin_status;
  const exempt =
    location.pathname === ONBOARDING_PATH ||
    OAUTH_CALLBACK_PATHS.includes(location.pathname);
  if (!onboarded && !exempt) {
    return <Navigate to={ONBOARDING_PATH} replace />;
  }

  return <>{children}</>;
}
