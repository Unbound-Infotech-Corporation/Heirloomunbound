import ObserverPanel from "../components/studio/ObserverPanel";

export default function Observer() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8" data-testid="observer-page">
      <div className="overline mb-2">twin box</div>
      <h1 className="font-serif text-3xl mb-2" style={{ color: "var(--text-primary)" }}>
        Observer
      </h1>
      <ObserverPanel showIntro />
    </div>
  );
}
