import { useEffect, useState } from "react";
import {
  Briefcase,
  Calendar,
  Check,
  Eye,
  Globe,
  Loader2,
  Mail,
  Monitor,
  Music,
  Palette,
  Phone,
  ShieldCheck,
  Terminal,
  Wrench,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/usePageMeta";

const ICONS = {
  globe: Globe,
  mail: Mail,
  calendar: Calendar,
  phone: Phone,
  music: Music,
  wrench: Wrench,
  monitor: Monitor,
  eye: Eye,
  terminal: Terminal,
  briefcase: Briefcase,
  palette: Palette,
  shield: ShieldCheck,
};

const CATEGORY_LABELS = {
  knowledge: "Knowledge",
  companion: "Companion",
  computer: "Your computer",
  work: "Work",
  create: "Create",
};

export default function Abilities() {
  usePageMeta({
    title: "Abilities · Heirloom",
    description: "Choose what your twin can do — toggle abilities on or off.",
  });

  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(null); // ability id in flight
  const [grant, setGrant] = useState(null); // ability pending permission grant

  const load = async () => {
    try {
      const r = await api.get("/abilities");
      setData(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't load abilities.");
    }
  };
  useEffect(() => {
    load();
  }, []);

  const disable = async (ability) => {
    setBusy(ability.id);
    try {
      await api.post(`/abilities/${ability.id}/disable`);
      toast.success(`${ability.name} turned off.`);
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't update.");
    } finally {
      setBusy(null);
    }
  };

  const confirmEnable = async () => {
    const ability = grant;
    if (!ability) return;
    setBusy(ability.id);
    try {
      await api.post(`/abilities/${ability.id}/enable`, {
        granted_permissions: ability.permissions.map((p) => p.id),
      });
      toast.success(`${ability.name} is on.`);
      setGrant(null);
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't enable.");
    } finally {
      setBusy(null);
    }
  };

  const onToggle = (ability) => {
    if (ability.enabled) {
      disable(ability);
    } else {
      setGrant(ability); // open permission grant modal
    }
  };

  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ color: "var(--text-muted)" }}>
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  const categories = [...new Set(data.abilities.map((a) => a.category))];
  const enabledCount = data.abilities.filter((a) => a.enabled).length;

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-5xl" data-testid="abilities-root">
      <header className="mb-10">
        <div className="overline mb-3">what your twin can do</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">Abilities</h1>
        <p className="mt-3 text-base max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          Switch on the powers you want your twin to have. Each one asks permission for exactly what it touches —
          turn anything off any time. <b style={{ color: "var(--text-primary)" }}>{enabledCount}</b> of {data.abilities.length} on.
        </p>
        {!data.companion_connected && (
          <div
            className="mt-5 inline-flex items-center gap-2 text-xs px-4 py-2 rounded-sm"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-muted)" }}
            data-testid="abilities-no-companion"
          >
            <Monitor className="h-3.5 w-3.5" /> Computer abilities need your Heirloom desktop app running.
          </div>
        )}
      </header>

      {categories.map((cat) => (
        <section key={cat} className="mb-10">
          <div className="overline mb-4">{CATEGORY_LABELS[cat] || cat}</div>
          <div className="grid sm:grid-cols-2 gap-4">
            {data.abilities.filter((a) => a.category === cat).map((ability) => {
              const Icon = ICONS[ability.icon] || Globe;
              return (
                <div
                  key={ability.id}
                  className="surface p-5 flex flex-col"
                  data-testid={`ability-card-${ability.id}`}
                  style={{ border: `1px solid ${ability.enabled ? "var(--accent)" : "var(--border-default)"}` }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <div
                        className="h-9 w-9 rounded-sm flex items-center justify-center shrink-0"
                        style={{
                          background: ability.enabled ? "var(--accent-muted, rgba(212,163,115,0.12))" : "var(--bg-base)",
                          border: `1px solid ${ability.enabled ? "var(--accent)" : "var(--border-default)"}`,
                          color: ability.enabled ? "var(--accent)" : "var(--text-muted)",
                        }}
                      >
                        <Icon className="h-4 w-4" />
                      </div>
                      <div>
                        <div className="font-serif text-lg leading-tight">{ability.name}</div>
                        {ability.requires_companion && (
                          <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                            needs desktop app
                          </div>
                        )}
                      </div>
                    </div>
                    <ToggleSwitch
                      on={ability.enabled}
                      busy={busy === ability.id}
                      onClick={() => onToggle(ability)}
                      testid={`ability-toggle-${ability.id}`}
                    />
                  </div>
                  <p className="text-sm mt-3 flex-1" style={{ color: "var(--text-secondary)" }}>
                    {ability.tagline}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {ability.permissions.map((p) => (
                      <span
                        key={p.id}
                        className="text-xs px-2 py-0.5 rounded-sm"
                        style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-muted)" }}
                      >
                        {p.label}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ))}

      {grant && (
        <PermissionDialog
          ability={grant}
          busy={busy === grant.id}
          onConfirm={confirmEnable}
          onClose={() => setGrant(null)}
        />
      )}
    </div>
  );
}

function ToggleSwitch({ on, busy, onClick, testid }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      data-testid={testid}
      aria-pressed={on}
      className="relative h-6 w-11 rounded-full transition-colors shrink-0 disabled:opacity-60"
      style={{ background: on ? "var(--accent)" : "var(--border-default)" }}
    >
      <span
        className="absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all flex items-center justify-center"
        style={{ left: on ? "22px" : "2px" }}
      >
        {busy && <Loader2 className="h-3 w-3 animate-spin" style={{ color: "var(--accent)" }} />}
      </span>
    </button>
  );
}

function PermissionDialog({ ability, busy, onConfirm, onClose }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-6"
      style={{ background: "rgba(0,0,0,0.7)" }}
      data-testid="permission-dialog"
    >
      <div className="surface w-full max-w-md p-8" style={{ background: "var(--bg-surface)" }}>
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5" style={{ color: "var(--accent)" }} />
            <div className="overline">grant permission</div>
          </div>
          <button onClick={onClose} data-testid="permission-close" className="p-1" style={{ color: "var(--text-muted)" }}>
            <X className="h-5 w-5" />
          </button>
        </div>
        <h2 className="font-serif text-2xl mb-2">Turn on {ability.name}?</h2>
        <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
          Your twin will be able to:
        </p>
        <ul className="space-y-2 mb-6">
          {ability.permissions.map((p) => (
            <li key={p.id} className="flex items-start gap-2 text-sm" style={{ color: "var(--text-primary)" }}>
              <Check className="h-4 w-4 mt-0.5 shrink-0" style={{ color: "var(--accent)" }} />
              {p.label}
            </li>
          ))}
        </ul>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-5 py-2 text-sm rounded-sm"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            data-testid="permission-confirm"
            className="inline-flex items-center gap-2 px-5 py-2 text-sm rounded-sm disabled:opacity-60"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            Allow & turn on
          </button>
        </div>
      </div>
    </div>
  );
}
