import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Check,
  Download,
  ExternalLink,
  Home,
  KeyRound,
  Loader2,
  Monitor,
  Sparkles,
  Unplug,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/usePageMeta";

/**
 * Maestro-style model studio. Connect a cloud API (paste a key once) or
 * tap a local model to download it onto the home PC. Then pick which
 * model each function uses from a dropdown. No extra setup screens.
 */
export default function Models() {
  usePageMeta({
    title: "Models · Heirloom",
    description: "Connect AI services and download local models in one click.",
  });

  const [studio, setStudio] = useState(null);
  const [connectFor, setConnectFor] = useState(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState("");
  const [pulls, setPulls] = useState({}); // model -> {cmd_id, status}

  const load = async () => {
    try {
      const { data } = await api.get("/models/studio");
      setStudio(data);
    } catch {
      toast.error("Couldn't load models");
    }
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    const pending = Object.values(pulls).filter((p) => p.cmd_id && p.status !== "done" && p.status !== "error");
    if (pending.length === 0) return undefined;
    const t = setInterval(async () => {
      for (const p of pending) {
        try {
          const { data } = await api.get(`/models/pulls/${p.cmd_id}`);
          setPulls((prev) => ({ ...prev, [p.model]: { ...prev[p.model], ...data } }));
          if (data.ok) {
            toast.success(`${p.model} is ready on your PC`);
            load();
          } else if (data.status === "error") {
            toast.error(data.output || `Couldn't download ${p.model}`);
          }
        } catch { /* keep polling */ }
      }
    }, 2500);
    return () => clearInterval(t);
  }, [pulls]);

  if (!studio) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ color: "var(--text-muted)" }}>
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  const cfg = studio.config || {};
  const home = studio.home || {};
  const assignments = studio.assignments || {};
  const options = studio.options || [];
  const installed = new Set(home.local_models || []);

  const connect = async () => {
    if (!connectFor) return;
    setBusy(`connect:${connectFor.id}`);
    try {
      await api.post("/models/connect", { provider: connectFor.id, api_key: key });
      toast.success(`${connectFor.label} is connected`);
      setConnectFor(null);
      setKey("");
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "That key didn't work");
    } finally {
      setBusy("");
    }
  };

  const enableEmergent = async () => {
    setBusy("connect:emergent");
    try {
      await api.post("/models/connect", { provider: "emergent" });
      toast.success("Heirloom key is on");
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't enable");
    } finally { setBusy(""); }
  };

  const disconnect = async (pid) => {
    setBusy(`disc:${pid}`);
    try {
      await api.post("/models/disconnect", { provider: pid });
      toast.success("Disconnected");
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't disconnect");
    } finally { setBusy(""); }
  };

  const assign = async (functionId, optionId) => {
    setBusy(`assign:${functionId}`);
    try {
      await api.post("/models/assign", { function: functionId, option_id: optionId });
      toast.success("Saved");
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't assign");
    } finally { setBusy(""); }
  };

  const pull = async (model) => {
    setBusy(`pull:${model}`);
    try {
      const { data } = await api.post("/models/pull", { model });
      setPulls((prev) => ({ ...prev, [model]: { model, cmd_id: data.cmd_id, status: data.status } }));
      toast.success(data.hint || `Downloading ${model} on your PC…`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't start download");
    } finally { setBusy(""); }
  };

  const isReady = (svc) => {
    const p = cfg.providers?.[svc.id] || {};
    return !!p.enabled && (!svc.byok || p.has_key);
  };

  const isInstalled = (id) =>
    installed.has(id) || [...installed].some((t) => t === id || t.startsWith(`${id.split(":")[0]}:`));

  return (
    <div className="min-h-screen px-6 sm:px-10 py-12" style={{ background: "var(--bg-base)" }} data-testid="models-page">
      <div className="max-w-5xl mx-auto space-y-12">
        <header>
          <div className="overline mb-3">Maestro</div>
          <h1 className="font-serif text-4xl sm:text-5xl font-light tracking-tight mb-3">
            Click the brain you want.
          </h1>
          <p className="text-base max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            Connect a cloud API with one key, or download a model onto your home computer.
            Then pick which one each part of Heirloom uses. That&apos;s the whole setup.
          </p>
          <p className="text-sm max-w-2xl mt-3" style={{ color: "var(--text-muted)" }}>
            Twin chat, the Interviewer, and Quick replies work together. One talks as you,
            one asks better questions, one keeps the voice honest. Pick different brains if
            you like, or leave the Heirloom key on all three.
          </p>
          <div
            className="mt-5 inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded-full"
            style={{ background: "var(--surface-elev)", color: home.online ? "#527a3d" : "var(--text-muted)" }}
            data-testid="models-home-pill"
          >
            {home.online ? <Home className="h-3.5 w-3.5" /> : <Monitor className="h-3.5 w-3.5" />}
            {home.online
              ? `Home PC online · ${home.name || "companion"}`
              : home.connected
                ? "Home PC is asleep — open the desktop app to download models"
                : "Pair the desktop app to download models onto your PC"}
          </div>
        </header>

        {/* Cloud APIs */}
        <section data-testid="models-cloud">
          <h2 className="font-serif text-2xl mb-4">Cloud APIs</h2>
          <div className="grid sm:grid-cols-2 gap-3">
            {studio.services.map((svc) => {
              const ready = isReady(svc);
              return (
                <div
                  key={svc.id}
                  className="rounded-md border p-4 flex flex-col gap-3"
                  style={{ background: "var(--surface)", borderColor: ready ? "var(--accent)" : "var(--border-default)" }}
                  data-testid={`model-svc-${svc.id}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-medium" style={{ color: "var(--text-primary)" }}>{svc.label}</div>
                      <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{svc.blurb}</p>
                    </div>
                    {ready
                      ? <span className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full" style={{ background: "rgba(82,122,61,0.12)", color: "#527a3d" }}>ready</span>
                      : <span className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full" style={{ background: "var(--surface-elev)", color: "var(--text-muted)" }}>off</span>}
                  </div>
                  <div className="flex flex-wrap gap-2 mt-auto">
                    {svc.byok ? (
                      <button
                        type="button"
                        onClick={() => { setConnectFor(svc); setKey(""); }}
                        data-testid={`model-connect-${svc.id}`}
                        className="text-xs px-3 py-1.5 rounded-sm flex items-center gap-1.5"
                        style={{ background: "var(--accent)", color: "var(--surface)" }}
                      >
                        <KeyRound className="h-3.5 w-3.5" />
                        {ready ? "Update key" : "Connect"}
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={enableEmergent}
                        disabled={ready || busy === "connect:emergent"}
                        data-testid="model-connect-emergent"
                        className="text-xs px-3 py-1.5 rounded-sm flex items-center gap-1.5"
                        style={{ background: ready ? "var(--surface-elev)" : "var(--accent)", color: ready ? "var(--text-muted)" : "var(--surface)" }}
                      >
                        <Sparkles className="h-3.5 w-3.5" />
                        {ready ? "On" : "Use this"}
                      </button>
                    )}
                    {ready && svc.byok && (
                      <button
                        type="button"
                        onClick={() => disconnect(svc.id)}
                        data-testid={`model-disconnect-${svc.id}`}
                        className="text-xs px-3 py-1.5 rounded-sm flex items-center gap-1.5"
                        style={{ border: "1px solid var(--border-default)", color: "var(--text-muted)" }}
                      >
                        <Unplug className="h-3.5 w-3.5" /> Off
                      </button>
                    )}
                    {svc.signup_url && (
                      <a
                        href={svc.signup_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs px-3 py-1.5 rounded-sm flex items-center gap-1"
                        style={{ color: "var(--text-muted)" }}
                      >
                        Get a key <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Local downloads */}
        <section data-testid="models-local">
          <h2 className="font-serif text-2xl mb-1">Download to your PC</h2>
          <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
            Like Pinokio&apos;s Maestro: tap one, it installs on the home computer, then it&apos;s in the dropdown.
            Needs <a href="https://ollama.com" target="_blank" rel="noreferrer" className="underline">Ollama</a> (one installer) and the Heirloom desktop app open.
            {" "}Want a face that looks back at you? <Link to="/avatar-studio" className="underline">Avatar Studio</Link> — one photo, one tick, we install the rest.
          </p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {studio.local_models.map((m) => {
              const ready = isInstalled(m.id);
              const pulling = pulls[m.id] && !["done", "error"].includes(pulls[m.id].status);
              return (
                <div
                  key={m.id}
                  className="rounded-md border p-4 flex flex-col gap-2"
                  style={{ background: "var(--surface)", borderColor: ready ? "var(--accent)" : "var(--border-default)" }}
                  data-testid={`local-model-${m.id}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="font-medium" style={{ color: "var(--text-primary)" }}>{m.name}</div>
                    {m.recommended && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-sm" style={{ background: "var(--accent-muted)", color: "var(--accent)" }}>start here</span>
                    )}
                  </div>
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>{m.blurb}</p>
                  <div className="text-[11px] font-mono" style={{ color: "var(--text-muted)" }}>{m.size} · {m.ram} RAM · {m.kind}</div>
                  <button
                    type="button"
                    disabled={ready || pulling || busy === `pull:${m.id}`}
                    onClick={() => pull(m.id)}
                    data-testid={`local-pull-${m.id}`}
                    className="mt-auto text-xs px-3 py-1.5 rounded-sm flex items-center justify-center gap-1.5"
                    style={{
                      background: ready ? "var(--surface-elev)" : "var(--accent)",
                      color: ready ? "var(--text-muted)" : "var(--surface)",
                    }}
                  >
                    {ready ? <Check className="h-3.5 w-3.5" /> : pulling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                    {ready ? "Ready on this PC" : pulling ? "Downloading…" : "Download"}
                  </button>
                </div>
              );
            })}
          </div>
        </section>

        {/* Per-function dropdowns */}
        <section data-testid="models-functions">
          <h2 className="font-serif text-2xl mb-1">What uses which model</h2>
          <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
            Different jobs, not three twins arguing. Leave them on Heirloom if you&apos;re happy.
          </p>
          <div className="rounded-md border overflow-hidden" style={{ borderColor: "var(--border-default)" }}>
            {studio.functions.map((fn, idx) => {
              const asg = assignments[fn.id] || {};
              return (
                <div
                  key={fn.id}
                  className="flex flex-col sm:flex-row sm:items-center gap-3 px-5 py-4"
                  style={{ borderTop: idx === 0 ? "none" : "1px solid var(--border-default)", background: "var(--surface)" }}
                  data-testid={`fn-row-${fn.id}`}
                >
                  <div className="flex-1">
                    <div className="font-medium" style={{ color: "var(--text-primary)" }}>{fn.label}</div>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>{fn.blurb}</div>
                  </div>
                  <select
                    value={asg.option_id || ""}
                    onChange={(e) => assign(fn.id, e.target.value)}
                    disabled={busy === `assign:${fn.id}` || options.length === 0}
                    data-testid={`fn-select-${fn.id}`}
                    className="px-3 py-2 rounded-sm text-sm border min-w-[220px]"
                    style={{ background: "var(--surface-elev)", color: "var(--text-primary)", borderColor: "var(--border-default)" }}
                  >
                    {options.length === 0 && <option value="">Connect a service above first</option>}
                    {options.map((o) => (
                      <option key={o.id} value={o.id}>{o.label}</option>
                    ))}
                  </select>
                  <Link to={fn.page} className="text-xs" style={{ color: "var(--text-muted)" }}>open</Link>
                </div>
              );
            })}
          </div>
          <p className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>
            Power users: budgets, fallbacks and health checks still live on{" "}
            <Link to="/routing" className="underline">AI Router</Link>.
          </p>
        </section>
      </div>

      {connectFor && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(18,17,16,0.75)", backdropFilter: "blur(4px)" }}
          onClick={() => setConnectFor(null)}
          data-testid="model-connect-modal"
        >
          <div
            className="w-full max-w-md rounded-md border p-6 space-y-4"
            style={{ background: "var(--surface)", borderColor: "var(--border-default)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="font-serif text-2xl" style={{ color: "var(--text-primary)" }}>
              Connect {connectFor.label}
            </h3>
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              Paste the API key. We check it once, save it for you, and never show it again.
            </p>
            {connectFor.dashboard_url && (
              <a href={connectFor.dashboard_url} target="_blank" rel="noreferrer" className="text-xs inline-flex items-center gap-1" style={{ color: "var(--accent)" }}>
                Open {connectFor.label} keys <ExternalLink className="h-3 w-3" />
              </a>
            )}
            <input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={connectFor.key_hint || "API key"}
              data-testid="model-connect-key"
              className="w-full px-3 py-2 rounded-sm text-sm border"
              style={{ background: "var(--surface-elev)", color: "var(--text-primary)", borderColor: "var(--border-default)" }}
            />
            <div className="flex justify-end gap-3">
              <button type="button" onClick={() => setConnectFor(null)} className="px-4 py-2 text-sm" style={{ color: "var(--text-secondary)" }}>Cancel</button>
              <button
                type="button"
                onClick={connect}
                disabled={!key.trim() || busy.startsWith("connect:")}
                data-testid="model-connect-save"
                className="px-5 py-2 rounded-sm text-sm font-medium flex items-center gap-2"
                style={{ background: "var(--accent)", color: "var(--surface)" }}
              >
                {busy.startsWith("connect:") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
                Connect
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
