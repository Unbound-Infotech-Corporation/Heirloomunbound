import { useState } from "react";
import { SHARE_COPY, cardMode, pickedIds, sharePayload } from "../../lib/cardSharing";
import ShareBadge from "./ShareBadge";

const btn = { border: "1px solid var(--border-default)", color: "var(--text-primary)" };
const gold = { border: "1px solid var(--accent)", color: "var(--accent)" };
const primary = { background: "var(--accent)", color: "var(--text-inverse)" };
const tap = "px-4 py-2 min-h-[44px] text-sm rounded-sm disabled:opacity-50";

// Approved cards with who-hears badges, a per-card Share control and bulk actions.
// onShare(cardIds, payload) does the saving; this component only collects choices.
export default function CardSharingList({ cards, heirs, onShare, busy = false }) {
  const [picked, setPicked] = useState({});
  const [open, setOpen] = useState("");
  const [bulkPick, setBulkPick] = useState(false);
  const [bulkHeirs, setBulkHeirs] = useState({});
  const [mode, setMode] = useState("none");
  const [heirPick, setHeirPick] = useState({});
  const [error, setError] = useState("");

  const ids = pickedIds(picked);
  const noHeirs = !heirs.length;

  const run = async (cardIds, payload) => {
    setError("");
    try {
      await onShare(cardIds, payload);
      setOpen("");
      setBulkPick(false);
      setPicked({});
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "That did not save.");
    }
  };

  const openCard = (c) => {
    setOpen(open === c.card_id ? "" : c.card_id);
    setMode(cardMode(c));
    setHeirPick(Object.fromEntries((c.heir_ids || []).map((id) => [id, true])));
    setError("");
  };

  const saveCard = (c) => {
    try {
      run([c.card_id], sharePayload(mode, pickedIds(heirPick)));
    } catch (e) {
      setError(e.message);
    }
  };

  if (!cards.length) {
    return (
      <div className="surface p-6" data-testid="share-empty">
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          No approved memories yet. Approve a card and you can choose who hears it here.
        </p>
      </div>
    );
  }

  return (
    <div data-testid="share-list">
      <div className="flex flex-wrap gap-2 mb-3" data-testid="share-bulk-bar">
        <button type="button" className={tap} style={btn} onClick={() => setPicked(Object.fromEntries(cards.map((c) => [c.card_id, true])))} data-testid="share-select-all">
          Select all
        </button>
        <button type="button" className={tap} style={primary} disabled={!ids.length || busy || noHeirs}
          onClick={() => run(ids, sharePayload("all"))} data-testid="share-selected-all">
          Share selected{ids.length ? ` (${ids.length})` : ""} with all heirs
        </button>
        <button type="button" className={tap} style={gold} disabled={!ids.length || busy || noHeirs}
          onClick={() => setBulkPick((v) => !v)} data-testid="share-selected-pick">
          Pick heirs…
        </button>
        <button type="button" className={tap} style={btn} disabled={!ids.length || busy}
          onClick={() => run(ids, sharePayload("none"))} data-testid="unshare-selected">
          Stop sharing selected
        </button>
      </div>
      {bulkPick ? (
        <div className="surface p-4 mb-3" data-testid="share-bulk-heirs">
          <div className="overline mb-2">share the selected with</div>
          <div className="flex flex-wrap gap-3 mb-3">
            {heirs.map((h) => (
              <label key={h.heir_id} className="flex items-center gap-2 text-sm min-h-[44px]">
                <input type="checkbox" checked={!!bulkHeirs[h.heir_id]} onChange={(e) => setBulkHeirs({ ...bulkHeirs, [h.heir_id]: e.target.checked })} />
                {h.name}
              </label>
            ))}
          </div>
          <button type="button" className={tap} style={primary} disabled={!pickedIds(bulkHeirs).length || busy}
            onClick={() => run(ids, sharePayload("some", pickedIds(bulkHeirs)))} data-testid="share-bulk-save">
            Share with these heirs
          </button>
        </div>
      ) : null}
      {noHeirs ? (
        <p className="text-sm mb-3" style={{ color: "var(--text-muted)" }} data-testid="share-no-heirs">
          Add an heir first (Heirs page), then you can share memories with them.
        </p>
      ) : null}
      {error ? <p className="text-sm mb-3" style={{ color: "var(--danger)" }} role="alert" data-testid="share-error">{error}</p> : null}

      <div className="grid gap-3">
        {cards.map((c) => (
          <div key={c.card_id} className="surface p-4" data-testid={`share-card-${c.card_id}`}>
            <div className="flex items-start gap-3">
              <input type="checkbox" className="mt-1.5 h-5 w-5 shrink-0" aria-label={`Select ${c.title}`}
                checked={!!picked[c.card_id]} onChange={(e) => setPicked({ ...picked, [c.card_id]: e.target.checked })}
                data-testid={`share-pick-${c.card_id}`} />
              <div className="flex-1 min-w-0">
                <div className="font-serif text-lg leading-snug break-words">{c.title}</div>
                <p className="text-sm mt-1 line-clamp-2 break-words" style={{ color: "var(--text-secondary)" }}>{c.story}</p>
                <div className="mt-2"><ShareBadge card={c} heirs={heirs} /></div>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 mt-3">
              <button type="button" className={tap} style={gold} onClick={() => openCard(c)} disabled={noHeirs} aria-expanded={open === c.card_id}
                data-testid={`share-open-${c.card_id}`}>
                Share with heirs
              </button>
              {cardMode(c) !== "none" ? (
                <button type="button" className={tap} style={btn} disabled={busy} onClick={() => run([c.card_id], sharePayload("none"))}
                  data-testid={`unshare-${c.card_id}`}>
                  Stop sharing
                </button>
              ) : null}
            </div>
            {open === c.card_id ? (
              <div className="mt-3 p-3 rounded-sm" style={{ background: "var(--bg-elevated)" }} data-testid={`share-panel-${c.card_id}`}>
                {[["none", "Only me"], ["all", "All heirs"], ["some", "Pick heirs"]].map(([value, label]) => (
                  <label key={value} className="flex items-center gap-2 text-sm min-h-[44px]">
                    <input type="radio" name={`mode-${c.card_id}`} checked={mode === value} onChange={() => setMode(value)} data-testid={`share-mode-${value}-${c.card_id}`} />
                    {label}
                  </label>
                ))}
                {mode === "some" ? (
                  <div className="flex flex-wrap gap-3 pl-6 mb-2">
                    {heirs.map((h) => (
                      <label key={h.heir_id} className="flex items-center gap-2 text-sm min-h-[44px]">
                        <input type="checkbox" checked={!!heirPick[h.heir_id]} onChange={(e) => setHeirPick({ ...heirPick, [h.heir_id]: e.target.checked })}
                          data-testid={`share-heir-${h.heir_id}-${c.card_id}`} />
                        {h.name}
                      </label>
                    ))}
                  </div>
                ) : null}
                <button type="button" className={`${tap} mt-1`} style={primary} disabled={busy} onClick={() => saveCard(c)} data-testid={`share-save-${c.card_id}`}>
                  Save
                </button>
              </div>
            ) : null}
          </div>
        ))}
      </div>
      <p className="text-xs mt-4" style={{ color: "var(--text-muted)" }}>{SHARE_COPY.note}</p>
    </div>
  );
}
