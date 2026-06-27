import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

// Helpers for SSE streaming (auth via cookie sent by fetch)
// Backend now frames each delta as JSON: `data: {"text": "..."}\n\n` so embedded
// newlines and brackets survive intact. Errors arrive as `event: error` with
// JSON `{error}`. `event: done` signals graceful completion.
export const streamSSE = async (path, payload, onChunk, onDone, onError, onEvent) => {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const txt = await res.text();
      onError && onError(new Error(`HTTP ${res.status}: ${txt}`));
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let doneSignalled = false;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";
      for (const evt of events) {
        const lines = evt.split("\n");
        let eventName = "";
        const dataLines = [];
        for (const line of lines) {
          if (line.startsWith("event:")) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).replace(/^ /, ""));
          }
        }
        const data = dataLines.join("\n");
        if (eventName === "done") {
          doneSignalled = true;
          onDone && onDone();
        } else if (eventName === "error") {
          let msg = data;
          try { msg = JSON.parse(data).error || data; } catch (_) {}
          onError && onError(new Error(msg));
        } else if (eventName) {
          // Named event (e.g. 'action') — pass parsed JSON to onEvent
          let parsed = data;
          try { parsed = JSON.parse(data); } catch (_) {}
          if (onEvent) onEvent(eventName, parsed);
        } else if (data) {
          // Default event = streaming text delta — JSON-encoded {text}
          let text = data;
          try {
            const parsed = JSON.parse(data);
            text = typeof parsed === "string" ? parsed : (parsed.text ?? "");
          } catch (_) {
            // Backwards-compat: if the server ever yields raw text, use as-is.
          }
          if (text) onChunk(text);
        }
      }
    }
    if (!doneSignalled) onDone && onDone();
  } catch (e) {
    onError && onError(e);
  }
};
