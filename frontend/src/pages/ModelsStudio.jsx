import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";
import {
  FeatureModelPanel,
  StudioPanel,
  StudioTabs,
  StudioWorkspace,
} from "../components/studio";

export default function ModelsStudio() {
  const [catalog, setCatalog] = useState(null);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState("");
  const [activeTab, setActiveTab] = useState("stt");

  const load = useCallback(async () => {
    const { data } = await api.get("/studio/models");
    setCatalog(data);
    return data;
  }, []);

  useEffect(() => {
    load().catch(() => toast.error("Could not load model catalog"));
  }, [load]);

  const provisionAll = async () => {
    setBusy(true);
    setLog("Queuing provision on the dedicated PC…");
    try {
      const { data } = await api.post("/studio/models/provision", {});
      setLog(
        `${data.hint}\nQueued: ${(data.features || []).join(", ") || "auto"}\ncmd ${data.cmd_id}`
      );
      toast.success("Provision queued");
      setTimeout(() => load(), 4000);
    } catch (err) {
      const detail = err?.response?.data?.detail || err.message;
      setLog(String(detail));
      toast.error(detail);
    } finally {
      setBusy(false);
    }
  };

  if (!catalog) {
    return (
      <div className="px-6 py-10" data-testid="models-loading">
        Loading models…
      </div>
    );
  }

  const companion = catalog.companion || {};
  const features = catalog.features || [];
  const readyCount = features.filter((f) => f.status?.ready).length;

  const featureTabs = features.map((feat) => ({
    id: feat.id,
    label: feat.label,
    testId: `models-tab-${feat.id}`,
    content: <FeatureModelPanel feature={feat} onRefresh={load} />,
  }));

  const activeFeature = features.find((f) => f.id === activeTab) || features[0];

  return (
    <div data-testid="models-root">
      <div className="studio-options-bar" data-testid="models-options-bar">
        <label className="studio-opt-group">
          Feature
          <select
            value={activeTab}
            onChange={(e) => setActiveTab(e.target.value)}
            data-testid="models-feature-picker"
          >
            {features.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
                {f.status?.ready ? " ✓" : ""}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="studio-btn"
          data-testid="models-provision-opt"
          disabled={busy}
          onClick={provisionAll}
        >
          {busy ? "Queuing…" : "Provision all local"}
        </button>
        <button type="button" className="studio-btn" onClick={() => load()}>
          Refresh
        </button>
        <span className="ml-auto" style={{ color: companion.connected ? "#7da06f" : "#c95a5a" }}>
          {companion.connected ? companion.name || "PC online" : "Dedicated PC offline"}
          {!catalog.hosted_llm ? " · no hosted cloud fallback" : ""}
        </span>
      </div>

      <StudioWorkspace
        testId="models-workspace"
        inspectorWidth={300}
        inspector={
          <>
            <StudioPanel title="Dedicated PC" testId="models-probe" defaultOpen>
              <dl className="studio-dl" style={{ fontSize: 11 }}>
                <dt>Status</dt>
                <dd className="studio-value">
                  {companion.connected ? companion.name || "online" : "not connected"}
                </dd>
                <dt>GPU</dt>
                <dd>{companion.gpu?.detail || "—"}</dd>
                <dt>Ollama</dt>
                <dd>{companion.ollama?.detail || "—"}</dd>
                <dt>Whisper</dt>
                <dd>{companion.whisper?.detail || "—"}</dd>
                <dt>Piper</dt>
                <dd>{companion.piper?.detail || "—"}</dd>
              </dl>
              <p className="text-xs mt-3" style={{ color: "#777", lineHeight: 1.4 }}>
                {companion.detail ||
                  "Local engines run on the machine in the other room. Cloud keys are optional fallbacks — configure them inside each feature tab, not on one shared page."}
              </p>
            </StudioPanel>

            {activeFeature ? (
              <StudioPanel title={`${activeFeature.label} summary`} defaultOpen>
                <p className="text-xs" style={{ color: "#aaa", lineHeight: 1.5 }}>
                  Selected: <span className="studio-value">{activeFeature.selected}</span>
                  <br />
                  Runs as: <span className="studio-value">{activeFeature.status?.effective}</span>
                </p>
              </StudioPanel>
            ) : null}
          </>
        }
        canvas={
          <div className="studio-canvas-hero" style={{ maxWidth: "100%" }}>
            <h1>Models — one window per feature</h1>
            <p>
              Pick an engine in the dropdown for each feature. If that engine needs a key, paste it
              right here — only for that feature. Use <strong>Test this feature</strong> to confirm
              it works before talking to your twin.
            </p>

            <div className="studio-probe-grid">
              {features.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  className={`studio-probe-card studio-probe-card-btn ${f.status?.ready ? "is-ready" : ""}`}
                  onClick={() => setActiveTab(f.id)}
                  data-testid={`models-card-${f.id}`}
                >
                  <dt>{f.label}</dt>
                  <dd>{f.status?.effective || f.selected}</dd>
                  <span className="studio-probe-card-state">{f.status?.ready ? "Ready" : "Setup"}</span>
                </button>
              ))}
            </div>

            {featureTabs.length > 0 ? (
              <div className="mt-6" style={{ border: "1px solid #111" }}>
                <StudioTabs
                  tabs={featureTabs}
                  defaultTab={activeTab}
                  activeTab={activeTab}
                  onTabChange={setActiveTab}
                  testId="models-tabs"
                />
              </div>
            ) : null}

            {log ? (
              <pre className="studio-log mt-4" data-testid="models-log">
                {log}
              </pre>
            ) : null}
          </div>
        }
        footer={
          <>
            <span>
              {readyCount}/{features.length} features ready
            </span>
            <span className="mx-2">·</span>
            <span>Keys live inside each feature tab</span>
          </>
        }
      />
    </div>
  );
}
