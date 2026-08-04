import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Activity, Check, DollarSign, Eye, EyeOff, KeyRound, Loader2, Route as RouteIcon, ShieldCheck, X, Zap } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/usePageMeta";

// ---------------- helpers ----------------
const fmtUSD = (n) => `$${(n || 0).toFixed(4)}`;
const fmtInt = (n) => (n || 0).toLocaleString();

function Chip({ children, tone = "muted" }) {
  const styles = {
    muted:  { color: "var(--text-muted)",     background: "var(--surface-elev)" },
    accent: { color: "var(--accent)",         background: "var(--accent-muted)"  },
    warn:   { color: "#c47016",               background: "rgba(196,112,22,0.12)" },
    ok:     { color: "#527a3d",               background: "rgba(82,122,61,0.12)"  },
  }[tone] || {};
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium" style={styles}>
      {children}
    </span>
  );
}

/**
 * Compact SVG sparkline — no external chart lib. Takes a numeric array and
 * plots a polyline scaled to the given box. Zero-cost series get an empty
 * baseline. Used on every provider card to visualise 30-day spend trend.
 */
function Sparkline({ values, width = 120, height = 32, testid }) {
  if (!values || values.length === 0) return null;
  const max = Math.max(...values, 0);
  const min = 0;
  const n = values.length;
  const stepX = n > 1 ? width / (n - 1) : 0;
  const yFor = (v) => {
    if (max === min) return height - 1;
    return height - 1 - ((v - min) / (max - min)) * (height - 2);
  };
  const points = values.map((v, i) => `${(i * stepX).toFixed(1)},${yFor(v).toFixed(1)}`).join(" ");
  const last = values[values.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} data-testid={testid}
         style={{ overflow: "visible" }}>
      <polyline
        fill="none"
        stroke="var(--accent)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
      {/* Highlight dot on the last value */}
      {n >= 1 && (
        <circle
          cx={((n - 1) * stepX).toFixed(1)}
          cy={yFor(last).toFixed(1)}
          r="2"
          fill="var(--accent)"
        />
      )}
    </svg>
  );
}

