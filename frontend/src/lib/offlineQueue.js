/**
 * Offline queue backed by IndexedDB. Used by MobileCapture so voice memos
 * and photos taken while offline are stored locally and auto-flushed when
 * the browser returns online.
 *
 * Design:
 *   - One object store `pending_uploads` keyed by an auto-incrementing id.
 *   - Each record: { kind, blob, filename, caption?, ts, retries }.
 *   - `enqueue()` writes a record.
 *   - `flush(api)` reads all records oldest-first, POSTs each, deletes on
 *     success, increments retries on failure.
 *   - `count()` — how many are queued (drives the UI badge).
 *
 * We intentionally keep the API tiny and framework-free so it's easy to
 * reason about and easy to swap for a Workbox-based BackgroundSync later.
 */
const DB_NAME = "heirloom-offline";
const STORE = "pending_uploads";
const DB_VERSION = 1;

// Max queue size before we start rejecting new records. User-configurable
// later via a settings row; for now a sane default that keeps ~100 MB in
// IndexedDB on modern browsers.
const DEFAULT_MAX = 50;

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function withStore(mode, fn) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const store = tx.objectStore(STORE);
    const res = fn(store);
    tx.oncomplete = () => resolve(res);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

export async function enqueue(record, max = DEFAULT_MAX) {
  const current = await count();
  if (current >= max) {
    throw new Error(`Offline queue full (${current}/${max}). Delete some or come back online.`);
  }
  return withStore("readwrite", (store) => {
    store.add({ ...record, retries: 0, ts: Date.now() });
  });
}

export async function count() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).count();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function list() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

export async function remove(id) {
  return withStore("readwrite", (store) => store.delete(id));
}

/**
 * Flush every queued record via the provided `api` axios instance.
 * Returns { succeeded, failed }.
 *
 * `api` is the shared instance from lib/api.js — we need the caller to pass
 * it so auth cookies + baseURL come from the same source of truth.
 */
export async function flush(api) {
  const records = await list();
  let succeeded = 0;
  let failed = 0;
  for (const r of records) {
    try {
      const fd = new FormData();
      if (r.kind === "voice") {
        fd.append("file", r.blob, r.filename || `memo-${r.ts}.webm`);
        await api.post("/entries/voice", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      } else if (r.kind === "photo") {
        fd.append("file", r.blob, r.filename || `photo-${r.ts}.jpg`);
        fd.append("caption", r.caption || "");
        await api.post("/photos", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      } else {
        // Unknown kind — drop it so we don't spin forever.
        await remove(r.id);
        continue;
      }
      await remove(r.id);
      succeeded += 1;
    } catch (_e) {
      // Increment retries so a bad record doesn't block newer ones forever.
      // After 5 tries we drop it.
      await withStore("readwrite", (store) => {
        const req = store.get(r.id);
        req.onsuccess = () => {
          const rec = req.result;
          if (!rec) return;
          rec.retries = (rec.retries || 0) + 1;
          if (rec.retries >= 5) {
            store.delete(r.id);
          } else {
            store.put(rec);
          }
        };
      });
      failed += 1;
    }
  }
  return { succeeded, failed };
}
