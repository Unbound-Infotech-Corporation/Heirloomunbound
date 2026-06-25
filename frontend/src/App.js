import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import "@/App.css";
import { AuthProvider } from "@/lib/auth";
import { AuthCallback, ProtectedRoute } from "@/components/Auth";
import AppLayout from "@/components/AppLayout";
import Landing from "@/pages/Landing";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Interviewer from "@/pages/Interviewer";
import Journal from "@/pages/Journal";
import Library from "@/pages/Library";
import Photos from "@/pages/Photos";
import Import from "@/pages/Import";
import Twin from "@/pages/Twin";
import Skills from "@/pages/Skills";
import Companion from "@/pages/Companion";
import Heirs from "@/pages/Heirs";
import Today from "@/pages/Today";
import Reminders from "@/pages/Reminders";
import Settings from "@/pages/Settings";
import { Toaster } from "sonner";

function AppRouter() {
  const location = useLocation();
  // CRITICAL: handle OAuth fragment BEFORE other routes / auth checks
  if (location.hash?.includes("session_id=")) return <AuthCallback />;

  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/today" element={<Today />} />
        <Route path="/reminders" element={<Reminders />} />
        <Route path="/interviewer" element={<Interviewer />} />
        <Route path="/journal" element={<Journal />} />
        <Route path="/library" element={<Library />} />
        <Route path="/photos" element={<Photos />} />
        <Route path="/import" element={<Import />} />
        <Route path="/twin" element={<Twin />} />
        <Route path="/skills" element={<Skills />} />
        <Route path="/companion" element={<Companion />} />
        <Route path="/heirs" element={<Heirs />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <AuthProvider>
          <AppRouter />
          <Toaster position="bottom-right" theme="dark" />
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}
