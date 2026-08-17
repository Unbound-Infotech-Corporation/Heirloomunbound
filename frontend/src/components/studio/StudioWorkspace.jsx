/**
 * Classic Adobe workspace: stacked inspector (left) + main canvas (right).
 */
export default function StudioWorkspace({
  inspector,
  canvas,
  footer,
  testId,
  inspectorWidth = 280,
  className = "",
}) {
  return (
    <div className={`studio-workspace ${className}`} data-testid={testId}>
      <aside className="studio-inspector" style={{ width: inspectorWidth, minWidth: inspectorWidth }}>
        {inspector}
      </aside>
      <div className="studio-workspace-split" aria-hidden />
      <main className="studio-workspace-canvas">{canvas}</main>
      {footer ? <footer className="studio-workspace-footer">{footer}</footer> : null}
    </div>
  );
}
