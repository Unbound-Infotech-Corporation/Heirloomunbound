/**
 * PWA push subscription helper.
 *
 * Two paths:
 *   - `ensurePushSubscription()` — idempotent: register SW, ask the browser
 *     for a subscription (uses the server's VAPID key), POST it to the API.
 *   - `unsubscribeFromPush()` — inverse.
 *
 * We deliberately don't ask for permission automatically — the caller (a
 * user-visible button on `/m/call`) prompts, so the UA doesn't downgrade
 * the perm to "denied" for future asks.
 */
import { api } from "@/lib/api";

// urlBase64ToUint8Array (Web Push spec) — VAPID public keys travel as
// base64url and PushManager.subscribe wants raw bytes.
function urlBase64ToUint8Array(b64) {
  const padding = "=".repeat((4 - (b64.length % 4)) % 4);
  const base64 = (b64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) arr[i] = raw.charCodeAt(i);
  return arr;
}

export async function pushSupported() {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export async function getPushPermission() {
  if (!(await pushSupported())) return "unsupported";
  return Notification.permission; // "default" | "granted" | "denied"
}

export async function ensurePushSubscription() {
  if (!(await pushSupported())) {
    throw new Error("This browser doesn't support push notifications.");
  }
  const reg =
    (await navigator.serviceWorker.getRegistration()) ||
    (await navigator.serviceWorker.register("/sw.js"));
  if (Notification.permission === "default") {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") throw new Error("Notification permission denied.");
  } else if (Notification.permission === "denied") {
    throw new Error("Notification permission blocked — enable it in browser settings.");
  }

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    const { data } = await api.get("/push/vapid-public-key");
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(data.public_key),
    });
  }

  const raw = sub.toJSON();
  await api.post("/push/subscribe", {
    endpoint: raw.endpoint,
    keys: raw.keys,
    user_agent: navigator.userAgent.slice(0, 200),
  });
  return sub;
}

export async function unsubscribeFromPush() {
  if (!(await pushSupported())) return;
  const reg = await navigator.serviceWorker.getRegistration();
  if (!reg) return;
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return;
  const raw = sub.toJSON();
  try {
    await api.post("/push/unsubscribe", { endpoint: raw.endpoint });
  } catch (_e) { /* ignore */ }
  try { await sub.unsubscribe(); } catch (_e) { /* ignore */ }
}
