import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";
import {
  StudioFieldRow,
  StudioPanel,
  StudioWorkspace,
} from "../components/studio";

const RATES = [16000, 44100, 48000];

export default function AudioMixer() {
  const [settings, setSettings] = useState(null);
  const [inputs, setInputs] = useState([]);
  const [outputs, setOutputs] = useState([]);
  const [level, setLevel] = useState(0);
  const [saving, setSaving] = useState(false);
  const meterRef = useRef(null);

  const load = useCallback(async () => {
    const { data } = await api.get("/studio/audio");
    setSettings(data.settings);
  }, []);

  useEffect(() => {
    load().catch(() => toast.error("Could not load mixer settings"));
  }, [load]);

  useEffect(() => {
    let stream;
    const enumDevices = async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const all = await navigator.mediaDevices.enumerateDevices();
        setInputs(all.filter((d) => d.kind === "audioinput"));
        setOutputs(all.filter((d) => d.kind === "audiooutput"));
        const ctx = new AudioContext();
        const src = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        src.connect(analyser);
        const data = new Uint8Array(analyser.frequencyBinCount);
        const tick = () => {
          analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) {
            const v = (data[i] - 128) / 128;
            sum += v * v;
          }
          setLevel(Math.min(100, Math.sqrt(sum / data.length) * 180));
          meterRef.current = requestAnimationFrame(tick);
        };
        tick();
      } catch {
        /* permission denied — still usable with defaults */
      }
    };
    enumDevices();
    return () => {
      if (meterRef.current) cancelAnimationFrame(meterRef.current);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const patch = async (partial) => {
    const next = { ...settings, ...partial };
    setSettings(next);
    setSaving(true);
    try {
      const { data } = await api.put("/studio/audio", partial);
      setSettings(data.settings);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Mixer save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!settings) {
    return (
      <div className="px-6 py-10" data-testid="mixer-loading">
        Loading mixer…
      </div>
    );
  }

  const inputLabel =
    inputs.find((d) => d.deviceId === settings.input_device_id)?.label || "System default";
  const outputLabel =
    outputs.find((d) => d.deviceId === settings.output_device_id)?.label || "System default";

  return (
    <div data-testid="mixer-root">
      <div className="studio-options-bar" data-testid="mixer-options-bar">
        <div className="studio-opt-group">
          <label>
            Input
            <select
              data-testid="mixer-input-opt"
              value={settings.input_device_id || "default"}
              onChange={(e) => patch({ input_device_id: e.target.value })}
            >
              <option value="default">System default</option>
              {inputs.map((d) => (
                <option key={d.deviceId} value={d.deviceId}>
                  {d.label || "Microphone"}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="studio-opt-group">
          <label>
            Output
            <select
              data-testid="mixer-output-opt"
              value={settings.output_device_id || "default"}
              onChange={(e) => patch({ output_device_id: e.target.value })}
            >
              <option value="default">System default</option>
              {outputs.map((d) => (
                <option key={d.deviceId} value={d.deviceId}>
                  {d.label || "Speakers"}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="studio-opt-group">
          <span>Rate</span>
          <select
            data-testid="mixer-rate-opt"
            value={settings.sample_rate}
            onChange={(e) => patch({ sample_rate: Number(e.target.value) })}
          >
            {RATES.map((r) => (
              <option key={r} value={r}>
                {r} Hz
              </option>
            ))}
          </select>
        </div>
        <span className="ml-auto" style={{ color: saving ? "#4da3ff" : "#666" }}>
          {saving ? "Syncing…" : "Ready"}
        </span>
      </div>

      <StudioWorkspace
        testId="mixer-workspace"
        inspector={
          <>
            <StudioPanel title="Devices" testId="mixer-devices">
              <StudioFieldRow label="Microphone" testId="mixer-input">
                <select
                  value={settings.input_device_id || "default"}
                  onChange={(e) => patch({ input_device_id: e.target.value })}
                >
                  <option value="default">System default</option>
                  {inputs.map((d) => (
                    <option key={d.deviceId} value={d.deviceId}>
                      {d.label || "Microphone"}
                    </option>
                  ))}
                </select>
              </StudioFieldRow>
              <StudioFieldRow label="Playback">
                <select
                  data-testid="mixer-output"
                  value={settings.output_device_id || "default"}
                  onChange={(e) => patch({ output_device_id: e.target.value })}
                >
                  <option value="default">System default</option>
                  {outputs.map((d) => (
                    <option key={d.deviceId} value={d.deviceId}>
                      {d.label || "Speakers"}
                    </option>
                  ))}
                </select>
              </StudioFieldRow>
              <StudioFieldRow label="Sample rate">
                <select
                  data-testid="mixer-rate"
                  value={settings.sample_rate}
                  onChange={(e) => patch({ sample_rate: Number(e.target.value) })}
                >
                  {RATES.map((r) => (
                    <option key={r} value={r}>
                      {r} Hz
                    </option>
                  ))}
                </select>
              </StudioFieldRow>
            </StudioPanel>

            <StudioPanel title="Input" testId="mixer-input-section" defaultOpen>
              <StudioFieldRow label="Gain">
                <input
                  type="range"
                  min="0"
                  max="200"
                  data-testid="mixer-gain"
                  value={settings.input_gain}
                  onChange={(e) => patch({ input_gain: Number(e.target.value) })}
                />
              </StudioFieldRow>
              <p className="studio-field-hint" style={{ textAlign: "right", marginTop: -4 }}>
                <span className="studio-value">{settings.input_gain}%</span>
              </p>
              <StudioFieldRow label="Noise gate">
                <input
                  type="range"
                  min="-80"
                  max="0"
                  data-testid="mixer-gate"
                  value={settings.noise_gate_db}
                  onChange={(e) => patch({ noise_gate_db: Number(e.target.value) })}
                />
              </StudioFieldRow>
              <p className="studio-field-hint" style={{ textAlign: "right", marginTop: -4 }}>
                <span className="studio-value">{settings.noise_gate_db} dB</span>
              </p>
              <StudioFieldRow label="High-pass">
                <input
                  type="range"
                  min="0"
                  max="200"
                  data-testid="mixer-hpf"
                  value={settings.high_pass_hz}
                  onChange={(e) => patch({ high_pass_hz: Number(e.target.value) })}
                />
              </StudioFieldRow>
              <label className="studio-check-row">
                <input
                  type="checkbox"
                  checked={!!settings.mute_input}
                  onChange={(e) => patch({ mute_input: e.target.checked })}
                />
                Mute input
              </label>
              <label className="studio-check-row">
                <input
                  type="checkbox"
                  checked={!!settings.noise_suppression}
                  onChange={(e) => patch({ noise_suppression: e.target.checked })}
                />
                Noise suppression
              </label>
              <label className="studio-check-row">
                <input
                  type="checkbox"
                  checked={!!settings.monitor_input}
                  onChange={(e) => patch({ monitor_input: e.target.checked })}
                />
                Monitor input
              </label>
              <label className="studio-check-row">
                <input
                  type="checkbox"
                  data-testid="mixer-live-listen"
                  checked={!!settings.live_listen}
                  onChange={(e) => patch({ live_listen: e.target.checked })}
                />
                Live listen — room presence
              </label>
            </StudioPanel>

            <StudioPanel title="Output session" testId="mixer-output-section">
              <StudioFieldRow label="Volume">
                <input
                  type="range"
                  min="0"
                  max="100"
                  data-testid="mixer-volume"
                  value={settings.output_volume}
                  onChange={(e) => patch({ output_volume: Number(e.target.value) })}
                />
              </StudioFieldRow>
              <p className="studio-field-hint" style={{ textAlign: "right", marginTop: -4 }}>
                <span className="studio-value">{settings.output_volume}%</span>
              </p>
              <label className="studio-check-row">
                <input
                  type="checkbox"
                  data-testid="mixer-mute-output"
                  checked={!!settings.mute_output}
                  onChange={(e) => patch({ mute_output: e.target.checked })}
                />
                Mute output
              </label>
            </StudioPanel>
          </>
        }
        canvas={
          <div className="studio-canvas-hero">
            <h1>Heirloom audio session</h1>
            <p>
              Windows Volume Mixer should list this app as <strong>Heirloom</strong>, not
              python.exe. Device and level changes sync to the dedicated PC on the next companion
              poll (~3 seconds).
            </p>

            <div className="studio-session-badge">
              <span>Session</span>
              <strong>Heirloom</strong>
              <span>·</span>
              <span>{inputLabel}</span>
              <span>→</span>
              <span>{outputLabel}</span>
            </div>

            <div className="studio-meter-stack">
              <div>
                <div className="studio-meter-label">Input level</div>
                <div className="studio-vu-lg" data-testid="mixer-vu">
                  <div className="studio-vu-fill" style={{ width: `${level}%` }} />
                </div>
              </div>
              <div>
                <div className="studio-meter-label">Output volume</div>
                <div className="studio-vu-lg">
                  <div
                    className="studio-vu-fill"
                    style={{
                      width: settings.mute_output ? "0%" : `${settings.output_volume}%`,
                      opacity: settings.mute_output ? 0.3 : 1,
                    }}
                  />
                </div>
              </div>
            </div>
          </div>
        }
        footer={
          <>
            <span>{settings.sample_rate} Hz</span>
            <span className="mx-2">·</span>
            <span>Gain {settings.input_gain}%</span>
            <span className="mx-2">·</span>
            <span>{saving ? "Saving…" : "Synced to dedicated PC"}</span>
          </>
        }
      />
    </div>
  );
}
