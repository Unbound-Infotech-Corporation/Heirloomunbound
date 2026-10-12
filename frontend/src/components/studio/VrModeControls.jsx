import { Headset } from "lucide-react";

const buttonStyle = (on) => ({
  border: "1px solid var(--border-default)",
  background: on ? "var(--accent)" : "transparent",
  color: on ? "var(--text-inverse)" : "inherit",
});

export default function VrModeControls({
  enabled = false,
  gazeEnabled = false,
  sessionActive = false,
  onToggleVr,
  onToggleGaze,
  onEnter,
  onLeave,
  note = "",
  testid = "vr-mode",
}) {
  return (
    <div className="vr-mode flex flex-wrap items-center gap-2" data-testid={testid}>
      <button
        type="button"
        data-testid={`${testid}-toggle`}
        aria-pressed={enabled}
        onClick={() => onToggleVr?.(!enabled)}
        className="text-xs px-3 py-1 rounded-sm inline-flex items-center gap-1.5"
        style={buttonStyle(enabled)}
      >
        <Headset className="h-3.5 w-3.5" />
        {enabled ? "VR on" : "VR off"}
      </button>
      <button
        type="button"
        data-testid={`${testid}-gaze`}
        aria-pressed={gazeEnabled}
        onClick={() => onToggleGaze?.(!gazeEnabled)}
        className="text-xs px-3 py-1 rounded-sm"
        style={buttonStyle(gazeEnabled)}
      >
        {gazeEnabled ? "Eye tracking on" : "Eye tracking off"}
      </button>
      {enabled && !sessionActive && onEnter ? (
        <button
          type="button"
          data-testid={`${testid}-enter`}
          onClick={() => onEnter?.()}
          className="text-xs px-3 py-1 rounded-sm"
          style={buttonStyle(false)}
        >
          Enter headset
        </button>
      ) : null}
      {sessionActive && onLeave ? (
        <button
          type="button"
          data-testid={`${testid}-leave`}
          onClick={() => onLeave?.()}
          className="text-xs px-3 py-1 rounded-sm"
          style={buttonStyle(false)}
        >
          Leave headset
        </button>
      ) : null}
      {note ? (
        <p className="w-full text-xs" style={{ color: "var(--text-muted)" }} data-testid={`${testid}-note`}>
          {note}
        </p>
      ) : null}
    </div>
  );
}
