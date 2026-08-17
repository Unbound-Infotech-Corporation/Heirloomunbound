import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";

export default function ModelsStudio() {
  const [catalog, setCatalog] = useState(null);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState("");

  const load = useCallback(async () => {
    const { data } = await api.get("/studio/models");
    setCatalog(data);
  }, []);

  useEffect(() => {
    load().catch(() => toast.error("Could not load model catalog"));
  }, [load]);

  const setBackend = async (featureId, backend) => {
    const map = { ...(catalog?.map || {}), [featureId]: backend };
    try {
      const { data } = await api.put("/studio/models", { map });
      setCatalog((c) => ({ ...c, map: data.map }));
      toast.success("Backend saved");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Save failed");
    }
  };

  const provision = async () => {
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

  return (
    <div className="px-6 py-6 max-w-3xl" data-testid="models-root">
      <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
        Local backends run on the dedicated PC (Whisper, Ollama, Piper). Cloud
        keys are fallbacks — you should not have to paste them for the machine
        in the other room to work. Hit Provision and the companion downloads
        what is missing.
      </p>

      <section className="studio-group" data-testid="models-probe">
        <h2>Dedicated PC</h2>
        <dl className="studio-dl">
          <dt>Status</dt>
          <dd>{companion.connected ? companion.name || "online" : "not connected"}</dd>
          <dt>GPU</dt>
          <dd>{companion.gpu?.detail || "—"}</dd>
          <dt>Ollama</dt>
          <dd>{companion.ollama?.detail || "—"}</dd>
          <dt>Whisper</dt>
          <dd>{companion.whisper?.detail || "—"}</dd>
          <dt>Piper</dt>
          <dd>{companion.piper?.detail || "—"}</dd>
        </dl>
        <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
          {companion.detail}
        </p>
        <div className="flex gap-2 mt-4">
          <button
            type="button"
            className="studio-btn-primary"
            data-testid="models-provision"
            disabled={busy}
            onClick={provision}
          >
            {busy ? "Queuing…" : "Provision models on this PC"}
          </button>
          <button type="button" className="studio-btn" onClick={() => load()}>
            Refresh probe
          </button>
        </div>
        {log ? (
          <pre className="studio-log" data-testid="models-log">
            {log}
          </pre>
        ) : null}
      </section>

      {(catalog.features || []).map((feat) => (
        <section className="studio-group" key={feat.id} data-testid={`models-feature-${feat.id}`}>
          <h2>{feat.label}</h2>
          <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>
            {feat.purpose}
            {feat.local_artifact ? ` · local artifact: ${feat.local_artifact}` : ""}
          </p>
          <select
            data-testid={`models-select-${feat.id}`}
            value={(catalog.map || {})[feat.id] || feat.selected}
            onChange={(e) => setBackend(feat.id, e.target.value)}
          >
            {(feat.backends || []).map((b) => (
              <option key={b.id} value={b.id}>
                {b.label}
                {b.available ? "" : " — needs provision"}
                {b.detail ? ` (${b.detail})` : ""}
              </option>
            ))}
          </select>
        </section>
      ))}
    </div>
  );
}
