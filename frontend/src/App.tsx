import { Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AuthCallback } from "@/pages/AuthCallback";
import { CampaignDetail } from "@/pages/CampaignDetail";
import { CampaignEditor } from "@/pages/CampaignEditor";
import { Campaigns } from "@/pages/Campaigns";
import { Connections } from "@/pages/Connections";
import { ContentRules } from "@/pages/ContentRules";
import { Events } from "@/pages/Events";
import { Landing } from "@/pages/Landing";
import { Leaderboard } from "@/pages/Leaderboard";
import { LinkedInCallback } from "@/pages/LinkedInCallback";
import { Onboarding } from "@/pages/Onboarding";
import { Profile } from "@/pages/Profile";
import { Teams } from "@/pages/Teams";
import { Users } from "@/pages/Users";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/v1/google/callback" element={<AuthCallback />} />
        <Route path="/app" element={<Navigate to="/app/campaigns" replace />} />
        <Route
          path="/app/campaigns"
          element={
            <ProtectedRoute>
              <Campaigns />
            </ProtectedRoute>
          }
        />
        <Route
          path="/app/campaigns/new"
          element={
            <ProtectedRoute>
              <CampaignEditor />
            </ProtectedRoute>
          }
        />
        <Route
          path="/app/campaigns/:id"
          element={
            <ProtectedRoute>
              <CampaignDetail />
            </ProtectedRoute>
          }
        />
        <Route
          path="/app/campaigns/:id/edit"
          element={
            <ProtectedRoute>
              <CampaignEditor />
            </ProtectedRoute>
          }
        />
        <Route
          path="/connections/linkedin/callback"
          element={
            <ProtectedRoute>
              <LinkedInCallback />
            </ProtectedRoute>
          }
        />
        <Route
          path="/app/connections"
          element={
            <ProtectedRoute>
              <Connections />
            </ProtectedRoute>
          }
        />
        <Route
          path="/app/users"
          element={
            <ProtectedRoute>
              <Users />
            </ProtectedRoute>
          }
        />
        <Route
          path="/app/onboarding"
          element={
            <ProtectedRoute>
              <Onboarding />
            </ProtectedRoute>
          }
        />
        <Route
          path="/app/profile"
          element={
            <ProtectedRoute>
              <Profile />
            </ProtectedRoute>
          }
        />
        <Route
          path="/app/teams"
          element={
            <ProtectedRoute>
              <Teams />
            </ProtectedRoute>
          }
        />
        <Route
          path="/app/leaderboard"
          element={
            <ProtectedRoute>
              <Leaderboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/app/content-rules"
          element={
            <ProtectedRoute>
              <ContentRules />
            </ProtectedRoute>
          }
        />
        <Route
          path="/app/events"
          element={
            <ProtectedRoute>
              <Events />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
