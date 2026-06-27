import axios from "axios";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { CheckCircle2, Download, Loader2, Sparkles } from "lucide-react";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND}/api`;
const POLL_INTERVAL_MS = 2500;
const MAX_POLLS = 24;  // 1 minute

export default function BuySuccess() {
  const [params] = useSearchParams();
  const sessionId = params.get("session_id");
  const nav = useNavigate();
  const [status, setStatus] = useState("checking"); // checking | paid | failed | timeout
  const [info, setInfo] = useState(null);
  const pollsRef = useRef(0);

  useEffect(() => {
    if (!sessionId) {
      setStatus("failed");
      return;
    }

    let cancelled = false;
    const poll = async () => {
      if (cancelled) return;
      try {
        const { data } = await axios.get(`${API}/billing/status/${sessionId}`);
        if (data.paid) {
          setInfo(data);
          setStatus("paid");
          return;
        }
        if (data.status === "expired" || data.payment_status === "failed") {
          setStatus("failed");
          return;
        }
      } catch (e) {
        // network blip — keep trying
      }
      pollsRef.current += 1;
      if (pollsRef.current >= MAX_POLLS) {
        setStatus("timeout");
        return;
      }
      setTimeout(poll, POLL_INTERVAL_MS);
    };
    poll();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (status === "checking") {
    return (
      <div className="min-h-screen flex items-center justify-center flex-col gap-4" style={{ background: "var(--bg-base)" }} data-testid="success-checking">
        <Loader2 className="h-6 w-6 animate-spin" style={{ color: "var(--accent)" }} />
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Confirming your payment with Stripe…
        </p>
      </div>
    );
  }

  if (status === "failed" || status === "timeout") {
    return (
      <div className="min-h-screen flex items-center justify-center px-6" style={{ background: "var(--bg-base)" }} data-testid="success-failed">
        <div className="max-w-md text-center">
          <div className="overline mb-3">heirloom</div>
          <h1 className="font-serif text-3xl mb-3">
            {status === "timeout" ? "Still confirming…" : "Payment didn't go through."}
          </h1>
          <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
            {status === "timeout"
              ? "Stripe is taking longer than usual. Refresh in a minute, or check your email for a confirmation."
              : "No charge was made. Try again or contact support@unboundinfotech.com."}
          </p>
          <button
            onClick={() => nav("/buy")}
            data-testid="success-retry"
            className="px-5 py-3 text-sm rounded-sm"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            Back to checkout
          </button>
        </div>
      </div>
    );
  }

  // PAID
  const downloadUrl = info?.download_url ? `${BACKEND}${info.download_url}` : null;
  const loginUrl = info?.login_url ? `${window.location.origin}${info.login_url}` : null;

  return (
    <div className="min-h-screen flex items-center justify-center px-6 py-16" style={{ background: "var(--bg-base)" }} data-testid="success-paid">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-2xl"
      >
        <CheckCircle2 className="h-10 w-10 mb-5" style={{ color: "var(--accent)" }} />
        <div className="overline mb-2">payment received</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight mb-3">
          Welcome to Heirloom.
        </h1>
        <p className="text-base mb-10" style={{ color: "var(--text-secondary)" }}>
          We've created your account ({info?.email || "your email"}) and generated a personalized Windows installer with your device token baked in.
        </p>

        <div className="space-y-5">
          <a
            href={downloadUrl || "#"}
            download
            data-testid="success-download"
            className="block surface p-6 transition-colors"
            style={{ borderLeft: "3px solid var(--accent)" }}
          >
            <div className="flex justify-between items-center">
              <div>
                <div className="overline mb-2">step 1</div>
                <h3 className="font-serif text-2xl mb-1">Download your installer</h3>
                <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                  HeirloomCompanion-Windows.zip · double-click Heirloom.bat inside it. Link works for 14 days, up to 5 downloads.
                </p>
              </div>
              <Download className="h-7 w-7" style={{ color: "var(--accent)" }} />
            </div>
          </a>

          <a
            href={loginUrl || "#"}
            data-testid="success-login"
            className="block surface p-6 transition-colors"
            style={{ borderLeft: "3px solid var(--accent)" }}
          >
            <div className="flex justify-between items-center">
              <div>
                <div className="overline mb-2">step 2</div>
                <h3 className="font-serif text-2xl mb-1">Open your private archive</h3>
                <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                  Magic-link login — no password needed. This link is single-use; it'll create your session and bring you to Today.
                </p>
              </div>
              <Sparkles className="h-7 w-7" style={{ color: "var(--accent)" }} />
            </div>
          </a>
        </div>

        <p className="text-xs italic mt-10" style={{ color: "var(--text-muted)" }}>
          Save this page — these two links won't be emailed (yet). The magic-link works for 24 hours. The download works for 14 days.
        </p>
      </motion.div>
    </div>
  );
}
