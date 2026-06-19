import { Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AuthCallback } from "@/pages/AuthCallback";
import { Dashboard } from "@/pages/Dashboard";
import { Landing } from "@/pages/Landing";
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
