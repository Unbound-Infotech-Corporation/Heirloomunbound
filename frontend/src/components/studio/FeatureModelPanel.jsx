import { useState } from "react";
import { Check, Eye, EyeOff, Loader2, ShieldCheck, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "../../lib/api";
import StudioFieldRow from "./StudioFieldRow";
import StudioPanel from "./StudioPanel";

const LOCAL_BACKENDS = new Set(["local_whisper", "local_piper", "ollama", "auto"]);

/**
 * One feature window: backend dropdown, inline credential (only when needed),
 * provision + test — no grouped keys wizard.
 */
export default function FeatureModelPanel({ feature, onRefresh }) {
  const [keyDraft, setKeyDraft] = useState("");
  const [reveal, setReveal] = useState(false);
  const [busy, setBusy] = useState(null);
  const [testResult, setTestResult] = useState(null);

  if (!feature) return null;

  const status = feature.status || {};
  const selected = feature.selected;
  const cred = status.credential;
  const selectedBackend = (feature.backends || []).find((b) => b.id === selected);
  const needsLocal =
    LOCAL_BACKENDS.has(selected) &&
    ["stt", "tts", "twin", "vision"].includes(feature.id);

  const setBackend = async (backend) => {
    setBusy("backend");
    setTestResult(null);
    try {
      await api.patch(`/studio/models/${feature.id}`, { backend });
      toast.success(`${feature.label}: backend saved`);
      await onRefresh?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not save backend");
    } finally {
      setBusy(null);
    }
  };

  const runTest = async () => {
    setBusy("test");
    try {
      const { data } = await api.post(`/studio/models/${feature.id}/test`);
      setTestResult(data);
      if (data.ok) toast.success(data.detail || "Ready");
      else toast.error(data.detail || "Not ready yet");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Test failed");
    } finally {
      setBusy(null);
    }
  };

  const provisionOne = async () => {
    setBusy("provision");
    try {
      const { data } = await api.post(`/studio/models/${feature.id}/provision`);
      toast.success(data.hint || "Queued on dedicated PC");
      setTimeout(() => onRefresh?.(), 4000);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Provision failed");
    } finally {
      setBusy(null);
    }
  };

  const verifyKey = async () => {
    if (!cred?.verify_service || !keyDraft.trim()) {
      toast.error("Paste a key first");
      return;
    }
    setBusy("verify");
    try {
      const { data } = await api.post("/user-keys/verify", {
        service: cred.verify_service,
        api_key: keyDraft.trim(),
      });
      if (data.ok) toast.success(data.detail);
      else toast.error(data.detail);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Verify failed");
    } finally {
      setBusy(null);
    }
  };

  const saveKey = async () => {
    if (!cred?.save_path || !keyDraft.trim()) {
      toast.error("Paste a key first");
      return;
    }
    setBusy("save-key");
    try {
      await api.put(cred.save_path, { api_key: keyDraft.trim() });
      toast.success(`${cred.label} saved for ${feature.label} only`);
      setKeyDraft("");
      await onRefresh?.();
      await runTest();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Save failed");
    } finally {
      setBusy(null);
    }
  };

  const clearKey = async () => {
    if (!cred?.save_path) return;
    setBusy("save-key");
    try {
      await api.delete(cred.save_path);
      toast.success("Key removed");
      await onRefresh?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Remove failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div data-testid={`feature-panel-${feature.id}`}>
      <div
        className={`studio-feature-status ${status.ready ? "is-ready" : "is-pending"}`}
        data-testid={`feature-status-${feature.id}`}
      >
        <span className="studio-feature-status-dot" />
        <span>
          {status.ready ? "Ready" : "Not ready"} — runs as{" "}
          <strong className="studio-value">{status.effective || selected}</strong>
        </span>
        {status.detail ? <span className="studio-feature-status-detail">{status.detail}</span> : null}
      </div>

      <p className="text-xs mb-4 mt-3" style={{ color: "#888", lineHeight: 1.5 }}>
        {feature.purpose}
        {feature.local_artifact ? (
          <>
            {" "}
            · local: <span className="studio-value">{feature.local_artifact}</span>
          </>
        ) : null}
      </p>

      <StudioFieldRow label="Engine" hint={selectedBackend?.detail}>
        <select
          data-testid={`models-select-${feature.id}`}
          value={selected}
          disabled={busy === "backend"}
          onChange={(e) => setBackend(e.target.value)}
        >
          {(feature.backends || []).map((b) => (
            <option key={b.id} value={b.id} disabled={!b.available && b.id !== "auto"}>
              {b.label}
              {!b.available && b.id !== "auto" ? " (unavailable)" : ""}
            </option>
          ))}
        </select>
      </StudioFieldRow>

      {cred ? (
        <StudioPanel title={cred.label} defaultOpen={!cred.configured} testId={`feature-key-${feature.id}`}>
          <p className="text-xs mb-3" style={{ color: "#777", lineHeight: 1.4 }}>
            {cred.help}
          </p>
          <div className="studio-key-badge-row mb-3">
            <span
              className={`studio-key-badge ${cred.configured ? "is-ok" : "is-missing"}`}
              data-testid={`feature-key-status-${feature.id}`}
            >
              {cred.configured
                ? cred.source === "you"
                  ? "Your key saved"
                  : "Using shared default"
                : "No key yet"}
            </span>
          </div>
          <div className="studio-key-inline">
            <div className="relative flex-1">
              <input
                type={reveal ? "text" : "password"}
                value={keyDraft}
                onChange={(e) => setKeyDraft(e.target.value)}
                placeholder={cred.placeholder}
                data-testid={`feature-key-input-${feature.id}`}
                className="studio-key-input"
              />
              <button
                type="button"
                className="studio-key-reveal"
                onClick={() => setReveal((v) => !v)}
                aria-label={reveal ? "Hide key" : "Show key"}
              >
                {reveal ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              </button>
            </div>
            <button
              type="button"
              className="studio-btn"
              disabled={!keyDraft.trim() || busy === "verify"}
              onClick={verifyKey}
              data-testid={`feature-key-verify-${feature.id}`}
            >
              {busy === "verify" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
              Verify
            </button>
            <button
              type="button"
              className="studio-btn-primary"
              disabled={!keyDraft.trim() || busy === "save-key"}
              onClick={saveKey}
              data-testid={`feature-key-save-${feature.id}`}
            >
              {busy === "save-key" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              Save
            </button>
            {cred.configured && cred.source === "you" ? (
              <button type="button" className="studio-btn" onClick={clearKey} title="Remove key">
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
        </StudioPanel>
      ) : null}

      <div className="studio-feature-actions mt-4">
        <button
          type="button"
          className="studio-btn-primary"
          disabled={!!busy}
          onClick={runTest}
          data-testid={`feature-test-${feature.id}`}
        >
          {busy === "test" ? "Testing…" : "Test this feature"}
        </button>
        {needsLocal ? (
          <button
            type="button"
            className="studio-btn"
            disabled={!!busy}
            onClick={provisionOne}
            data-testid={`feature-provision-${feature.id}`}
          >
            {busy === "provision" ? "Queuing…" : "Provision on dedicated PC"}
          </button>
        ) : null}
      </div>

      {testResult ? (
        <div
          className={`studio-test-result ${testResult.ok ? "is-ok" : "is-fail"}`}
          data-testid={`feature-test-result-${feature.id}`}
        >
          {testResult.ok ? "✓" : "✗"} {testResult.detail}
        </div>
      ) : null}
    </div>
  );
}
