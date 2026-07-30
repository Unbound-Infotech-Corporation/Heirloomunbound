import axios from "axios";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useAuth } from "../lib/auth";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND}/api`;

export default function MagicLink() {
  const { token } = useParams();
  const nav = useNavigate();
  const { setUser, refresh } = useAuth();
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!token) {
      setErr("Missing magic-link token.");
      return;
    }
    axios
      .post(`${API}/auth/magic/${token}`, {}, { withCredentials: true })
      .then(async ({ data }) => {
        // Session is delivered via httpOnly cookie by the backend
        // (withCredentials above). Do NOT mirror it into localStorage — that
        // exposes the token to any XSS payload and buys nothing (no reader).
        // Hydrate the AuthProvider so /today renders authenticated on first paint
        if (data.user && setUser) {
          setUser(data.user);
        } else if (refresh) {
          await refresh();
        }
        nav("/today");
      })
      .catch((e) =>
        setErr(e.response?.data?.detail || "This magic-link is invalid or expired.")
      );
  }, [token, nav, setUser, refresh]);

  if (err) {
    return (
      <div
        className="min-h-screen flex items-center justify-center px-6"
        style={{ background: "var(--bg-base)" }}
        data-testid="magic-error"
      >
        <div className="max-w-md text-center">
          <div className="overline mb-3">heirloom</div>
          <h1 className="font-serif text-3xl mb-3">This link no longer works.</h1>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {err}
          </p>
          <button
            onClick={() => nav("/login")}
            className="mt-6 px-4 py-2 text-sm rounded-sm"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            Sign in another way
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center gap-3"
      style={{ background: "var(--bg-base)" }}
      data-testid="magic-loading"
    >
      <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--accent)" }} />
      <span className="text-sm" style={{ color: "var(--text-muted)" }}>
        Signing you in…
      </span>
    </div>
  );
}
