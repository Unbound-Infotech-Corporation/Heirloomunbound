import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "../../lib/api";
import StudioFieldRow from "./StudioFieldRow";
import StudioPanel from "./StudioPanel";
import ModelBadge from "./ModelBadge";

const CATEGORIES = [
  { id: "code", label: "Code" },
  { id: "reasoning", label: "Reasoning" },
  { id: "research", label: "Research" },
  { id: "chat", label: "Quick chat" },
  { id: "vision", label: "Vision" },
];

function slotsToText(slots) {
  return (slots || []).map((slot) => `${slot.backend}/${slot.model}`).join("\n");
}

function textToSlots(text) {
  return String(text || "")
    .split(/[\n,;]+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 6)
    .map((line) => {
      const slash = line.indexOf("/");
      if (slash <= 0) return null;
      const backend = line.slice(0, slash).trim().toLowerCase();
      const model = line.slice(slash + 1).trim();
      if (!["ollama", "llamacpp", "cloud"].includes(backend) || !model || /\s/.test(model)) return null;
      return { backend, model };
    })
    .filter(Boolean);
}

export default function AssistRoutePanel({ router, onRefresh }) {
  const [picker, setPicker] = useState("auto");
  const [manualBackend, setManualBackend] = useState("ollama");
  const [manualModel, setManualModel] = useState("");
  const [opinion, setOpinion] = useState("auto");
  const [chains, setChains] = useState({});
  const [cloudOn, setCloudOn] = useState(false);
  const [cloudUrl, setCloudUrl] = useState("");
  const [cloudModel, setCloudModel] = useState("");
  const [cloudKey, setCloudKey] = useState("");
  const [previewText, setPreviewText] = useState("refactor the auth middleware");
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    if (!router) return;
    setPicker(router.picker || "auto");
    setManualBackend(router.manual_backend || "ollama");
    setManualModel(router.manual_model || "");
    setOpinion(router.second_opinion || "auto");
    const next = {};
    CATEGORIES.forEach((cat) => {
      next[cat.id] = slotsToText(router.routes?.[cat.id]);
    });
    setChains(next);
    setCloudOn(Boolean(router.cloud?.enabled));
    setCloudUrl(router.cloud?.base_url || "");
    setCloudModel(router.cloud?.model || "");
  }, [router]);

  const saveRoutes = async () => {
    setBusy("routes");
    try {
      const routes = {};
      CATEGORIES.forEach((cat) => {
        routes[cat.id] = textToSlots(chains[cat.id]);
      });
      await api.put("/studio/models/assist-routes", {
        picker,
        manual_backend: manualBackend,
        manual_model: manualModel.trim(),
        second_opinion: opinion,
        routes,
      });
      toast.success("Assist routing saved");
      await onRefresh?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not save Assist routing");
    } finally {
      setBusy("");
    }
  };

  const saveCloud = async () => {
    setBusy("cloud");
    try {
      const body = { enabled: cloudOn, base_url: cloudUrl.trim(), model: cloudModel.trim() };
      if (cloudKey.trim()) body.api_key = cloudKey.trim();
      await api.put("/studio/models/assist-cloud", body);
      setCloudKey("");
      toast.success("Cloud opt-in saved. The key stays on the server.");
      await onRefresh?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not save the cloud opt-in");
    } finally {
      setBusy("");
    }
  };

  const runPreview = async () => {
    setBusy("preview");
    setPreview(null);
    try {
      const { data } = await api.post("/studio/models/assist/preview", { text: previewText });
      setPreview(data);
    } catch (err) {
      const detail = err?.response?.data?.detail || err.message;
      setPreview({ ok: false, badge: "", error: String(detail) });
    } finally {
      setBusy("");
    }
  };

  return (
    <div data-testid="assist-route-panel">
      <StudioPanel title="Task router" defaultOpen testId="assist-route-table">
        <p className="text-xs mb-3" style={{ color: "#888", lineHeight: 1.5 }}>
          Auto classifies each Do request and runs the first installed model in that row.
          A miss stays on the badge. Manual is one model and does not fall back.
          One slot per line: <span className="studio-value">backend/model</span>.
        </p>
        <p className="text-xs mb-3" data-testid="assist-route-readiness" style={{ color: router?.ready ? "#7da06f" : "#c95a5a" }}>
          {router?.detail || "Routing table not loaded."}
        </p>
        <StudioFieldRow label="Picker">
          <select data-testid="assist-picker" value={picker} onChange={(e) => setPicker(e.target.value)}>
            <option value="auto">Auto (router)</option>
            <option value="manual">Manual model</option>
          </select>
        </StudioFieldRow>
        <StudioFieldRow label="Manual backend">
          <select data-testid="assist-manual-backend" value={manualBackend} onChange={(e) => setManualBackend(e.target.value)}>
            <option value="ollama">ollama</option>
            <option value="llamacpp">llamacpp</option>
            <option value="cloud">cloud</option>
          </select>
        </StudioFieldRow>
        <StudioFieldRow label="Manual model">
          <input
            data-testid="assist-manual-model"
            value={manualModel}
            onChange={(e) => setManualModel(e.target.value)}
            placeholder="qwen2.5-coder:7b"
          />
        </StudioFieldRow>
        <StudioFieldRow label="Second opinion">
          <select data-testid="assist-second-opinion" value={opinion} onChange={(e) => setOpinion(e.target.value)}>
            <option value="auto">Auto — risky code only</option>
            <option value="always">Always on code</option>
            <option value="off">Off</option>
          </select>
        </StudioFieldRow>
        {CATEGORIES.map((cat) => (
          <StudioFieldRow key={cat.id} label={cat.label}>
            <textarea
              data-testid={`assist-chain-${cat.id}`}
              rows={cat.id === "code" ? 5 : 3}
              value={chains[cat.id] || ""}
              onChange={(e) => setChains((prev) => ({ ...prev, [cat.id]: e.target.value }))}
            />
          </StudioFieldRow>
        ))}
        <button type="button" className="studio-btn-primary" data-testid="assist-save-routes" disabled={!!busy} onClick={saveRoutes}>
          {busy === "routes" ? "Saving…" : "Save routing table"}
        </button>
      </StudioPanel>

      <StudioPanel title="Cloud opt-in" defaultOpen={false} testId="assist-cloud-panel">
        <p className="text-xs mb-3" style={{ color: "#888", lineHeight: 1.5 }}>
          Off until you turn it on, save a key, and put a cloud slot in a chain. The key is never sent back.
          {router?.cloud?.has_key ? " A key is already saved." : " No key saved."}
        </p>
        <StudioFieldRow label="Enabled">
          <input
            type="checkbox"
            data-testid="assist-cloud-enabled"
            checked={cloudOn}
            onChange={(e) => setCloudOn(e.target.checked)}
          />
        </StudioFieldRow>
        <StudioFieldRow label="Base URL">
          <input data-testid="assist-cloud-url" value={cloudUrl} onChange={(e) => setCloudUrl(e.target.value)} placeholder="https://host/v1" />
        </StudioFieldRow>
        <StudioFieldRow label="Model">
          <input data-testid="assist-cloud-model" value={cloudModel} onChange={(e) => setCloudModel(e.target.value)} placeholder="model-name" />
        </StudioFieldRow>
        <StudioFieldRow label="API key">
          <input
            type="password"
            data-testid="assist-cloud-key"
            value={cloudKey}
            onChange={(e) => setCloudKey(e.target.value)}
            placeholder={router?.cloud?.has_key ? "saved — type to replace" : "optional"}
          />
        </StudioFieldRow>
        <button type="button" className="studio-btn" data-testid="assist-save-cloud" disabled={!!busy} onClick={saveCloud}>
          {busy === "cloud" ? "Saving…" : "Save cloud opt-in"}
        </button>
      </StudioPanel>

      <StudioPanel title="Preview" defaultOpen testId="assist-preview-panel">
        <StudioFieldRow label="Sample request">
          <input data-testid="assist-preview-text" value={previewText} onChange={(e) => setPreviewText(e.target.value)} />
        </StudioFieldRow>
        <button type="button" className="studio-btn" data-testid="assist-preview" disabled={!!busy || !previewText.trim()} onClick={runPreview}>
          {busy === "preview" ? "Checking…" : "Preview model"}
        </button>
        {preview ? (
          <div className="mt-3" data-testid="assist-preview-result">
            {preview.badge ? <ModelBadge badge={preview.badge} /> : null}
            {preview.error ? <p className="text-xs mt-2" style={{ color: "#c95a5a" }}>{preview.error}</p> : null}
          </div>
        ) : null}
      </StudioPanel>
    </div>
  );
}
