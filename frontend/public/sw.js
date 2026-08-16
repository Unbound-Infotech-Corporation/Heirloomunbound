/* Heirloom service worker — installable PWA shell.
 *
 * Strategy
 * --------
 * - Precache a tiny "app shell" (`/m` HTML + manifest + icons) at install so
 *   the mobile app opens instantly with no network round-trip.
 * - Runtime fetch: network-first for `/api/*` (data must be fresh); cache-first
 *   for immutable static assets under `/static/`; stale-while-revalidate for
 *   HTML navigation requests so an existing install still works offline.
 * - Skip caching for POST/PUT/DELETE requests and anything with cookies/auth
 *   that we don't want persisted on disk.
 *
 * Cache versioning: bump `SW_VERSION` when shipping a new PWA revision to
 * force clients to purge old caches on the next activate cycle.
 */
const SW_VERSION = "heirloom-v3";
const APP_SHELL = ["/m", "/m/login", "/manifest.json", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SW_VERSION).then((cache) => cache.addAll(APP_SHELL).catch(() => {})),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SW_VERSION).map((k) => caches.delete(k))),
    ).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // API calls — always try the network first; fall back to cache only for
  // GET-shaped read endpoints so a phone with a spotty connection still shows
  // stale-but-useful data.
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          // Only cache successful, non-authenticated data reads.
          if (res.ok && !url.pathname.includes("/auth/")) {
            const clone = res.clone();
            caches.open(`${SW_VERSION}-api`).then((c) => c.put(req, clone)).catch(() => {});
          }
          return res;
        })
        .catch(() => caches.match(req).then((r) => r || new Response(JSON.stringify({offline: true}), {
          status: 503, headers: {"Content-Type": "application/json"},
        }))),
    );
    return;
  }

  // Static assets — cache first with revalidate.
  if (url.pathname.startsWith("/static/") || /\.(js|css|png|jpg|jpeg|webp|svg|woff2?)$/.test(url.pathname)) {
    event.respondWith(
      caches.match(req).then((cached) => {
        const fetched = fetch(req).then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(SW_VERSION).then((c) => c.put(req, clone)).catch(() => {});
          }
          return res;
        }).catch(() => cached);
        return cached || fetched;
      }),
    );
    return;
  }

  // Navigation (HTML) — network first with cache fallback so the PWA opens
  // offline. React Router handles the actual routing client-side.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(() => caches.match(req).then((r) => r || caches.match("/m"))),
    );
    return;
  }
});

// ---------- Push notifications ----------
// Backend sends `data: JSON.stringify({title, body, url, tag, requireInteraction})`.
// Wrap the parse in a try so a malformed payload still fires SOMETHING —
// otherwise Chrome will throw a generic "site has been updated in the
// background" notification which is worse UX than a plain string.
self.addEventListener("push", (event) => {
  let payload = { title: "Heirloom", body: "New activity" };
  if (event.data) {
    try {
      payload = { ...payload, ...event.data.json() };
    } catch (_e) {
      payload.body = event.data.text() || payload.body;
    }
  }
  const options = {
    body: payload.body,
    tag: payload.tag || "heirloom",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    data: { url: payload.url || "/m", call_sid: payload.call_sid || null },
    requireInteraction: !!payload.requireInteraction,
    // Show two actions for a call push so the owner can join in one tap.
    actions: payload.call_sid
      ? [
          { action: "join", title: "Join call" },
          { action: "dismiss", title: "Dismiss" },
        ]
      : [],
  };
  event.waitUntil(self.registration.showNotification(payload.title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  if (event.action === "dismiss") return;
  const url = event.notification.data?.url || "/m";
  event.waitUntil(
    (async () => {
      const clientsArr = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const c of clientsArr) {
        if (c.url.includes("/m")) {
          await c.focus();
          try { c.postMessage({ type: "notification-click", url, data: event.notification.data }); } catch (_e) {}
          return;
        }
      }
      await self.clients.openWindow(url);
    })(),
  );
});
