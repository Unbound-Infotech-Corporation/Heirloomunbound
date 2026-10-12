import PresencePanel from "../components/studio/PresencePanel";

export default function Presence() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8" data-testid="presence-page">
      <div className="overline mb-2">twin box</div>
      <h1 className="font-serif text-3xl mb-2" style={{ color: "var(--text-primary)" }}>
        Presence
      </h1>
      <PresencePanel showIntro />
    </div>
  );
}
