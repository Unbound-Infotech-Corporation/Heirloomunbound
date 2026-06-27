import { useEffect, useState } from "react";
import { RefreshCw, Sparkles, Heart, Users, BookOpen, MessageSquareQuote, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";

const TRAIT_LABELS = {
  openness: "Openness",
  conscientiousness: "Conscientiousness",
  extraversion: "Extraversion",
  agreeableness: "Agreeableness",
  neuroticism: "Neuroticism",
};

export default function Personality() {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/personality/profile");
      setProfile(data);
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    try {
      const { data } = await api.post("/personality/refresh");
      setProfile(data);
      toast.success("Profile refreshed");
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (loading) {
    return (
      <div className="px-10 lg:px-16 py-12 flex items-center gap-3" data-testid="personality-loading">
        <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--accent)" }} />
        <span className="text-sm" style={{ color: "var(--text-muted)" }}>
          Reading your archive…
        </span>
      </div>
    );
  }

  if (!profile) return null;
  const bigfive = profile.bigfive || {};
  const empty = (profile.entry_count || 0) === 0;

  return (
    <div className="px-10 lg:px-16 py-12 max-w-4xl" data-testid="personality-root">
      <header className="mb-10 flex justify-between items-end flex-wrap gap-6">
        <div>
          <div className="overline mb-3">your portrait</div>
          <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
            This is who the twin thinks you are.
          </h1>
          <p className="mt-3 text-base max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            A live portrait drawn from your archive. It updates as you write more. If something feels off, refresh — or write more honestly.
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          data-testid="personality-refresh"
          className="inline-flex items-center gap-2 px-4 py-3 text-sm rounded-sm disabled:opacity-50"
          style={{ border: "1px solid var(--accent)", color: "var(--accent)" }}
        >
          {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {refreshing ? "Refreshing…" : "Refresh from archive"}
        </button>
      </header>

      {empty ? (
        <div className="surface p-12 text-center" data-testid="personality-empty">
          <Sparkles className="h-8 w-8 mx-auto mb-3" style={{ color: "var(--text-muted)" }} />
          <p className="font-serif text-2xl mb-3" style={{ color: "var(--text-secondary)" }}>
            Nothing in your archive yet.
          </p>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            Start with the AI Interviewer, voice journal, or a single memory in the Library.
          </p>
        </div>
      ) : (
        <>
          {/* Summary */}
          {profile.summary && (
            <section
              className="surface p-7 mb-10 grain-overlay"
              data-testid="personality-summary"
            >
              <div className="overline mb-3 flex items-center gap-2">
                <MessageSquareQuote className="h-3.5 w-3.5" /> in three sentences
              </div>
              <blockquote
                className="font-serif text-2xl lg:text-3xl leading-snug border-l-2 pl-6 py-1"
                style={{
                  borderColor: "var(--accent)",
                  color: "var(--text-primary)",
                }}
              >
                {profile.summary}
              </blockquote>
            </section>
          )}

          {/* Big Five */}
          <section className="mb-10" data-testid="personality-bigfive">
            <div className="overline mb-4">the big five</div>
            <h2 className="font-serif text-2xl mb-6">How you tilt</h2>
            <div className="space-y-4">
              {Object.entries(TRAIT_LABELS).map(([key, label]) => {
                const trait = bigfive[key] || {};
                const score = Math.max(0, Math.min(100, trait.score ?? 50));
                return (
                  <div key={key} className="surface p-5" data-testid={`bigfive-${key}`}>
                    <div className="flex justify-between items-baseline mb-2">
                      <div className="font-serif text-lg">{label}</div>
                      <div
                        className="font-mono text-sm"
                        style={{ color: "var(--text-muted)" }}
                      >
                        {score}
                      </div>
                    </div>
                    <div
                      className="h-1.5 rounded-full overflow-hidden mb-3"
                      style={{ background: "var(--bg-base)" }}
                    >
                      <div
                        className="h-full transition-all"
                        style={{
                          width: `${score}%`,
                          background: "var(--accent)",
                        }}
                      />
                    </div>
                    {trait.reason && (
                      <p
                        className="text-sm leading-relaxed italic"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        {trait.reason}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          {/* Values + Themes */}
          <div className="grid md:grid-cols-2 gap-6 mb-10">
            <section className="surface p-6" data-testid="personality-values">
              <div className="overline mb-3 flex items-center gap-2">
                <Heart className="h-3.5 w-3.5" /> top values
              </div>
              <ul className="space-y-2">
                {(profile.top_values || []).map((v, i) => (
                  <li key={i} className="font-serif text-lg" style={{ color: "var(--text-primary)" }}>
                    {v}
                  </li>
                ))}
              </ul>
            </section>
            <section className="surface p-6" data-testid="personality-themes">
              <div className="overline mb-3 flex items-center gap-2">
                <BookOpen className="h-3.5 w-3.5" /> life themes
              </div>
              <ul className="space-y-2">
                {(profile.life_themes || []).map((v, i) => (
                  <li key={i} className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                    · {v}
                  </li>
                ))}
              </ul>
            </section>
          </div>

          {/* Voice tone */}
          {profile.voice_tone?.description && (
            <section className="surface p-7 mb-10" data-testid="personality-tone">
              <div className="overline mb-3">your voice</div>
              <p
                className="text-base leading-relaxed mb-5"
                style={{ color: "var(--text-primary)" }}
              >
                {profile.voice_tone.description}
              </p>
              {(profile.voice_tone.signature_phrases || []).length > 0 && (
                <div>
                  <div className="overline mb-2">signature phrases</div>
                  <div className="flex flex-wrap gap-2">
                    {profile.voice_tone.signature_phrases.map((p, i) => (
                      <span
                        key={i}
                        className="px-3 py-1.5 text-sm font-serif rounded-sm"
                        style={{
                          background: "var(--accent-muted)",
                          color: "var(--text-primary)",
                          border: "1px solid var(--accent)",
                        }}
                      >
                        "{p}"
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}

          {/* Key relationships */}
          {(profile.key_relationships || []).length > 0 && (
            <section className="mb-10" data-testid="personality-rels">
              <div className="overline mb-4 flex items-center gap-2">
                <Users className="h-3.5 w-3.5" /> the people in your archive
              </div>
              <div className="grid md:grid-cols-2 gap-3">
                {profile.key_relationships.map((r, i) => (
                  <div key={i} className="surface p-4">
                    <div className="font-serif text-base mb-0.5">{r.name}</div>
                    <div className="overline mb-2">{r.role}</div>
                    {r.note && (
                      <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                        {r.note}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          <p className="text-xs italic" style={{ color: "var(--text-muted)" }}>
            Drawn from {profile.entry_count} archive {profile.entry_count === 1 ? "entry" : "entries"}, generated {new Date(profile.generated_at).toLocaleString()}.
          </p>
        </>
      )}
    </div>
  );
}
