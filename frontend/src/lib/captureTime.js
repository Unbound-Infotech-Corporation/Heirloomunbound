/** Browser zone sent with Quick Capture so "3pm" is the owner's clock. */

export function browserTimeZone(intl = globalThis.Intl) {
  try {
    return intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}
