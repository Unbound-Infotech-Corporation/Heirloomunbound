import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import HeldFactsList from "../components/memory/HeldFactsList";
import HowWeWorkFields from "../components/memory/HowWeWorkFields";
import SafeTopicsFields from "../components/memory/SafeTopicsFields";
import StandingRoutinesFields from "../components/memory/StandingRoutinesFields";
import { api } from "../lib/api";
import { MEMORY_COPY, nextSafeTopics, pairingFromMe, pairingPayload } from "../lib/memoryStudio";
import { routinesFromMe, routinesPayload } from "../lib/standingRoutines";

export default function Memory() {
  const [facts, setFacts] = useState([]);
  const [factsLoading, setFactsLoading] = useState(true);
  const [factsError, setFactsError] = useState("");
  const [prefsError, setPrefsError] = useState("");
  const [prefsLoading, setPrefsLoading] = useState(true);
  const [safeTopics, setSafeTopics] = useState([]);
  const [newTopic, setNewTopic] = useState("");
  const [pairing, setPairing] = useState(pairingFromMe(null));
  const [routines, setRoutines] = useState(routinesFromMe(null));

  const loadFacts = async () => {
    setFactsLoading(true);
    setFactsError("");
    try {
      const { data } = await api.get("/memory/facts");
      setFacts(data.facts || []);
    } catch (e) {
      setFactsError(e.response?.data?.detail || MEMORY_COPY.factsError);
      setFacts([]);
    } finally {
      setFactsLoading(false);
    }
  };

  const loadPrefs = async () => {
    setPrefsLoading(true);
    setPrefsError("");
    try {
      const { data } = await api.get("/auth/me");
      setSafeTopics(data.safe_topics || []);
      setPairing(pairingFromMe(data));
      setRoutines(routinesFromMe(data));
    } catch (e) {
      setPrefsError(e.response?.data?.detail || MEMORY_COPY.prefsError);
    } finally {
      setPrefsLoading(false);
    }
  };

  useEffect(() => {
    loadFacts();
    loadPrefs();
  }, []);

  const removeFact = async (factId) => {
    try {
      await api.delete(`/memory/facts/${factId}`);
      setFacts((arr) => arr.filter((f) => f.fact_id !== factId));
      toast.success("Fact removed — your twin won't use it anymore");
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const savePairing = async (next) => {
    const payload = pairingPayload(next);
    setPairing(payload);
    try {
      await api.put("/auth/me/preferences", payload);
      toast.success("How we work saved");
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const saveRoutines = async (next) => {
    const payload = routinesPayload(next);
    setRoutines(payload);
    try {
      await api.put("/nudges/routines", payload);
      toast.success("Standing routines saved");
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const addTopic = async () => {
    const t = String(newTopic || "").trim();
    if (!t) return;
    const next = nextSafeTopics(safeTopics, t);
    setSafeTopics(next);
    setNewTopic("");
    try {
      await api.put("/auth/me/preferences", { safe_topics: next });
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const removeTopic = async (t) => {
    const next = safeTopics.filter((x) => x !== t);
    setSafeTopics(next);
    try {
      await api.put("/auth/me/preferences", { safe_topics: next });
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-3xl" data-testid="memory-studio-root">
      <header className="mb-10">
        <div className="overline mb-3">memory studio</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
          What the Twin holds.
        </h1>
        <p className="mt-3 text-base max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          Identity facts, how you pair, standing routines, and the safe-topic fence — visible, editable, with provenance.
          Portrait stays a reading of the archive. This page is the edit surface.
        </p>
      </header>

      <div className="flex flex-wrap gap-3 mb-8 text-xs" style={{ color: "var(--text-muted)" }}>
        <Link to="/owner" className="hover:text-[var(--accent)]" data-testid="memory-link-sit">
          Sit →
        </Link>
        <Link to="/twin" className="hover:text-[var(--accent)]" data-testid="memory-link-twin">
          Twin sitting →
        </Link>
        <Link to="/personality" className="hover:text-[var(--accent)]" data-testid="memory-link-portrait">
          Portrait →
        </Link>
        <Link to="/settings" className="hover:text-[var(--accent)]" data-testid="memory-link-settings">
          Settings →
        </Link>
      </div>

      <HeldFactsList
        facts={facts}
        onRemove={removeFact}
        loading={factsLoading}
        error={factsError}
      />

      {prefsLoading ? (
        <div className="flex items-center gap-3 mb-6" data-testid="memory-prefs-loading">
          <Loader2 className="h-4 w-4 animate-spin" style={{ color: "var(--accent)" }} />
          <span className="text-sm" style={{ color: "var(--text-muted)" }}>Loading how we work…</span>
        </div>
      ) : prefsError ? (
        <div className="surface p-6 mb-6" data-testid="memory-prefs-error">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{prefsError}</p>
          <button
            type="button"
            onClick={loadPrefs}
            data-testid="memory-prefs-retry"
            className="mt-4 px-4 py-2 text-sm rounded-sm"
            style={{ border: "1px solid var(--accent)", color: "var(--accent)" }}
          >
            Try again
          </button>
        </div>
      ) : (
        <>
          <HowWeWorkFields pairing={pairing} onChange={savePairing} />
          <StandingRoutinesFields routines={routines} onChange={saveRoutines} />
          <SafeTopicsFields
            topics={safeTopics}
            newTopic={newTopic}
            onNewTopicChange={setNewTopic}
            onAdd={addTopic}
            onRemove={removeTopic}
          />
        </>
      )}
    </div>
  );
}
