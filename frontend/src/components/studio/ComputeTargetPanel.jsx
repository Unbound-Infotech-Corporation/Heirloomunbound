import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "../../lib/api";
import StudioFieldRow from "./StudioFieldRow";
import StudioPanel from "./StudioPanel";

const MODES = [
  {
    id: "local",
    label: "This PC",
    hint: "Whisper, Piper, and Ollama on the dedicated machine that most recently checked in.",
  },
  {
    id: "network",
    label: "Network PC",
    hint: "Pick another registered Heirloom install on your LAN (e.g. the 5090 in the office).",
  },
  {
    id: "server",
    label: "Remote server",
    hint: "Ollama on a URL you control. Whisper/Piper still run on the selected PC.",
  },
];

export default function ComputeTargetPanel({ onSaved }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const { data: body } = await api.get("/studio/compute");
    setData(body);
    return body;
  }, []);

  useEffect(() => {
    load().catch(() => toast.error("Could not load compute settings"));
  }, [load]);

  const save = async (patch) => {
    setBusy(true);
    try {
      const { data: body } = await api.put("/studio/compute", patch);
      toast.success("Compute target saved");
      await load();
      onSaved?.(body);
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    } finally {
      setBusy(false);
    }
  };

  const testOllama = async () => {
    setBusy(true);
    try {
      const { data: body } = await api.post("/studio/compute/test-ollama");
      if (body.ok) toast.success(body.detail);
      else toast.error(body.detail);
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return (
      <StudioPanel title="Compute target" testId="compute-loading">
        <p className="text-xs" style={{ color: "#888" }}>
          Loading…
        </p>
      </StudioPanel>
    );
  }

  const settings = data.settings || {};
  const mode = settings.mode || "local";
  const devices = data.devices || [];

  return (
    <StudioPanel title="Compute target" testId="compute-panel" defaultOpen>
      <p className="text-xs mb-3" style={{ color: "#999", lineHeight: 1.45 }}>
        Local PC first — point heavy models at this machine, another PC on your network, or a remote
        Ollama server.
      </p>

      <div className="studio-compute-modes" data-testid="compute-modes">
        {MODES.map((m) => (
          <label key={m.id} className="studio-compute-mode">
            <input
              type="radio"
              name="compute-mode"
              value={m.id}
              checked={mode === m.id}
              disabled={busy}
              onChange={() => save({ mode: m.id, device_id: m.id === "network" ? settings.device_id : null })}
              data-testid={`compute-mode-${m.id}`}
            />
            <span className="studio-compute-mode-label">{m.label}</span>
            <span className="studio-compute-mode-hint">{m.hint}</span>
          </label>
        ))}
      </div>

      {mode === "network" ? (
        <StudioFieldRow label="Network PC" testId="compute-device-row">
          <select
            value={settings.device_id || ""}
            disabled={busy || devices.length === 0}
            onChange={(e) => save({ mode: "network", device_id: e.target.value || null })}
            data-testid="compute-device-select"
          >
            <option value="">Select a PC…</option>
            {devices.map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {d.name || d.device_id}
                {d.last_seen ? ` · seen ${String(d.last_seen).slice(0, 10)}` : ""}
              </option>
            ))}
          </select>
        </StudioFieldRow>
      ) : null}

      {mode === "server" ? (
        <>
          <StudioFieldRow label="Label" testId="compute-remote-label">
            <input
              type="text"
              placeholder="Homelab GPU box"
              value={(settings.remote || {}).label || ""}
              disabled={busy}
              onChange={(e) =>
                setData({
                  ...data,
                  settings: {
                    ...settings,
                    remote: { ...(settings.remote || {}), label: e.target.value },
                  },
                })
              }
              onBlur={() =>
                save({
                  mode: "server",
                  remote: {
                    label: (settings.remote || {}).label,
                    ollama_url: (settings.remote || {}).ollama_url,
                  },
                })
              }
            />
          </StudioFieldRow>
          <StudioFieldRow label="Ollama URL" testId="compute-remote-url">
            <input
              type="url"
              placeholder="http://192.168.1.50:11434"
              value={(settings.remote || {}).ollama_url || ""}
              disabled={busy}
              onChange={(e) =>
                setData({
                  ...data,
                  settings: {
                    ...settings,
                    remote: { ...(settings.remote || {}), ollama_url: e.target.value },
                  },
                })
              }
              onBlur={() =>
                save({
                  mode: "server",
                  remote: {
                    label: (settings.remote || {}).label,
                    ollama_url: (settings.remote || {}).ollama_url,
                  },
                })
              }
            />
          </StudioFieldRow>
        </>
      ) : null}

      <div className="flex gap-2 mt-3 flex-wrap">
        <button
          type="button"
          className="studio-btn studio-btn-primary"
          disabled={busy}
          onClick={testOllama}
          data-testid="compute-test-ollama"
        >
          Test Ollama
        </button>
      </div>

      <dl className="studio-dl mt-3" style={{ fontSize: 11 }}>
        <dt>Active PC</dt>
        <dd className="studio-value">{data.resolved_device_name || "none registered"}</dd>
        <dt>Ollama</dt>
        <dd>{data.ollama_reachable ? "reachable" : "not ready"}</dd>
      </dl>
    </StudioPanel>
  );
}
