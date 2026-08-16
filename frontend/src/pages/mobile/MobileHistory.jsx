import { useEffect, useState } from "react";
import { Camera, Image as ImageIcon, Loader2, Phone, PhoneIncoming, PhoneOutgoing } from "lucide-react";
import { useOutletContext } from "react-router-dom";
import { api } from "@/lib/api";

/**
 * Mobile History — recent calls + recent memories in a single scroll.
 * Uses the same endpoints the desktop app hits, presented in a phone-native
 * timeline layout.
 */
export default function MobileHistory() {
  const { home } = useOutletContext() || {};
  const [calls, setCalls] = useState([]);
  const [entries, setEntries] = useState([]);
  const [photos, setPhotos] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [c, e, p] = await Promise.all([
          api.get("/twilio/calls?limit=15").catch(() => ({ data: { calls: [] } })),
          api.get("/entries?limit=10").catch(() => ({ data: { entries: [] } })),
          api.get("/photos?limit=10").catch(() => ({ data: { photos: [] } })),
        ]);
        setCalls(c.data.calls || []);
        setEntries(e.data.entries || []);
        setPhotos(p.data.photos || []);
      } finally { setLoading(false); }
    })();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16" data-testid="history-loading">
        <Loader2 className="w-5 h-5 animate-spin" style={{ color: "var(--accent)" }} />
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto space-y-6" data-testid="mobile-history">
      <div className="pt-2">
        <div className="overline mb-2">Timeline</div>
        <h1 className="font-serif text-4xl" style={{ color: "var(--text-primary)" }}>Recent</h1>
        {home?.archive && (
          <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }} data-testid="history-archive-counts">
            {home.archive.entries} memories · {home.archive.photos} photos · {home.archive.calls} calls
            {home.home?.online ? " · home PC online" : " · last synced archive"}
          </p>
        )}
      </div>

      {/* Calls */}
      <section data-testid="history-calls">
        <div className="text-xs uppercase tracking-wide mb-2" style={{ color: "var(--text-muted)" }}>
          Calls
        </div>
        {calls.length === 0 ? (
          <div className="text-sm py-3" style={{ color: "var(--text-muted)" }}>
            No calls yet — the twin&rsquo;s number is quiet.
          </div>
        ) : (
          <div className="rounded-md border overflow-hidden"
               style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
            {calls.map((c, i) => {
              const direction = c.direction || (c.from ? "inbound" : "outbound");
              const Icon = direction === "inbound" ? PhoneIncoming : PhoneOutgoing;
              return (
                <div key={c.call_sid || i}
                     className="flex items-center gap-3 px-4 py-3 border-t"
                     style={{ borderColor: i === 0 ? "transparent" : "var(--border-default)" }}
                     data-testid={`history-call-${i}`}>
                  <Icon className="w-4 h-4" style={{ color: "var(--accent)" }} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm truncate" style={{ color: "var(--text-primary)" }}>
                      {c.from || c.to || "unknown"}
                    </div>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                      {(c.created_at || "").slice(0, 16).replace("T", " ")}
                      {c.duration ? ` · ${c.duration}s` : ""}
                      {c.status ? ` · ${c.status}` : ""}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {entries.length === 0 && photos.length === 0 && calls.length === 0 && (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Nothing yet. Capture a memory or call the twin — it lands in the same archive as your home computer.
        </p>
      )}
      {entries.length > 0 && (
        <section data-testid="history-entries">
          <div className="text-xs uppercase tracking-wide mb-2" style={{ color: "var(--text-muted)" }}>
            Memories
          </div>
          <div className="space-y-2">
            {entries.slice(0, 5).map((e) => (
              <div key={e.entry_id}
                   className="rounded-md border p-3"
                   style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}
                   data-testid={`history-entry-${e.entry_id}`}>
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {(e.created_at || "").slice(0, 10)}
                </div>
                <div className="text-sm mt-1" style={{ color: "var(--text-primary)" }}>
                  {String(e.content || "").slice(0, 200)}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Photos */}
      {photos.length > 0 && (
        <section data-testid="history-photos">
          <div className="text-xs uppercase tracking-wide mb-2" style={{ color: "var(--text-muted)" }}>
            Photos
          </div>
          <div className="grid grid-cols-3 gap-2">
            {photos.slice(0, 6).map((p) => (
              <div key={p.photo_id}
                   className="aspect-square rounded-sm flex items-center justify-center"
                   style={{ background: "var(--surface-elev)" }}
                   data-testid={`history-photo-${p.photo_id}`}>
                <ImageIcon className="w-5 h-5" style={{ color: "var(--text-muted)" }} />
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
