import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";

const ONBOARDING_PATH = "/app/onboarding";

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

  // First-login onboarding: a user without a team must pick one before using the
  // app. The onboarding route itself is exempt to avoid a redirect loop.
  if (!user.team_id && location.pathname !== ONBOARDING_PATH) {
    return <Navigate to={ONBOARDING_PATH} replace />;
  }

  // Once onboarded, the onboarding route has nothing to do; send them to the app.
  if (user.team_id && location.pathname === ONBOARDING_PATH) {
    return <Navigate to="/app" replace />;
  }

  return <>{children}</>;
}
