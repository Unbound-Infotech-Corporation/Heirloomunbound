// Sentry MUST be imported before React/app code so it instruments first.
import "@/instrument";

import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Sentry from "@sentry/react";
import "@/index.css";
import App from "@/App";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

// Minimal Shadcn-styled error fallback. Stays on-brand with the rest of the app.
function ErrorFallback({ error, resetError }) {
  return (
    <div
      className="min-h-screen flex items-center justify-center px-6"
      style={{ background: "var(--bg-base)", color: "var(--text-primary)" }}
      data-testid="app-error-boundary"
    >
      <div className="max-w-md text-center">
        <div
          className="overline mb-3"
          style={{ color: "var(--text-muted)" }}
        >
          something broke
        </div>
        <h1 className="font-serif text-3xl mb-3">
          Heirloom hit a snag.
        </h1>
        <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
          We&apos;ve been notified. Try again in a moment, or refresh the page.
        </p>
        {error?.message && (
          <pre
            className="text-xs mb-6 p-3 rounded-sm text-left overflow-auto"
            style={{
              color: "var(--text-muted)",
              background: "var(--bg-surface)",
              border: "1px solid var(--border-default)",
              maxHeight: 160,
            }}
          >
            {String(error.message).slice(0, 400)}
          </pre>
        )}
        <button
          type="button"
          onClick={resetError}
          data-testid="app-error-retry"
          className="inline-flex items-center gap-2 px-5 py-2 rounded-sm text-sm"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          Try again
        </button>
      </div>
    </div>
  );
}

// React 19: pass reactErrorHandler() to createRoot so uncaught + caught
// errors flow into Sentry even without an explicit boundary.
const root = ReactDOM.createRoot(document.getElementById("root"), {
  onUncaughtError: Sentry.reactErrorHandler(),
  onCaughtError: Sentry.reactErrorHandler(),
  onRecoverableError: Sentry.reactErrorHandler(),
});

root.render(
  <React.StrictMode>
    <Sentry.ErrorBoundary fallback={ErrorFallback}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </Sentry.ErrorBoundary>
  </React.StrictMode>,
);
