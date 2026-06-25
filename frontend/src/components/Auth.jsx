import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

export function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--bg-base)" }}>
        <div className="overline">verifying…</div>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

// AuthCallback: handles redirect from Emergent Auth (#session_id=...) -> exchanges for cookie -> dashboard
// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
import { useRef } from "react";

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
    if (!m) {
      navigate("/login", { replace: true });
      return;
    }
    const sessionId = decodeURIComponent(m[1]);

    api
      .post("/auth/session", { session_id: sessionId })
      .then(({ data }) => {
        setUser(data);
        // Strip the hash before navigating
        window.history.replaceState(null, "", window.location.pathname);
        navigate("/today", { replace: true, state: { user: data } });
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
            onClick={() => navigate("/login")}
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
