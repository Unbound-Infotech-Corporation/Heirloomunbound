import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "../../lib/api";
import { memorialFormFrom, memorialPayload, memorialStatusLine } from "../../lib/memorialMode";
import StudioFieldRow from "./StudioFieldRow";
import StudioPanel from "./StudioPanel";

export default function MemorialModePanel() {
  const [form, setForm] = useState(null);
  const [events, setEvents] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [{ data: memorial }, { data: flags }] = await Promise.all([
      api.get("/studio/memorial"),
      api.get("/studio/safety-events"),
    ]);
    setForm(memorialFormFrom(memorial.settings || {}));
    setEvents(flags.events || []);
  }, []);

  useEffect(() => {
    load().catch(() => toast.error("Could not load memorial settings"));
  }, [load]);

  const save = async () => {
    setBusy(true);
    try {
      await api.put("/studio/memorial", memorialPayload(form));
      toast.success(form.mode === "posthumous" ? "Memorial mode saved" : "Living mode saved");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    } finally {
      setBusy(false);
    }
  };

  if (!form) {
    return (
      <StudioPanel title="Memorial mode" testId="memorial-loading">
        <p className="text-xs" style={{ color: "#888" }}>
          Loading…
        </p>
      </StudioPanel>
    );
  }

  const set = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));

  return (
    <StudioPanel title="Memorial mode" testId="memorial-mode">
      <p className="text-xs" style={{ color: "#888", marginBottom: 8 }}>
        {memorialStatusLine(memorialPayload(form))}
      </p>
      <StudioFieldRow label="Mode" hint="Heirs hear this">
        <select
          aria-label="Memorial mode"
          data-testid="memorial-mode-select"
          value={form.mode}
          onChange={set("mode")}
        >
          <option value="living">Living</option>
          <option value="posthumous">Posthumous</option>
        </select>
      </StudioFieldRow>
      <StudioFieldRow label="Date" hint="Optional">
        <input
          aria-label="Memorial date"
          data-testid="memorial-date"
          type="date"
          value={form.date || ""}
          onChange={set("date")}
        />
      </StudioFieldRow>
      <StudioFieldRow label="Contact" hint="Sees crisis flags">
        <input
          aria-label="Designated contact name"
          placeholder="Name"
          value={form.contactName}
          onChange={set("contactName")}
        />
      </StudioFieldRow>
      <StudioFieldRow label="Email">
        <input
          aria-label="Designated contact email"
          placeholder="ada@example.com"
          value={form.contactEmail}
          onChange={set("contactEmail")}
        />
      </StudioFieldRow>
      <StudioFieldRow label="Long sitting" hint="User turns">
        <input
          aria-label="Long session turns"
          type="number"
          min="8"
          max="400"
          value={form.longSessionTurns}
          onChange={set("longSessionTurns")}
        />
      </StudioFieldRow>
      <StudioFieldRow label="Sittings a day">
        <input
          aria-label="Sessions per day"
          type="number"
          min="2"
          max="100"
          value={form.sessionsPerDay}
          onChange={set("sessionsPerDay")}
        />
      </StudioFieldRow>
      <StudioFieldRow label="Long sitting" hint="Minutes, with enough turns">
        <input
          aria-label="Long session minutes"
          type="number"
          min="20"
          max="720"
          value={form.longSessionMinutes}
          onChange={set("longSessionMinutes")}
        />
      </StudioFieldRow>
      <button type="button" className="studio-btn" data-testid="memorial-save" disabled={busy} onClick={save}>
        {busy ? "Saving…" : "Save memorial mode"}
      </button>
      <div className="text-xs" style={{ marginTop: 12 }} data-testid="safety-events">
        <div style={{ marginBottom: 4 }}>Crisis flags</div>
        {events.length === 0 ? (
          <p style={{ color: "#888" }}>No flagged messages.</p>
        ) : (
          <ul style={{ margin: 0, paddingLeft: 16 }}>
            {events.map((event) => (
              <li key={event.event_id || event.created_at}>
                {event.created_at} · {event.surface} · {event.note}
              </li>
            ))}
          </ul>
        )}
      </div>
    </StudioPanel>
  );
}
