import { useEffect, useState } from "react";
import { Calendar, Copy, Heart, Plus, ShieldAlert, Trash2, Unlock } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";

const empty = {
  name: "",
  email: "",
  relationship: "",
  note: "",
  release_on: "",
  inactivity_days: "",
};

export default function Heirs() {
  const [heirs, setHeirs] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [draft, setDraft] = useState(empty);
  const [releasedLinks, setReleasedLinks] = useState({}); // heir_id -> full URL

  const portalOrigin =
    typeof window !== "undefined" ? window.location.origin : "";

  const load = () => api.get("/heirs").then(({ data }) => setHeirs(data));
  useEffect(() => {
    load();
  }, []);

  const submit = async () => {
    if (!draft.name.trim() || !draft.email.trim()) return;
    try {
      await api.post("/heirs", {
        name: draft.name,
        email: draft.email,
        relationship: draft.relationship,
        note: draft.note,
        release_on: draft.release_on || null,
        inactivity_days: draft.inactivity_days
          ? parseInt(draft.inactivity_days, 10)
          : null,
      });
      setShowNew(false);
      setDraft(empty);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Remove this heir?")) return;
    await api.delete(`/heirs/${id}`);
    load();
  };

  const checkIn = async () => {
    const { data } = await api.post("/heirs/check-in", {});
    toast.success(`Checked in — ${data.heirs_updated} heir(s) updated`);
    load();
  };

  const checkReleases = async () => {
    const { data } = await api.post("/heirs/check-releases");
    if (data.released.length === 0) {
      toast.info("No releases triggered");
    } else {
      const next = { ...releasedLinks };
      data.released.forEach((r) => {
        next[r.heir_id] = `${portalOrigin}${r.portal_path}`;
      });
      setReleasedLinks(next);
      toast.success(`Released ${data.released.length} heir(s)`);
    }
    load();
  };

  const releaseNow = async (id) => {
    if (
      !window.confirm(
        "Release this heir now? They will be able to view your archive immediately."
      )
    )
      return;
    const { data } = await api.post(`/heirs/${id}/release-now`);
    setReleasedLinks((p) => ({
      ...p,
      [id]: `${portalOrigin}${data.portal_path}`,
    }));
    toast.success("Heir released. Copy the link below.");
    load();
  };

  const revoke = async (id) => {
    if (!window.confirm("Revoke this heir's access? Their portal link will stop working.")) return;
    await api.post(`/heirs/${id}/revoke-release`);
    setReleasedLinks((p) => {
      const n = { ...p };
      delete n[id];
      return n;
    });
    toast.success("Access revoked");
    load();
  };

  const fetchLink = async (id) => {
    try {
      const { data } = await api.get(`/heirs/${id}/release-link`);
      setReleasedLinks((p) => ({
        ...p,
        [id]: `${portalOrigin}${data.portal_path}`,
      }));
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const copyLink = async (url) => {
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Portal link copied");
    } catch (e) {
      toast.error("Copy failed — select & copy manually");
    }
  };

  return (
    <div className="px-10 lg:px-16 py-12 max-w-4xl" data-testid="heirs-root">
      <header className="mb-10 flex justify-between items-end flex-wrap gap-6">
        <div>
          <div className="overline mb-3">the keepers</div>
          <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
            Who do you trust with this?
          </h1>
          <p
            className="mt-3 text-base max-w-2xl"
            style={{ color: "var(--text-secondary)" }}
          >
            Name the people who should be able to sit with your twin one day.
            Set a release date or an inactivity threshold — and check in
            regularly to keep the clock at zero.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={checkIn}
            data-testid="check-in-btn"
            className="inline-flex items-center gap-2 px-4 py-3 text-sm rounded-sm"
            style={{
              border: "1px solid var(--border-default)",
              color: "var(--text-secondary)",
            }}
            title="Reset inactivity timers for all heirs"
          >
            <Heart className="h-4 w-4" /> I'm here
          </button>
          <button
            onClick={checkReleases}
            data-testid="check-releases-btn"
            className="inline-flex items-center gap-2 px-4 py-3 text-sm rounded-sm"
            style={{
              border: "1px solid var(--border-default)",
              color: "var(--text-secondary)",
            }}
            title="Run release check now"
          >
            <ShieldAlert className="h-4 w-4" /> Check triggers
          </button>
          <button
            onClick={() => setShowNew((s) => !s)}
            data-testid="new-heir-toggle"
            className="inline-flex items-center gap-2 px-5 py-3 text-sm rounded-sm"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            <Plus className="h-4 w-4" /> Add heir
          </button>
        </div>
      </header>

      {showNew && (
        <div className="surface p-6 mb-10 space-y-4">
          <input
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            placeholder="Name (e.g. Elias — my son)"
            data-testid="heir-name"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <input
            value={draft.email}
            onChange={(e) => setDraft({ ...draft, email: e.target.value })}
            placeholder="Email"
            type="email"
            data-testid="heir-email"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <input
            value={draft.relationship}
            onChange={(e) => setDraft({ ...draft, relationship: e.target.value })}
            placeholder="Relationship (son, partner, friend…)"
            data-testid="heir-rel"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <textarea
            value={draft.note}
            onChange={(e) => setDraft({ ...draft, note: e.target.value })}
            placeholder="A private note to them (read only after release)"
            rows={4}
            data-testid="heir-note"
            className="w-full px-3 py-2 text-sm rounded-sm leading-relaxed"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="overline block mb-2">release date (optional)</label>
              <input
                type="date"
                value={draft.release_on}
                onChange={(e) => setDraft({ ...draft, release_on: e.target.value })}
                data-testid="heir-release"
                className="w-full px-3 py-2 text-sm rounded-sm font-mono"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              />
            </div>
            <div>
              <label className="overline block mb-2">release after N days of inactivity</label>
              <input
                type="number"
                min="1"
                max="3650"
                value={draft.inactivity_days}
                onChange={(e) => setDraft({ ...draft, inactivity_days: e.target.value })}
                placeholder="e.g. 90"
                data-testid="heir-inactivity"
                className="w-full px-3 py-2 text-sm rounded-sm font-mono"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              />
            </div>
          </div>
          <p className="text-xs italic" style={{ color: "var(--text-muted)" }}>
            Tip: Press "I'm here" any time to reset the inactivity clock. If you
            stop checking in, the heir is automatically released after the threshold.
          </p>
          <div className="flex justify-end gap-3">
            <button
              onClick={() => setShowNew(false)}
              className="px-4 py-2 text-sm rounded-sm"
              style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
            >
              Cancel
            </button>
            <button
              onClick={submit}
              data-testid="heir-submit"
              className="px-4 py-2 text-sm rounded-sm"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              Add heir
            </button>
          </div>
        </div>
      )}

      {heirs.length === 0 ? (
        <div className="surface p-12 text-center" data-testid="heirs-empty">
          <div className="overline mb-3">no heirs yet</div>
          <p className="font-serif text-2xl" style={{ color: "var(--text-secondary)" }}>
            Begin with one person.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {heirs.map((h) => (
            <div key={h.heir_id} className="surface p-6" data-testid={`heir-${h.heir_id}`}>
              <div className="flex justify-between items-start gap-4">
                <div className="flex-1">
                  <div className="overline mb-1">
                    {h.relationship || "trusted"}
                    {h.released && (
                      <span
                        className="ml-2 px-2 py-0.5 rounded-sm text-[10px]"
                        style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
                      >
                        RELEASED
                      </span>
                    )}
                  </div>
                  <h3 className="font-serif text-2xl mb-1">{h.name}</h3>
                  <div className="text-sm font-mono" style={{ color: "var(--text-muted)" }}>
                    {h.email}
                  </div>
                  {h.note && (
                    <p className="text-sm mt-3 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                      "{h.note}"
                    </p>
                  )}
                  <div className="flex gap-6 mt-3 text-xs" style={{ color: "var(--text-muted)" }}>
                    {h.release_on && (
                      <span className="inline-flex items-center gap-1">
                        <Calendar className="h-3 w-3" /> on {h.release_on}
                      </span>
                    )}
                    {h.inactivity_days && (
                      <span>after {h.inactivity_days} days inactive</span>
                    )}
                    {h.released_at && <span>released {h.released_at.slice(0, 10)}</span>}
                  </div>
                </div>
                <button
                  onClick={() => remove(h.heir_id)}
                  data-testid={`delete-heir-${h.heir_id}`}
                  className="p-2"
                >
                  <Trash2 className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
                </button>
              </div>

              <div className="flex flex-wrap gap-2 mt-4">
                {!h.released ? (
                  <button
                    onClick={() => releaseNow(h.heir_id)}
                    data-testid={`release-now-${h.heir_id}`}
                    className="px-3 py-1.5 text-xs rounded-sm inline-flex items-center gap-1.5"
                    style={{ border: "1px solid var(--accent)", color: "var(--accent)" }}
                  >
                    <Unlock className="h-3 w-3" /> Release now
                  </button>
                ) : (
                  <>
                    {!releasedLinks[h.heir_id] && (
                      <button
                        onClick={() => fetchLink(h.heir_id)}
                        className="px-3 py-1.5 text-xs rounded-sm"
                        style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                      >
                        Show portal link
                      </button>
                    )}
                    <button
                      onClick={() => revoke(h.heir_id)}
                      data-testid={`revoke-${h.heir_id}`}
                      className="px-3 py-1.5 text-xs rounded-sm"
                      style={{ border: "1px solid var(--border-default)", color: "var(--text-muted)" }}
                    >
                      Revoke access
                    </button>
                  </>
                )}
              </div>

              {releasedLinks[h.heir_id] && (
                <div
                  className="mt-3 p-3 rounded-sm flex items-center gap-2"
                  style={{ background: "var(--bg-elevated)", border: "1px solid var(--accent)" }}
                >
                  <input
                    readOnly
                    value={releasedLinks[h.heir_id]}
                    className="flex-1 text-xs font-mono bg-transparent outline-none"
                    style={{ color: "var(--text-primary)" }}
                    data-testid={`portal-url-${h.heir_id}`}
                  />
                  <button
                    onClick={() => copyLink(releasedLinks[h.heir_id])}
                    className="px-3 py-1 text-xs rounded-sm inline-flex items-center gap-1"
                    style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
                  >
                    <Copy className="h-3 w-3" /> Copy
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
