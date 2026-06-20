import { Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AuthCallback } from "@/pages/AuthCallback";
import { Connections } from "@/pages/Connections";
import { Dashboard } from "@/pages/Dashboard";
import { Landing } from "@/pages/Landing";
import { LinkedInCallback } from "@/pages/LinkedInCallback";
import { CampaignDetail } from "@/pages/CampaignDetail";
import { CampaignEditor } from "@/pages/CampaignEditor";
import { Campaigns } from "@/pages/Campaigns";
import { Users } from "@/pages/Users";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/v1/google/callback" element={<AuthCallback />} />
        <Route
          path="/app"
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          }
        />
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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
