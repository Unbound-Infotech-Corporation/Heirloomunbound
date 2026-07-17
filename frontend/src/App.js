import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import "@/App.css";
import { AuthProvider } from "@/lib/auth";
import { AuthCallback, ProtectedRoute } from "@/components/Auth";
import AppLayout from "@/components/AppLayout";
import PageLoader from "@/components/PageLoader";
import { Toaster } from "sonner";

// Eager: first-paint public surfaces (landing + login + auth callback path).
import Landing from "@/pages/Landing";
import Login from "@/pages/Login";

// Lazy: everything else — keeps the initial JS bundle lean.
const TesterEntry = lazy(() => import("@/pages/TesterEntry"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Interviewer = lazy(() => import("@/pages/Interviewer"));
const Journal = lazy(() => import("@/pages/Journal"));
const Library = lazy(() => import("@/pages/Library"));
const Photos = lazy(() => import("@/pages/Photos"));
const Import = lazy(() => import("@/pages/Import"));
const Twin = lazy(() => import("@/pages/Twin"));
const TwinLive = lazy(() => import("@/pages/TwinLive"));
const AvatarStudio = lazy(() => import("@/pages/AvatarStudio"));
const SetupKeys = lazy(() => import("@/pages/SetupKeys"));
const Skills = lazy(() => import("@/pages/Skills"));
const Abilities = lazy(() => import("@/pages/Abilities"));
const PhotoStory = lazy(() => import("@/pages/PhotoStory"));
const Companion = lazy(() => import("@/pages/Companion"));
const Heirs = lazy(() => import("@/pages/Heirs"));
const HeirPortal = lazy(() => import("@/pages/HeirPortal"));
const Letters = lazy(() => import("@/pages/Letters"));
const MagicLink = lazy(() => import("@/pages/MagicLink"));
const Personality = lazy(() => import("@/pages/Personality"));
const Buy = lazy(() => import("@/pages/Buy"));
const BuySuccess = lazy(() => import("@/pages/BuySuccess"));
const Today = lazy(() => import("@/pages/Today"));
const Reminders = lazy(() => import("@/pages/Reminders"));
const Onboarding = lazy(() => import("@/pages/Onboarding"));
const Sources = lazy(() => import("@/pages/Sources"));
const Settings = lazy(() => import("@/pages/Settings"));
const Privacy = lazy(() => import("@/pages/Privacy"));
const Terms = lazy(() => import("@/pages/Terms"));
const Refunds = lazy(() => import("@/pages/Refunds"));
const Support = lazy(() => import("@/pages/Support"));

function AppRouter() {
  const location = useLocation();
  // CRITICAL: handle OAuth fragment BEFORE other routes / auth checks
  if (location.hash?.includes("session_id=")) return <AuthCallback />;

  return (
    <Suspense fallback={<PageLoader />}>
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
          <Route path="/photo-story" element={<PhotoStory />} />
          <Route path="/companion" element={<Companion />} />
          <Route path="/heirs" element={<Heirs />} />
          <Route path="/letters" element={<Letters />} />
          <Route path="/personality" element={<Personality />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/avatar-studio" element={<AvatarStudio />} />
          <Route path="/setup/keys" element={<SetupKeys />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
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
