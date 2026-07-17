import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { Loader2, Shield } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const BASE = `${BACKEND_URL}/api/executor-lock`;

export default function ExecutorPortal() {
  const { token } = useParams();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState("");
  const [docRef, setDocRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    axios
      .get(`${BASE}/public/${token}`)
      .then(({ data }) => setInfo(data))
      .catch((e) => setError(e.response?.data?.detail || "Invalid executor link."))
      .finally(() => setLoading(false));
  }, [token]);

  const submit = async () => {
    setBusy(true);
    setResult(null);
    try {
      const { data } = await axios.post(`${BASE}/public/${token}/attest`, {
        attestation_note: note,
        confirmation: confirm,
        document_reference: docRef,
      });
      setResult(data);
      setInfo((i) => (i ? { ...i, status: data.status, attested_at: data.attested_at } : i));
    } catch (e) {
      setResult({ error: e.response?.data?.detail || e.message });
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--bg-base)" }}>
        <Loader2 className="h-6 w-6 animate-spin" style={{ color: "var(--accent)" }} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center px-6" style={{ background: "var(--bg-base)" }}>
        <div className="max-w-md text-center">
          <div className="overline mb-3">executor lock</div>
          <h1 className="font-serif text-3xl mb-3">This link is inactive.</h1>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{error}</p>
        </div>
      </div>
    );
  }

  const locked = info?.status === "locked";
  const pending = info?.status === "pending";

  return (
    <div
      className="min-h-screen px-4 sm:px-8 py-12"
      style={{ background: "var(--bg-base)", paddingBottom: "max(3rem, env(safe-area-inset-bottom))" }}
      data-testid="executor-portal"
    >
      <div className="max-w-xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <Shield className="h-6 w-6" style={{ color: "var(--accent)" }} />
          <div className="overline">executor lock</div>
        </div>
        <h1 className="font-serif text-4xl font-light tracking-tight mb-3">
          Stewardship for {info.owner_name}
        </h1>
        <p className="text-sm mb-8" style={{ color: "var(--text-secondary)" }}>
          You are named as executor ({info.executor_name}). Attesting starts a {info.wait_hours}-hour
          waiting period. After that, the archive locks read-only and heirs are released.
        </p>

        <div className="surface p-6 mb-6 text-sm" style={{ color: "var(--text-secondary)" }}>
          <div>Status: <strong style={{ color: "var(--text-primary)" }}>{info.status}</strong></div>
          {info.attested_at && <div className="mt-1">Attested: {info.attested_at.slice(0, 16)}</div>}
          {info.locked_at && <div className="mt-1">Locked: {info.locked_at.slice(0, 16)}</div>}
        </div>

        {locked ? (
          <p className="font-serif text-xl">The archive is locked. Heirs have been released.</p>
        ) : pending ? (
          <p className="font-serif text-xl">
            Waiting period in progress. The owner can cancel until it completes.
          </p>
        ) : (
          <div className="surface p-6 space-y-4">
            <label className="block text-sm">
              <span className="overline mb-2 block">attestation note</span>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={4}
                data-testid="executor-note"
                className="w-full px-3 py-2 text-sm rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
                placeholder="Brief note on how death was verified…"
              />
            </label>
            <label className="block text-sm">
              <span className="overline mb-2 block">document reference (optional)</span>
              <input
                value={docRef}
                onChange={(e) => setDocRef(e.target.value)}
                data-testid="executor-doc-ref"
                className="w-full px-3 py-2 text-sm rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
                placeholder="Certificate # / attorney file"
              />
            </label>
            <label className="block text-sm">
              <span className="overline mb-2 block">type CONFIRM DEATH</span>
              <input
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                data-testid="executor-confirm"
                className="w-full px-3 py-2 text-sm rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              />
            </label>
            <button
              type="button"
              onClick={submit}
              disabled={busy || note.trim().length < 10 || confirm.trim().toUpperCase() !== "CONFIRM DEATH"}
              data-testid="executor-submit"
              className="px-5 py-3 text-sm rounded-sm disabled:opacity-50"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              {busy ? "Submitting…" : "Start waiting period"}
            </button>
          </div>
        )}

        {result && (
          <div className="mt-6 text-sm surface p-4" data-testid="executor-result">
            {result.error ? (
              <span style={{ color: "var(--danger, #c44)" }}>{result.error}</span>
            ) : (
              <span>{result.message || result.status}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
