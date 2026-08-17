/**
 * Single property row — label left, control right (Effect Controls style).
 */
export default function StudioFieldRow({ label, hint, children, testId, className = "" }) {
  return (
    <div className={`studio-field-row ${className}`} data-testid={testId}>
      <div className="studio-field-label">
        <span>{label}</span>
        {hint ? <span className="studio-field-hint">{hint}</span> : null}
      </div>
      <div className="studio-field-control">{children}</div>
    </div>
  );
}
