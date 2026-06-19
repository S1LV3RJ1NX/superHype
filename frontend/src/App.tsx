import { Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AuthCallback } from "@/pages/AuthCallback";
import { Connections } from "@/pages/Connections";
import { Dashboard } from "@/pages/Dashboard";
import { Landing } from "@/pages/Landing";
import { LinkedInCallback } from "@/pages/LinkedInCallback";
import { Placeholder } from "@/pages/Placeholder";
import { Skills } from "@/pages/Skills";
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
          path="/app/compose"
          element={
            <ProtectedRoute>
              <Placeholder title="Compose" phase={4} />
            </ProtectedRoute>
          }
        />
        <Route
          path="/app/skills"
          element={
            <ProtectedRoute>
              <Skills />
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
