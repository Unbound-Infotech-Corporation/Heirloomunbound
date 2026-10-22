/** Owner toggle for living vs posthumous. The heir portal reads the saved setting. */

export function memorialModeFrom(settings) {
  return settings?.mode === "posthumous" ? "posthumous" : "living";
}

export function memorialPayload(form) {
  const mode = form?.mode === "posthumous" ? "posthumous" : "living";
  const turns = Number(form?.longSessionTurns);
  const sessions = Number(form?.sessionsPerDay);
  const minutes = Number(form?.longSessionMinutes);
  return {
    mode,
    date: String(form?.date || "").trim(),
    contact_name: String(form?.contactName || "").trim(),
    contact_email: String(form?.contactEmail || "").trim(),
    long_session_turns: Number.isFinite(turns) ? turns : 40,
    sessions_per_day: Number.isFinite(sessions) ? sessions : 8,
    long_session_minutes: Number.isFinite(minutes) ? minutes : 120,
  };
}

export function memorialFormFrom(settings) {
  const grief = settings?.grief || {};
  return {
    mode: memorialModeFrom(settings),
    date: settings?.date || "",
    contactName: settings?.contact_name || "",
    contactEmail: settings?.contact_email || "",
    longSessionTurns: grief.long_session_turns ?? 40,
    sessionsPerDay: grief.sessions_per_day ?? 8,
    longSessionMinutes: grief.long_session_minutes ?? 120,
  };
}

export function memorialStatusLine(settings) {
  if (memorialModeFrom(settings) === "posthumous") {
    const date = String(settings?.date || "").trim();
    return date
      ? `Memorial mode. Memories stay in the past, dated ${date}.`
      : "Memorial mode. Memories stay in the past.";
  }
  return "Living mode. The twin still separates memory from what someone says now.";
}
