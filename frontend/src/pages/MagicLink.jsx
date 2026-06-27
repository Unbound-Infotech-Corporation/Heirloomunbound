import axios from "axios";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND}/api`;

export default function MagicLink() {
  const { token } = useParams();
  const nav = useNavigate();
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!token) {
      setErr("Missing magic-link token.");
      return;
    }
    axios
      .post(`${API}/auth/magic/${token}`, {}, { withCredentials: true })
      .then(({ data }) => {
        // Store session_token also in localStorage for the SPA's Bearer fallback
        if (data.session_token) {
          localStorage.setItem("session_token", data.session_token);
        }
        nav("/today");
      })
      .catch((e) =>
        setErr(e.response?.data?.detail || "This magic-link is invalid or expired.")
      );
  }, [token, nav]);

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
