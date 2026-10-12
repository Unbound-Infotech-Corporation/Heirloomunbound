/** VR sit: the twin is across the table. Talk is push-to-talk, then the existing chat and voice. */

export const TWIN_SEAT = { x: 0, y: 1.15, z: -1.6 };
export const PTT_KEYS = new Set(["Space", "KeyV"]);
export const PTT_BUTTONS = [0, 1];

export function controllerPttDown(gamepad) {
  const buttons = gamepad?.buttons || [];
  return PTT_BUTTONS.some((index) => Boolean(buttons[index]?.pressed));
}

export function keyboardPtt(event, { typing = false } = {}) {
  if (!event || typing || event.repeat) return false;
  const tag = event.target?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return false;
  return PTT_KEYS.has(event.code);
}

export function readSessionPtt(session, keysDown) {
  if (keysDown && keysDown.size) return true;
  const sources = session?.inputSources || [];
  return sources.some((source) => controllerPttDown(source?.gamepad));
}

export function seatPannerPosition(seat = TWIN_SEAT) {
  return {
    x: Number(seat?.x) || 0,
    y: Number(seat?.y) || 0,
    z: Number(seat?.z) || 0,
    panningModel: "HRTF",
  };
}

export async function runVrTurn({
  blob,
  audience = "owner",
  heirSurface = false,
  transcribe,
  chat,
  speak,
}) {
  if (String(audience || "owner").toLowerCase() !== "owner" || heirSurface) {
    return { ok: false, reason: "heir", seat: TWIN_SEAT };
  }
  if (!blob) return { ok: false, reason: "empty", seat: TWIN_SEAT };
  const transcript = String((await transcribe(blob)) || "").trim();
  if (!transcript) return { ok: false, reason: "empty", transcript: "", seat: TWIN_SEAT };
  const reply = String((await chat(transcript)) || "").trim();
  if (!reply) return { ok: false, reason: "quiet", transcript, reply: "", seat: TWIN_SEAT };
  let audio = null;
  try {
    audio = await speak(reply);
  } catch {
    audio = null;
  }
  return { ok: true, reason: "ok", transcript, reply, audio, seat: { ...TWIN_SEAT } };
}

export async function playAtSeat(base64, seat = TWIN_SEAT, win) {
  const place = seatPannerPosition(seat);
  const Ctx = win?.AudioContext || win?.webkitAudioContext;
  if (!Ctx || !base64) return { played: false, seat: place };
  const ctx = new Ctx();
  const binary = win?.atob ? win.atob(base64) : atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  const buffer = await ctx.decodeAudioData(bytes.buffer);
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  const panner = ctx.createPanner();
  panner.panningModel = place.panningModel;
  if (panner.positionX) {
    panner.positionX.value = place.x;
    panner.positionY.value = place.y;
    panner.positionZ.value = place.z;
  } else if (typeof panner.setPosition === "function") {
    panner.setPosition(place.x, place.y, place.z);
  }
  source.connect(panner);
  panner.connect(ctx.destination);
  source.start();
  return { played: true, seat: place };
}
