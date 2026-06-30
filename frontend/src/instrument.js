// Sentry initialization — MUST be imported as the first import in src/index.js
// so it instruments before React/router/anything else loads. Silently no-ops
// when REACT_APP_SENTRY_DSN is unset (so dev/test environments stay clean).
import * as Sentry from "@sentry/react";
import React from "react";
import {
  createRoutesFromChildren,
  matchRoutes,
  useLocation,
  useNavigationType,
} from "react-router-dom";

const dsn = process.env.REACT_APP_SENTRY_DSN || "";

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.REACT_APP_SENTRY_ENVIRONMENT || "preview",
    release: process.env.REACT_APP_VERSION || undefined,

    integrations: [
      // React Router v7 (non-framework mode) — names transactions by route
      Sentry.reactRouterV7BrowserTracingIntegration({
        useEffect: React.useEffect,
        useLocation,
        useNavigationType,
        createRoutesFromChildren,
        matchRoutes,
      }),
      // Session replay — masked + media blocked, on-error only by default
      Sentry.replayIntegration({
        maskAllText: false,
        blockAllMedia: true,
      }),
    ],

    // Performance: low rate keeps us inside the free tier
    tracesSampleRate: 0.05,
    tracePropagationTargets: [
      "localhost",
      /^https:\/\/.*\.emergentagent\.com/,
      /^https:\/\/.*heirloomunbound\.com/,
    ],

    // Session replay sampling: 0% normal, 100% when an error fires
    replaysSessionSampleRate: 0.0,
    replaysOnErrorSampleRate: 1.0,

    // Cosmetic: include filename + lineno in messages
    attachStacktrace: true,

    // Filter noise — ResizeObserver loops + extension-injected errors
    ignoreErrors: [
      "ResizeObserver loop completed",
      "ResizeObserver loop limit exceeded",
      "Non-Error promise rejection captured",
      /chrome-extension:/i,
      /moz-extension:/i,
    ],
  });
}

// Helper: bind user context once we know who's signed in. Called from
// auth-success paths around the app.
export function setSentryUser(user) {
  if (!dsn || !user) return;
  Sentry.setUser({
    id: user.user_id || user.id,
    email: user.email,
    username: user.name,
  });
}

export function clearSentryUser() {
  if (!dsn) return;
  Sentry.setUser(null);
}
