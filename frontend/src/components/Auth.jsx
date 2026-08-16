import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

import { useRef } from "react";

export function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  const [onboarded, setOnboarded] = useState(null); // null=unknown, true/false=resolved

  useEffect(() => {
    if (!user) {
      setOnboarded(null);
      return;
    }
    // Skip the check when we're already on /onboarding
    if (location.pathname === "/onboarding") {
      setOnboarded(true);
      return;
    }
    api
      .get("/onboarding/state")
      .then(({ data }) => setOnboarded(Boolean(data.onboarded)))
      .catch(() => setOnboarded(true)); // fail open — don't trap on error
  }, [user, location.pathname]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--bg-base)" }}>
        <div className="overline">verifying…</div>
      </div>
    );
  }
  const onPhone = location.pathname.startsWith("/m");
  if (!user) return <Navigate to={onPhone ? "/m/login" : "/login"} replace />;
  if (onboarded === null) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--bg-base)" }}>
        <div className="overline">preparing your archive…</div>
      </div>
    );
  }
  // Phone app: let them talk to the twin after Google. Desktop still does onboarding.
  if (onboarded === false && location.pathname !== "/onboarding" && !onPhone) {
    return <Navigate to="/onboarding" replace />;
  }
  return children;
}

export function AuthCallback() {
  const navigate = useNavigate();
  const location = useLocation();
  const { setUser } = useAuth();
  const [error, setError] = useState(null);
  const hasProcessed = useRef(false);

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const hash = location.hash || window.location.hash;
    const m = hash.match(/session_id=([^&]+)/);
    const path = window.location.pathname || "";
    let markedPhone = false;
    try {
      markedPhone = sessionStorage.getItem("heirloom_after_google") === "phone";
    } catch {
      markedPhone = false;
    }
    const onPhone = path.startsWith("/m") || (markedPhone && path !== "/today");
    if (!m) {
      navigate(onPhone ? "/m/login" : "/login", { replace: true });
      return;
    }
    const sessionId = decodeURIComponent(m[1]);

    api
      .post("/auth/session", { session_id: sessionId })
      .then(({ data }) => {
        setUser(data);
        window.history.replaceState(null, "", window.location.pathname);
        try {
          sessionStorage.removeItem("heirloom_after_google");
        } catch {
          /* ignore */
        }
        // Phone Google returns to /m; the website login still goes to /today.
        navigate(onPhone ? "/m/twin" : "/today", { replace: true, state: { user: data } });
      })
      .catch((err) => {
        setError(err.message || "Auth failed");
      });
  }, [location.hash, navigate, setUser]);

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--bg-base)" }}>
      <div className="text-center">
        <div className="overline mb-3">authenticating</div>
        <div className="font-serif text-3xl" style={{ color: "var(--text-primary)" }}>
          {error ? "Something went wrong" : "Welcoming you home…"}
        </div>
        {error && (
          <button
            onClick={() =>
              navigate((window.location.pathname || "").startsWith("/m") ? "/m/login" : "/login")
            }
            data-testid="auth-retry-button"
            className="mt-6 px-5 py-2 text-sm"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
          >
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
