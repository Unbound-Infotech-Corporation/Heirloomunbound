import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { toast } from "sonner";
import { api } from "../lib/api";

// Owner page: pair the Heirloom phone app (mobile/) with this box, and remove phones.
export default function MobileApp() {
  const [pair, setPair] = useState(null);
  const [qr, setQr] = useState("");
  const [phones, setPhones] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = () =>
    api
      .get("/mobile/devices")
      .then(({ data }) => setPhones(data.devices || []))
      .catch(() => {});

  useEffect(() => {
    load();
  }, []);

  const start = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/mobile/pair/start", {});
      setPair(data);
      setQr(await QRCode.toDataURL(data.qr, { margin: 1, width: 260 }));
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id) => {
    try {
      await api.delete(`/mobile/devices/${id}`);
      toast.success("Phone removed");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    }
  };

  return (
    <div className="min-h-screen px-5 py-10 max-w-xl mx-auto" style={{ background: "var(--bg-base)" }} data-testid="mobile-app-root">
      <p className="overline mb-2">Heirloom · phone app</p>
      <h1 className="font-serif text-3xl mb-3">Pair a phone</h1>
      <p className="text-sm mb-6" style={{ color: "var(--text-muted)", lineHeight: 1.45 }}>
        Open the Heirloom app on your phone and scan this code. The phone talks only to this box:
        your Twin, its memory and its voice stay here.
      </p>
      {pair ? (
        <div data-testid="mobile-pair-code">
          {qr && <img src={qr} alt="Pairing QR code" width={260} height={260} className="mb-4 rounded" />}
          <p className="text-sm">Or type in the app:</p>
          <p className="font-mono text-lg mt-1">{pair.box}</p>
          <p className="font-mono text-3xl tracking-widest mt-1">{pair.code}</p>
          <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
            Works once, for 10 minutes.
          </p>
        </div>
      ) : (
        <button className="studio-btn studio-btn-primary" onClick={start} disabled={busy} data-testid="mobile-pair-start">
          {busy ? "Making a code…" : "Show pairing code"}
        </button>
      )}
      <h2 className="font-serif text-xl mt-10 mb-3">Paired phones</h2>
      {phones.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>None yet.</p>
      ) : (
        <ul className="space-y-2">
          {phones.map((p) => (
            <li key={p.device_id} className="flex items-center justify-between">
              <span>
                {p.name} <span className="text-xs" style={{ color: "var(--text-muted)" }}>({p.platform})</span>
              </span>
              <button className="studio-btn" onClick={() => remove(p.device_id)}>Remove</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
