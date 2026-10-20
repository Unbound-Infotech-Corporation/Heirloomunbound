export default function ModelBadge({ badge, detail }) {
  if (!badge) return null;
  const drafts = detail?.drafts;
  return (
    <div className="studio-model-badge-wrap" data-testid="model-badge">
      <span className="studio-model-badge">{badge}</span>
      {drafts?.primary?.text || drafts?.second?.text ? (
        <div className="studio-model-drafts">
          {drafts.primary?.text ? (
            <div>
              <div className="studio-model-draft-label">Primary · {drafts.primary.backend}/{drafts.primary.model}</div>
              <pre>{drafts.primary.text}</pre>
            </div>
          ) : null}
          {drafts.second?.text ? (
            <div>
              <div className="studio-model-draft-label">Second · {drafts.second.backend}/{drafts.second.model}</div>
              <pre>{drafts.second.text}</pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