// ---------------- page ----------------
export default function Routing() {
  usePageMeta({ title: "AI Router — Heirloom", description: "Multi-provider LLM routing + usage" });

  const [catalog, setCatalog] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [usage, setUsage] = useState(null);
  const [events, setEvents] = useState([]);
  const [health, setHealth] = useState([]);
  const [daily, setDaily] = useState({ days: [], series: {} });
  const [checkingHealth, setCheckingHealth] = useState(false);
  const [saving, setSaving] = useState(false);
  const [verifying, setVerifying] = useState({});
  const [visibleKey, setVisibleKey] = useState({});
  const [pendingKey, setPendingKey] = useState({});

  useEffect(() => { (async () => {
    try {
      const [c, cf, u, ev, h, dd] = await Promise.all([
        api.get("/routing/catalog"),
        api.get("/routing/config"),
        api.get("/routing/usage?days=30"),
        api.get("/routing/usage/events?limit=50"),
        api.get("/routing/health"),
        api.get("/routing/usage/daily?days=30"),
      ]);
      setCatalog(c.data); setCfg(cf.data); setUsage(u.data); setEvents(ev.data);
      setHealth(h.data);
      setDaily(dd.data);
    } catch (e) { toast.error("Couldn't load router config"); }
  })(); }, []);

  const healthByProvider = useMemo(() => {
    const map = {};
    (health || []).forEach((h) => { map[h.provider] = h; });
    return map;
  }, [health]);

  const runHealthCheck = async () => {
    setCheckingHealth(true);
    try {
      const { data } = await api.post("/routing/health/check");
      setHealth(data);
      toast.success(`Checked ${data.length} provider${data.length === 1 ? "" : "s"}`);
    } catch { toast.error("Health check failed"); }
    finally { setCheckingHealth(false); }
  };

  const providers = catalog?.providers || [];
  const tasks = catalog?.tasks || [];

  const setProviderField = (pid, field, value) => {
    setCfg((prev) => ({
      ...prev,
      providers: {
        ...prev.providers,
        [pid]: { ...(prev.providers[pid] || {}), [field]: value },
      },
    }));
  };
  const setTaskRoute = (task, pid) => {
    setCfg((prev) => ({ ...prev, task_routes: { ...prev.task_routes, [task]: pid } }));
  };

  const save = async () => {
    setSaving(true);
    try {
      // Merge in pending key edits (empty string = "no change" server-side)
      const providers = { ...cfg.providers };
      Object.entries(pendingKey).forEach(([pid, k]) => {
        providers[pid] = { ...(providers[pid] || {}), api_key: k };
      });
      const payload = {
        providers: Object.fromEntries(Object.entries(providers).map(([pid, p]) => [pid, {
          enabled: !!p.enabled,
          api_key: p.api_key ?? "",
          default_model: p.default_model || "",
          monthly_budget_usd: Number(p.monthly_budget_usd || 0),
        }])),
        task_routes: cfg.task_routes,
        fallback_order: cfg.fallback_order,
      };
      const { data } = await api.put("/routing/config", payload);
      setCfg(data);
      setPendingKey({});
      toast.success("Routing saved");
    } catch (e) { toast.error("Save failed"); }
    finally { setSaving(false); }
  };

  const verifyKey = async (pid) => {
    const k = (pendingKey[pid] ?? "").trim();
    if (!k) { toast.error("Paste a key first"); return; }
    setVerifying((v) => ({ ...v, [pid]: true }));
    try {
      const { data } = await api.post("/routing/verify", { provider: pid, api_key: k });
      if (data.ok) toast.success(`${pid} key verified — replied: ${data.sample || "ok"}`);
      else toast.error(`${pid}: ${data.error || "invalid key"}`);
    } catch (e) { toast.error("Verify failed"); }
    finally { setVerifying((v) => ({ ...v, [pid]: false })); }
  };

  const refreshUsage = async () => {
    try {
      const [u, ev, dd] = await Promise.all([
        api.get("/routing/usage?days=30"),
        api.get("/routing/usage/events?limit=50"),
        api.get("/routing/usage/daily?days=30"),
      ]);
      setUsage(u.data); setEvents(ev.data); setDaily(dd.data);
    } catch { /* silent */ }
  };

  // Test call — round-trip through /routing/chat to prove routing works
  const [testTask, setTestTask] = useState("chat");
  const [testMsg, setTestMsg] = useState("In one sentence: what is legacy?");
  const [testing, setTesting] = useState(false);
  const [testOut, setTestOut] = useState(null);

  const runTest = async () => {
    setTesting(true); setTestOut(null);
    try {
      const { data } = await api.post("/routing/chat", {
        task: testTask,
        messages: [{ role: "user", content: testMsg }],
      });
      setTestOut(data);
      await refreshUsage();
    } catch (e) { toast.error("Test call failed"); }
    finally { setTesting(false); }
  };

  const providerTotals = useMemo(() => {
    const map = {};
    (usage?.by_provider || []).forEach((r) => { map[r.provider] = r; });
    return map;
  }, [usage]);

  if (!catalog || !cfg) {
    return (
      <div className="flex items-center justify-center h-96" data-testid="routing-loading">
        <Loader2 className="w-6 h-6 animate-spin" style={{ color: "var(--accent)" }} />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto py-10 space-y-10" data-testid="routing-page">
      {/* Header */}
      <header className="space-y-3">
        <div className="overline">Chapter · Routing</div>
        <h1 className="font-serif text-4xl sm:text-5xl tracking-tight" style={{ color: "var(--text-primary)" }}>
          The twin&rsquo;s brain, routed
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>
          Send different tasks to different models. Bring your own keys for OpenAI, Anthropic, Gemini, Groq, xAI or DeepSeek — or let the built-in Emergent key handle everything. Costs and monthly budget caps are tracked here.
        </p>
        <div className="flex items-center gap-3 pt-1">
          <div className="text-xs px-3 py-1.5 rounded-full font-mono flex items-center gap-2"
               style={{ color: "var(--text-secondary)", background: "var(--surface-elev)" }}
               data-testid="routing-total-cost">
            <DollarSign className="w-3.5 h-3.5" /> {fmtUSD(usage?.total_cost_usd)} · last 30 days
          </div>
          <div className="text-xs px-3 py-1.5 rounded-full font-mono"
               style={{ color: "var(--text-secondary)", background: "var(--surface-elev)" }}
               data-testid="routing-total-calls">
            {fmtInt(usage?.total_calls)} calls
          </div>
          <button
            onClick={runHealthCheck}
            disabled={checkingHealth}
            data-testid="routing-check-health-btn"
            className="text-xs px-3 py-1.5 rounded-full flex items-center gap-1.5 border"
            style={{ color: "var(--text-primary)", background: "var(--surface-elev)", borderColor: "var(--border-default)" }}
          >
            {checkingHealth ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Activity className="w-3.5 h-3.5" />}
            Check provider health
          </button>
        </div>
      </header>

      {/* ── Task routing table ── */}
      <section data-testid="routing-tasks-section">
        <h2 className="font-serif text-2xl mb-4" style={{ color: "var(--text-primary)" }}>Per-task routing</h2>
        <div className="rounded-md border overflow-hidden" style={{ borderColor: "var(--border-default)" }}>
          {tasks.map((t, idx) => (
            <div key={t.id}
                 className="flex items-center justify-between px-5 py-4 gap-4"
                 style={{ borderTop: idx === 0 ? "none" : "1px solid var(--border-default)", background: "var(--surface)" }}>
              <div className="flex-1">
                <div className="font-medium" style={{ color: "var(--text-primary)" }}>{t.label}</div>
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>task id: <span className="font-mono">{t.id}</span></div>
              </div>
              <select
                value={cfg.task_routes[t.id] || t.default_provider}
                onChange={(e) => setTaskRoute(t.id, e.target.value)}
                data-testid={`task-route-${t.id}`}
                className="px-3 py-2 rounded-sm text-sm border"
                style={{ background: "var(--surface-elev)", color: "var(--text-primary)", borderColor: "var(--border-default)" }}
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>{p.label}</option>
                ))}
              </select>
            </div>
          ))}
        </div>
      </section>

      {/* ── Providers ── */}
      <section data-testid="routing-providers-section">
        <h2 className="font-serif text-2xl mb-4" style={{ color: "var(--text-primary)" }}>Providers</h2>
        <div className="grid gap-4">
          {providers.map((p) => {
            const pcfg = cfg.providers[p.id] || {};
            const spent = providerTotals[p.id]?.cost_usd || 0;
            const cap = Number(pcfg.monthly_budget_usd || 0);
            const overBudget = cap > 0 && spent >= cap;
            const isEmergent = p.id === "emergent";
            const h = healthByProvider[p.id];
            const dotColor = h?.status === "green" ? "#527a3d" : h?.status === "red" ? "#c25b3f" : "var(--text-muted)";
            const dotTitle = h
              ? `${h.status.toUpperCase()} · ${h.error || 'ok'} · checked ${(h.last_checked || '').slice(0,16).replace('T',' ')}`
              : "Not yet checked";

            return (
              <div key={p.id} className="rounded-md border p-5 space-y-4"
                   style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}
                   data-testid={`provider-card-${p.id}`}>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span
                        className="inline-block w-2.5 h-2.5 rounded-full"
                        style={{ background: dotColor }}
                        title={dotTitle}
                        data-testid={`provider-health-dot-${p.id}`}
                      />
                      <span className="font-medium" style={{ color: "var(--text-primary)" }}>{p.label}</span>
                      {!p.byok && <Chip tone="accent">built-in</Chip>}
                      {p.byok && (pcfg.has_key ? <Chip tone="ok"><Check className="w-3 h-3" />key stored</Chip> : <Chip tone="muted">no key</Chip>)}
                      {overBudget && <Chip tone="warn"><AlertTriangle className="w-3 h-3" />over budget</Chip>}
                    </div>
                    <div className="text-xs mt-1 flex items-center gap-3" style={{ color: "var(--text-muted)" }}>
                      <span>{isEmergent ? "Uses your Emergent Universal Key balance" : p.base_url}</span>
                      {h?.last_checked && (
                        <span className="font-mono" data-testid={`provider-health-when-${p.id}`}>
                          · checked {(h.last_checked || '').slice(11,16)}
                          {typeof h.latency_ms === 'number' ? ` · ${h.latency_ms}ms` : ''}
                        </span>
                      )}
                    </div>
                    {h?.status === "red" && h?.error && (
                      <div className="mt-2 text-xs font-mono" style={{ color: "#c25b3f" }} data-testid={`provider-health-error-${p.id}`}>
                        {h.error}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-4">
                    {daily.series && daily.series[p.id] && (
                      <div className="flex flex-col items-end gap-0.5" data-testid={`provider-spark-${p.id}`}>
                        <Sparkline values={daily.series[p.id]} testid={`provider-spark-svg-${p.id}`} />
                        <span className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                          30d · {fmtUSD(providerTotals[p.id]?.cost_usd || 0)}
                        </span>
                      </div>
                    )}
                    <label className="flex items-center gap-2 text-sm cursor-pointer" data-testid={`provider-enable-${p.id}`}>
                      <input
                        type="checkbox"
                        checked={!!pcfg.enabled}
                        onChange={(e) => setProviderField(p.id, "enabled", e.target.checked)}
                      />
                      <span style={{ color: "var(--text-secondary)" }}>Enabled</span>
                    </label>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {/* Default model */}
                  <div>
                    <label className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Default model</label>
                    <select
                      value={pcfg.default_model || p.default_model}
                      onChange={(e) => setProviderField(p.id, "default_model", e.target.value)}
                      data-testid={`provider-model-${p.id}`}
                      className="mt-1 w-full px-3 py-2 rounded-sm text-sm border"
                      style={{ background: "var(--surface-elev)", color: "var(--text-primary)", borderColor: "var(--border-default)" }}
                    >
                      {p.models.map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                  </div>

                  {/* API key (BYOK only) */}
                  <div>
                    <label className="text-xs uppercase tracking-wide flex items-center gap-1" style={{ color: "var(--text-muted)" }}>
                      <KeyRound className="w-3 h-3" /> API key
                    </label>
                    {isEmergent ? (
                      <div className="mt-1 px-3 py-2 rounded-sm text-sm border"
                           style={{ background: "var(--surface-elev)", color: "var(--text-muted)", borderColor: "var(--border-default)" }}>
                        Managed by Emergent
                      </div>
                    ) : (
                      <div className="mt-1 flex items-center gap-1">
                        <div className="flex-1 relative">
                          <input
                            type={visibleKey[p.id] ? "text" : "password"}
                            placeholder={pcfg.has_key ? "•••• stored ••••" : "paste key"}
                            value={pendingKey[p.id] ?? ""}
                            onChange={(e) => setPendingKey((k) => ({ ...k, [p.id]: e.target.value }))}
                            data-testid={`provider-key-${p.id}`}
                            className="w-full px-3 py-2 pr-8 rounded-sm text-sm border font-mono"
                            style={{ background: "var(--surface-elev)", color: "var(--text-primary)", borderColor: "var(--border-default)" }}
                          />
                          <button
                            type="button"
                            onClick={() => setVisibleKey((v) => ({ ...v, [p.id]: !v[p.id] }))}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-xs"
                            style={{ color: "var(--text-muted)" }}
                          >
                            {visibleKey[p.id] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                          </button>
                        </div>
                        <button
                          type="button"
                          onClick={() => verifyKey(p.id)}
                          disabled={verifying[p.id]}
                          className="px-3 py-2 rounded-sm text-xs border flex items-center gap-1"
                          style={{ background: "var(--surface-elev)", color: "var(--text-primary)", borderColor: "var(--border-default)" }}
                          data-testid={`provider-verify-${p.id}`}
                        >
                          {verifying[p.id] ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldCheck className="w-3 h-3" />} Verify
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Monthly budget */}
                  <div>
                    <label className="text-xs uppercase tracking-wide flex items-center gap-1" style={{ color: "var(--text-muted)" }}>
                      <DollarSign className="w-3 h-3" /> Monthly budget (USD)
                    </label>
                    <input
                      type="number"
                      min="0"
                      step="0.5"
                      value={pcfg.monthly_budget_usd || 0}
                      onChange={(e) => setProviderField(p.id, "monthly_budget_usd", Number(e.target.value))}
                      placeholder="0 = no cap"
                      data-testid={`provider-budget-${p.id}`}
                      className="mt-1 w-full px-3 py-2 rounded-sm text-sm border font-mono"
                      style={{ background: "var(--surface-elev)", color: "var(--text-primary)", borderColor: "var(--border-default)" }}
                    />
                    <div className="text-xs mt-1" style={{ color: overBudget ? "#c47016" : "var(--text-muted)" }}>
                      Spent this month: {fmtUSD(spent)}
                      {cap > 0 && ` of ${fmtUSD(cap)}`}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="flex items-center justify-end pt-6">
          <button
            onClick={save}
            disabled={saving}
            data-testid="routing-save-btn"
            className="px-6 py-2.5 rounded-sm text-sm font-medium flex items-center gap-2"
            style={{ background: "var(--accent)", color: "var(--surface)" }}
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            Save routing config
          </button>
        </div>
      </section>

      {/* ── Live test ── */}
      <section data-testid="routing-test-section">
        <h2 className="font-serif text-2xl mb-4" style={{ color: "var(--text-primary)" }}>Test a call</h2>
        <div className="rounded-md border p-5 space-y-3" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <select
              value={testTask}
              onChange={(e) => setTestTask(e.target.value)}
              data-testid="test-task-select"
              className="px-3 py-2 rounded-sm text-sm border"
              style={{ background: "var(--surface-elev)", color: "var(--text-primary)", borderColor: "var(--border-default)" }}
            >
              {tasks.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <input
              value={testMsg}
              onChange={(e) => setTestMsg(e.target.value)}
              placeholder="Prompt to route"
              className="md:col-span-2 px-3 py-2 rounded-sm text-sm border"
              style={{ background: "var(--surface-elev)", color: "var(--text-primary)", borderColor: "var(--border-default)" }}
              data-testid="test-prompt-input"
            />
            <button
              onClick={runTest}
              disabled={testing}
              data-testid="test-send-btn"
              className="px-4 py-2 rounded-sm text-sm font-medium flex items-center justify-center gap-2"
              style={{ background: "var(--accent)", color: "var(--surface)" }}
            >
              {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
              Send
            </button>
          </div>
          {testOut && (
            <div className="p-4 rounded-sm text-sm" style={{ background: "var(--surface-elev)" }} data-testid="test-result">
              {testOut.ok ? (
                <>
                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    <Chip tone="ok"><RouteIcon className="w-3 h-3" />{testOut.provider}</Chip>
                    <Chip>{testOut.model}</Chip>
                    <Chip>{testOut.prompt_tokens} in · {testOut.completion_tokens} out</Chip>
                    <Chip>{fmtUSD(testOut.cost_usd)}</Chip>
                    {testOut.attempted?.length > 0 && <Chip tone="warn">{testOut.attempted.length} fallback(s)</Chip>}
                  </div>
                  <div style={{ color: "var(--text-primary)" }}>{testOut.text}</div>
                </>
              ) : (
                <div style={{ color: "#c47016" }}>
                  <AlertTriangle className="w-4 h-4 inline mr-1" />
                  {testOut.error}
                  {testOut.attempted?.length > 0 && (
                    <ul className="mt-2 text-xs font-mono">
                      {testOut.attempted.map((a, i) => <li key={i}>{a.provider}: {a.error}</li>)}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* ── Usage stats ── */}
      <section data-testid="routing-usage-section">
        <h2 className="font-serif text-2xl mb-4" style={{ color: "var(--text-primary)" }}>Usage — last 30 days</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* By provider */}
          <div className="rounded-md border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
            <div className="px-4 py-3 border-b text-xs uppercase tracking-wide"
                 style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}>By provider</div>
            {(usage?.by_provider || []).length === 0 ? (
              <div className="p-6 text-sm" style={{ color: "var(--text-muted)" }}>No calls yet.</div>
            ) : usage.by_provider.map((row) => (
              <div key={row.provider} className="flex items-center justify-between px-4 py-3 border-t text-sm"
                   style={{ borderColor: "var(--border-default)" }}>
                <span style={{ color: "var(--text-primary)" }}>{row.provider}</span>
                <span className="font-mono" style={{ color: "var(--text-secondary)" }}>
                  {fmtInt(row.prompt_tokens + row.completion_tokens)} tok · {fmtUSD(row.cost_usd)}
                </span>
              </div>
            ))}
          </div>
          {/* By task */}
          <div className="rounded-md border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
            <div className="px-4 py-3 border-b text-xs uppercase tracking-wide"
                 style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}>By task</div>
            {(usage?.by_task || []).length === 0 ? (
              <div className="p-6 text-sm" style={{ color: "var(--text-muted)" }}>No calls yet.</div>
            ) : usage.by_task.map((row) => (
              <div key={row.task} className="flex items-center justify-between px-4 py-3 border-t text-sm"
                   style={{ borderColor: "var(--border-default)" }}>
                <span style={{ color: "var(--text-primary)" }}>{row.task}</span>
                <span className="font-mono" style={{ color: "var(--text-secondary)" }}>
                  {fmtInt(row.prompt_tokens + row.completion_tokens)} tok · {fmtUSD(row.cost_usd)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Recent events */}
        <div className="mt-6 rounded-md border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
          <div className="px-4 py-3 border-b text-xs uppercase tracking-wide flex items-center justify-between"
               style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}>
            <span>Recent calls</span>
            <button onClick={refreshUsage} className="text-xs" style={{ color: "var(--accent)" }} data-testid="refresh-events">Refresh</button>
          </div>
          {events.length === 0 ? (
            <div className="p-6 text-sm" style={{ color: "var(--text-muted)" }}>No calls yet — run a test above.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                    <th className="text-left px-4 py-2">Time</th>
                    <th className="text-left px-4 py-2">Task</th>
                    <th className="text-left px-4 py-2">Provider</th>
                    <th className="text-left px-4 py-2">Model</th>
                    <th className="text-right px-4 py-2">Tokens</th>
                    <th className="text-right px-4 py-2">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e, i) => (
                    <tr key={i} className="border-t" style={{ borderColor: "var(--border-default)" }}>
                      <td className="px-4 py-2 font-mono text-xs" style={{ color: "var(--text-muted)" }}>{(e.ts || "").slice(0, 16).replace("T", " ")}</td>
                      <td className="px-4 py-2" style={{ color: "var(--text-secondary)" }}>{e.task}</td>
                      <td className="px-4 py-2" style={{ color: "var(--text-primary)" }}>{e.provider}</td>
                      <td className="px-4 py-2 font-mono text-xs" style={{ color: "var(--text-secondary)" }}>{e.model}</td>
                      <td className="px-4 py-2 text-right font-mono">{fmtInt(e.prompt_tokens + e.completion_tokens)}</td>
                      <td className="px-4 py-2 text-right font-mono">{fmtUSD(e.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
