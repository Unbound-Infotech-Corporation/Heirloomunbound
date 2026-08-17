import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { api } from "../lib/api";

export default function PhonePair() {
  const [params] = useSearchParams();
  const [code, setCode] = useState(params.get("code") || "");
  const [name, setName] = useState("My phone");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const [features, setFeatures] = useState(["twin", "capture", "journal", "reminders"]);
  const [catalog, setCatalog] = useState([]);

  useEffect(() => {
    api
      .get("/studio/first-run")
      .then(({ data }) => {
        setCatalog((data.catalog?.phone_features || []).filter((f) => !f.pc_only));
        if (data.settings?.phone_features?.length) setFeatures(data.settings.phone_features);
      })
      .catch(() => {});
  }, []);

  const claim = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { data } = await api.post("/studio/first-run/pair/claim", {
        code: code.trim(),
        name,
        phone_features: features,
      });
      setDone(data);
      toast.success("Phone connected");
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen px-5 py-10" style={{ background: "var(--bg-base)" }} data-testid="phone-pair-root">
      <p className="overline mb-2">Heirloom · phone</p>
      <h1 className="font-serif text-3xl mb-3">Connect this phone</h1>
      <p className="text-sm mb-6" style={{ color: "var(--text-muted)", lineHeight: 1.45 }}>
        Sign in with the same account as your dedicated PC. Models stay on that machine; this
        phone is a remote control for the features you enable.
      </p>

      {done ? (
        <div data-testid="phone-pair-done">
          <p style={{ color: "#7da06f" }}>Paired as {done.name}.</p>
          <p className="text-sm mt-2">Features: {(done.phone_features || []).join(", ")}</p>
          <a className="studio-btn studio-btn-primary inline-block mt-4" href="/twin">
            Open twin
          </a>
        </div>
      ) : (
        <form onSubmit={claim} className="max-w-md space-y-4">
          <label className="block text-sm">
            Pairing code from the PC
            <input
              className="block w-full mt-1"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              data-testid="phone-pair-code"
              required
            />
          </label>
          <label className="block text-sm">
            Name this phone
            <input
              className="block w-full mt-1"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <fieldset>
            <legend className="text-sm mb-2">Features on this phone</legend>
            {catalog.map((f) => (
              <label key={f.id} className="flex gap-2 mb-2 text-sm">
                <input
                  type="checkbox"
                  checked={features.includes(f.id)}
                  onChange={(e) =>
                    setFeatures((cur) =>
                      e.target.checked ? [...cur, f.id] : cur.filter((id) => id !== f.id)
                    )
                  }
                />
                {f.label}
              </label>
            ))}
          </fieldset>
          <button type="submit" className="studio-btn studio-btn-primary" disabled={busy} data-testid="phone-pair-claim">
            {busy ? "Connecting…" : "Connect"}
          </button>
        </form>
      )}
    </div>
  );
}
