import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Phone, Puzzle } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

/**
 * Optional phone integrations. Desktop-off packs are hidden by the API.
 * Phone calls are always listed — that's the handset add-on.
 */
export default function MobilePacks() {
  const [items, setItems] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");

  const load = async () => {
    try {
      const { data } = await api.get("/mobile/integrations");
      setItems(data.integrations || []);
      setNote(data.note || "");
    } catch {
      toast.error("Couldn't load packs");
      setItems([]);
    }
  };

  useEffect(() => { load(); }, []);

  const toggle = async (item) => {
    setBusy(item.id);
    try {
      const { data } = await api.put(`/mobile/integrations/${item.id}`, { enabled: !item.phone_enabled });
      setItems(data.integrations || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't update that pack");
    } finally {
      setBusy("");
    }
  };

  if (!items) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="w-5 h-5 animate-spin" style={{ color: "var(--accent)" }} />
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto space-y-5" data-testid="mobile-packs">
      <div>
        <div className="overline mb-2">on this phone</div>
        <h1 className="font-serif text-3xl" style={{ color: "var(--text-primary)" }}>Packs</h1>
        <p className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>
          {note || "Only packs you already use on the desktop show up here, plus phone calls."}
        </p>
      </div>

      <div className="space-y-3">
        {items.map((item) => {
          const Icon = item.id === "phone_calls" ? Phone : Puzzle;
          return (
            <div
              key={item.id}
              className="rounded-md border p-4 flex items-start gap-3"
              style={{
                background: "var(--surface)",
                borderColor: item.phone_enabled ? "var(--accent)" : "var(--border-default)",
              }}
              data-testid={`mobile-pack-${item.id}`}
            >
              <Icon className="w-4 h-4 mt-1 shrink-0" style={{ color: "var(--accent)" }} />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{item.name}</div>
                <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{item.tagline}</p>
                {item.id === "phone_calls" && (
                  <Link to="/m/call" className="text-xs underline mt-2 inline-block" style={{ color: "var(--accent)" }}>
                    Open the dialer
                  </Link>
                )}
              </div>
              <button
                type="button"
                onClick={() => toggle(item)}
                disabled={busy === item.id}
                data-testid={`mobile-pack-toggle-${item.id}`}
                className="text-xs px-3 py-1.5 rounded-full shrink-0"
                style={{
                  background: item.phone_enabled ? "var(--accent)" : "var(--surface-elev)",
                  color: item.phone_enabled ? "var(--surface)" : "var(--text-muted)",
                }}
              >
                {busy === item.id ? "…" : item.phone_enabled ? "On" : "Off"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
