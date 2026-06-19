import { Navigate, Route, Routes } from "react-router-dom";

import { Dashboard } from "@/pages/Dashboard";
import { Login } from "@/pages/Login";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/login" element={<Login />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
