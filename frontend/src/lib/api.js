import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

// Helpers for SSE streaming (auth via cookie sent by fetch)
export const streamSSE = async (path, payload, onChunk, onDone, onError) => {
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
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";
      for (const evt of events) {
        const lines = evt.split("\n");
        let isDone = false;
        let isError = false;
        const dataLines = [];
        for (const line of lines) {
          if (line.startsWith("event:")) {
            const ev = line.slice(6).trim();
            if (ev === "done") isDone = true;
            if (ev === "error") isError = true;
          } else if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).replace(/^ /, ""));
          }
        }
        const data = dataLines.join("\n");
        if (isDone) {
          onDone && onDone();
        } else if (isError) {
          onError && onError(new Error(data));
        } else if (data) {
          onChunk(data);
        }
      }
    }
    onDone && onDone();
  } catch (e) {
    onError && onError(e);
  }
};
