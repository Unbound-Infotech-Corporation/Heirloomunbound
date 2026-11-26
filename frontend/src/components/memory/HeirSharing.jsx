import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "../../lib/api";
import { SHARE_COPY, sharedCount } from "../../lib/cardSharing";
import CardSharingList from "./CardSharingList";
import FamilyNamesFields from "./FamilyNamesFields";

// Owner control for "who can hear each memory". Used on the Memory page and in card review.
// `version` changes when the parent approved cards, so the list reloads.
export default function HeirSharing({ version = 0, showNames = true }) {
  const [cards, setCards] = useState([]);
  const [heirs, setHeirs] = useState([]);
  const [defaultOn, setDefaultOn] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const [c, h, d] = await Promise.all([
        api.get("/life-story/cards", { params: { status: "approved" } }),
        api.get("/heirs"),
        api.get("/memory-loop/sharing"),
      ]);
      setCards(c.data.cards || []);
      setHeirs(h.data || []);
      setDefaultOn(!!d.data.share_new_cards);
    } catch (e) {
      setError(e.response?.data?.detail || "Could not load your shared memories.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load, version]);

  const onShare = async (cardIds, payload) => {
    setBusy(true);
    try {
      await api.post("/memory-loop/cards/share", { card_ids: [...new Set(cardIds)], ...payload });
      const label = payload.visibility === "owner" ? "Stopped sharing" : "Shared";
      toast.success(`${label} ${cardIds.length} ${cardIds.length === 1 ? "memory" : "memories"}`);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const toggleDefault = async (on) => {
    setDefaultOn(on);
    try {
      await api.put("/memory-loop/sharing", { share_new_cards: on });
    } catch (e) {
      setDefaultOn(!on);
      toast.error(e.response?.data?.detail || "That did not save.");
    }
  };

  const saveNames = async (heirId, names) => {
    try {
      const { data } = await api.put(`/heirs/${heirId}/names`, { names });
      setHeirs((rows) => rows.map((h) => (h.heir_id === heirId ? { ...h, names: data.names } : h)));
      toast.success("Names saved");
    } catch (e) {
      toast.error(e.response?.data?.detail || "That did not save.");
    }
  };

  return (
    <section data-testid="heir-sharing">
      <div className="overline mb-3">who can hear it</div>
      <h2 className="font-serif text-2xl mb-2">Share memories with your heirs.</h2>
      <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
        Approved memories stay private to you until you share them. {cards.length ? `${sharedCount(cards)} of ${cards.length} shared.` : ""}
      </p>
      <label className="surface p-4 mb-4 flex items-start gap-3 min-h-[44px]" data-testid="share-default">
        <input type="checkbox" className="mt-1 h-5 w-5 shrink-0" checked={defaultOn} onChange={(e) => toggleDefault(e.target.checked)} data-testid="share-default-toggle" />
        <span>
          <span className="block text-base">{SHARE_COPY.defaultLabel}</span>
          <span className="block text-xs mt-1" style={{ color: "var(--text-muted)" }}>{SHARE_COPY.defaultHelp}</span>
        </span>
      </label>
      {loading ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }} data-testid="share-loading">Loading…</p>
      ) : error ? (
        <div className="surface p-6" data-testid="share-load-error">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{error}</p>
          <button type="button" className="mt-3 px-4 py-2 min-h-[44px] text-sm rounded-sm" style={{ border: "1px solid var(--accent)", color: "var(--accent)" }} onClick={load}>
            Try again
          </button>
        </div>
      ) : (
        <>
          <CardSharingList cards={cards} heirs={heirs} onShare={onShare} busy={busy} />
          {showNames ? <FamilyNamesFields heirs={heirs} onSave={saveNames} /> : null}
        </>
      )}
    </section>
  );
}
