import { useEffect } from "react";

/**
 * usePageMeta — sets <title> and <meta name="description"> for the current page.
 * Restores the previous values on unmount so each route has its own metadata
 * without React-Helmet's overhead.
 *
 * Usage:
 *   usePageMeta({
 *     title: "Sign in — Heirloom",
 *     description: "Continue your private archive...",
 *   });
 */
export function usePageMeta({ title, description }) {
  useEffect(() => {
    const prevTitle = document.title;
    const descEl = document.querySelector('meta[name="description"]');
    const prevDesc = descEl ? descEl.getAttribute("content") : null;

    if (title) document.title = title;
    if (description && descEl) descEl.setAttribute("content", description);

    return () => {
      document.title = prevTitle;
      if (descEl && prevDesc !== null) descEl.setAttribute("content", prevDesc);
    };
  }, [title, description]);
}
