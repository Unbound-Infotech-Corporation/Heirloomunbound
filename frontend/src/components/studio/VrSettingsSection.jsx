import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { VR_LAUNCH_NOTE } from "../../lib/vrMode";
import { applyRoomGaze, applyRoomVrToggle, loadOwnerVr, saveOwnerVr } from "../../lib/vrRoom";
import VrModeControls from "./VrModeControls";

/** Settings persist the switches. They do not start a WebXR session. */
export default function VrSettingsSection() {
  const { user } = useAuth();
  const heir = Boolean(user?.heir_surface) || user?.audience === "heir";
  const userId = user?.user_id || "owner";
  const [prefs, setPrefs] = useState({ enabled: false, gazeEnabled: false });
  const [note, setNote] = useState(VR_LAUNCH_NOTE);

  useEffect(() => {
    if (heir) return undefined;
    let cancelled = false;
    loadOwnerVr(api, userId, window.localStorage).then((launched) => {
      if (cancelled) return;
      setPrefs({ enabled: Boolean(launched.enabled), gazeEnabled: Boolean(launched.gazeEnabled) });
    });
    return () => {
      cancelled = true;
    };
  }, [heir, userId]);

  if (heir) return null;

  const save = (next) => saveOwnerVr(api, userId, window.localStorage, next);

  return (
    <section className="surface p-7 mb-6" data-testid="settings-vr">
      <div className="overline mb-4">room vr</div>
      <h2 className="font-serif text-2xl mb-2">Headset in the Room</h2>
      <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
        Off until you turn it on. Saving it here does not put the headset on.
        Open a Room and use Enter headset when you want the visor.
      </p>
      <VrModeControls
        testid="settings-vr-mode"
        enabled={prefs.enabled}
        gazeEnabled={prefs.gazeEnabled}
        sessionActive={false}
        note={note}
        onToggleVr={async (nextEnabled) => {
          const result = await applyRoomVrToggle({
            prefs,
            nextEnabled,
            gesture: true,
            surface: "settings",
            sessionActive: false,
            save,
          });
          setPrefs(result.prefs);
          setNote(nextEnabled
            ? "Saved. The Room stays on this screen until you enter from there."
            : "VR is off. The Room stays on the normal screen.");
        }}
        onToggleGaze={async (nextGaze) => {
          const result = await applyRoomGaze({ prefs, nextGaze, gesture: true, save });
          setPrefs(result.prefs);
          setNote(nextGaze
            ? "Eye tracking is opt-in. PSVR2 on PC does not expose it, so nothing is sent until a runtime does."
            : "Eye tracking is off. No attention notes are sent.");
        }}
      />
    </section>
  );
}
