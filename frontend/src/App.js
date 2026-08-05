import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import "@/App.css";
import { AuthProvider } from "@/lib/auth";
import { AuthCallback, ProtectedRoute } from "@/components/Auth";
import AppLayout from "@/components/AppLayout";
import Landing from "@/pages/Landing";
import Login from "@/pages/Login";
import TesterEntry from "@/pages/TesterEntry";
import Dashboard from "@/pages/Dashboard";
import Interviewer from "@/pages/Interviewer";
import Journal from "@/pages/Journal";
import Library from "@/pages/Library";
import Photos from "@/pages/Photos";
import Import from "@/pages/Import";
import Twin from "@/pages/Twin";
import TwinLive from "@/pages/TwinLive";
import AvatarStudio from "@/pages/AvatarStudio";
import SetupKeys from "@/pages/SetupKeys";
import Skills from "@/pages/Skills";
import Abilities from "@/pages/Abilities";
import Agent from "@/pages/Agent";
import PhonePage from "@/pages/Phone";
import PhotoStory from "@/pages/PhotoStory";
import Roadmap from "@/pages/Roadmap";
import Routing from "@/pages/Routing";
import MobileShell from "@/pages/mobile/MobileShell";
import MobileCall from "@/pages/mobile/MobileCall";
import MobileCapture from "@/pages/mobile/MobileCapture";
import MobileHistory from "@/pages/mobile/MobileHistory";
import Companion from "@/pages/Companion";
import Heirs from "@/pages/Heirs";
import HeirPortal from "@/pages/HeirPortal";
import Letters from "@/pages/Letters";
import MagicLink from "@/pages/MagicLink";
import Personality from "@/pages/Personality";
import Buy from "@/pages/Buy";
import BuySuccess from "@/pages/BuySuccess";
import Today from "@/pages/Today";
import Reminders from "@/pages/Reminders";
import Onboarding from "@/pages/Onboarding";
import Sources from "@/pages/Sources";
import Settings from "@/pages/Settings";
import Privacy from "@/pages/Privacy";
import Terms from "@/pages/Terms";
import Refunds from "@/pages/Refunds";
import Support from "@/pages/Support";
import { Toaster } from "sonner";

function AppRouter() {
  const location = useLocation();
  // CRITICAL: handle OAuth fragment BEFORE other routes / auth checks
  if (location.hash?.includes("session_id=")) return <AuthCallback />;

  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/test" element={<TesterEntry />} />
      <Route path="/buy" element={<Buy />} />
      <Route path="/buy/success" element={<BuySuccess />} />
      <Route path="/privacy" element={<Privacy />} />
      <Route path="/terms" element={<Terms />} />
      <Route path="/refunds" element={<Refunds />} />
      <Route path="/support" element={<Support />} />
      <Route path="/roadmap" element={<Roadmap />} />
      <Route path="/auth/magic/:token" element={<MagicLink />} />
      <Route path="/heir/:token" element={<HeirPortal />} />
      <Route path="/twin/live/:handle" element={<TwinLive />} />
      <Route
        path="/onboarding"
        element={
          <ProtectedRoute>
            <Onboarding />
          </ProtectedRoute>
        }
      />
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
        <Route path="/sources" element={<Sources />} />
        <Route path="/interviewer" element={<Interviewer />} />
        <Route path="/journal" element={<Journal />} />
        <Route path="/library" element={<Library />} />
        <Route path="/photos" element={<Photos />} />
        <Route path="/import" element={<Import />} />
        <Route path="/twin" element={<Twin />} />
        <Route path="/skills" element={<Skills />} />
        <Route path="/abilities" element={<Abilities />} />
        <Route path="/agent" element={<Agent />} />
        <Route path="/phone" element={<PhonePage />} />
        <Route path="/photo-story" element={<PhotoStory />} />
        <Route path="/companion" element={<Companion />} />
        <Route path="/heirs" element={<Heirs />} />
        <Route path="/letters" element={<Letters />} />
        <Route path="/personality" element={<Personality />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/routing" element={<Routing />} />
        <Route path="/avatar-studio" element={<AvatarStudio />} />
        <Route path="/setup/keys" element={<SetupKeys />} />
      </Route>
      {/* Mobile PWA shell — protected but no AppLayout (its own bottom-tab UI). */}
      <Route
        path="/m"
        element={
          <ProtectedRoute>
            <MobileShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/m/call" replace />} />
        <Route path="call" element={<MobileCall />} />
        <Route path="capture" element={<MobileCapture />} />
        <Route path="history" element={<MobileHistory />} />
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
