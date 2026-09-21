import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Headset } from "lucide-react";
import { coachHref, headsetHintFromUa } from "../../lib/vrCompat";
import { enterRoomVr, probeBrowserXr } from "../../lib/vrRuntime";

export default function VrEnterButton({ testid = "room-sit-xr", onResult }) {
  const [busy, setBusy] = useState(false);
  const [probe, setProbe] = useState(null);

  useEffect(() => {
    probeBrowserXr()
      .then(setProbe)
      .catch(() => setProbe(null));
  }, []);

  const go = async () => {
    setBusy(true);
    try {
      const result = await enterRoomVr();
      onResult?.(result);
      if (result?.session) {
        result.session.addEventListener("end", () => onResult?.({ ok: false, reason: "", ended: true }));
      }
    } finally {
      setBusy(false);
    }
  };

  const hint = probe?.headsetHint;
  const ready = Boolean(probe?.immersiveVr);

  return (
    <div className="vr-enter" data-testid={`${testid}-wrap`}>
      <button
        type="button"
        data-testid={testid}
        onClick={go}
        disabled={busy}
        className="text-xs px-3 py-1 rounded-sm inline-flex items-center gap-1.5 disabled:opacity-50"
        style={{
          border: "1px solid var(--border-default)",
          background: ready ? "var(--accent)" : "transparent",
          color: ready ? "var(--text-inverse)" : "inherit",
        }}
      >
        <Headset className="h-3.5 w-3.5" />
        {busy ? "Starting…" : "Enter in VR"}
      </button>
      <Link
        to={coachHref(hint?.id)}
        className="text-xs"
        style={{ color: "var(--accent)" }}
        data-testid={`${testid}-coach`}
      >
        VR setup
      </Link>
    </div>
  );
}

export function uaHeadsetName() {
  return headsetHintFromUa(typeof navigator !== "undefined" ? navigator.userAgent : "")?.name || "";
}
