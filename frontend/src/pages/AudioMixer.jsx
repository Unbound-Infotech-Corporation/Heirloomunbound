import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";

const RATES = [16000, 44100, 48000];

export default function AudioMixer() {
  const [settings, setSettings] = useState(null);
  const [inputs, setInputs] = useState([]);
  const [outputs, setOutputs] = useState([]);
  const [level, setLevel] = useState(0);
  const [saving, setSaving] = useState(false);
  const meterRef = { current: null };

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

  return (
    <div className="px-6 py-6 max-w-3xl" data-testid="mixer-root">
      <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
        This is the Heirloom session — the slider Windows Volume Mixer should
        show as <strong>Heirloom</strong>, not python.exe. Changing output here
        (or in the Windows mixer) only moves this app.
      </p>

      <section className="studio-group" data-testid="mixer-devices">
        <h2>Devices</h2>
        <label>
          Microphone
          <select
            data-testid="mixer-input"
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
        <label>
          Playback
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
        </label>
        <label>
          Sample rate
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
        </label>
      </section>

      <section className="studio-group" data-testid="mixer-input-section">
        <h2>Microphone</h2>
        <label>
          Gain ({settings.input_gain}%)
          <input
            type="range"
            min="0"
            max="200"
            data-testid="mixer-gain"
            value={settings.input_gain}
            onChange={(e) => patch({ input_gain: Number(e.target.value) })}
          />
        </label>
        <label>
          Noise gate ({settings.noise_gate_db} dB)
          <input
            type="range"
            min="-80"
            max="0"
            data-testid="mixer-gate"
            value={settings.noise_gate_db}
            onChange={(e) => patch({ noise_gate_db: Number(e.target.value) })}
          />
        </label>
        <label>
          High-pass ({settings.high_pass_hz} Hz)
          <input
            type="range"
            min="0"
            max="200"
            data-testid="mixer-hpf"
            value={settings.high_pass_hz}
            onChange={(e) => patch({ high_pass_hz: Number(e.target.value) })}
          />
        </label>
        <label className="studio-check">
          <input
            type="checkbox"
            checked={!!settings.mute_input}
            onChange={(e) => patch({ mute_input: e.target.checked })}
          />
          Mute input
        </label>
        <label className="studio-check">
          <input
            type="checkbox"
            checked={!!settings.noise_suppression}
            onChange={(e) => patch({ noise_suppression: e.target.checked })}
          />
          Noise suppression
        </label>
        <label className="studio-check">
          <input
            type="checkbox"
            checked={!!settings.monitor_input}
            onChange={(e) => patch({ monitor_input: e.target.checked })}
          />
          Monitor input
        </label>
        <label className="studio-check">
          <input
            type="checkbox"
            data-testid="mixer-live-listen"
            checked={!!settings.live_listen}
            onChange={(e) => patch({ live_listen: e.target.checked })}
          />
          Live listen — twin wakes when someone enters the room
        </label>
        <div className="studio-vu" data-testid="mixer-vu">
          <div className="studio-vu-fill" style={{ width: `${level}%` }} />
        </div>
      </section>

      <section className="studio-group" data-testid="mixer-output-section">
        <h2>Heirloom output (Windows mixer session)</h2>
        <label>
          Session volume ({settings.output_volume}%)
          <input
            type="range"
            min="0"
            max="100"
            data-testid="mixer-volume"
            value={settings.output_volume}
            onChange={(e) => patch({ output_volume: Number(e.target.value) })}
          />
        </label>
        <label className="studio-check">
          <input
            type="checkbox"
            data-testid="mixer-mute-output"
            checked={!!settings.mute_output}
            onChange={(e) => patch({ mute_output: e.target.checked })}
          />
          Mute output
        </label>
        <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
          {saving ? "Saving…" : "Synced to the dedicated PC on the next poll (~3s)."}
        </p>
      </section>
    </div>
  );
}
