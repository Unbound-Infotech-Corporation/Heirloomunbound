/** Lightweight route fallback while lazy page chunks load. */
export default function PageLoader() {
  return (
    <div
      className="min-h-[40vh] flex items-center justify-center"
      style={{ color: "var(--text-muted)" }}
      data-testid="page-loader"
      aria-busy="true"
      aria-label="Loading page"
    >
      <div className="overline">Loading…</div>
    </div>
  );
}
