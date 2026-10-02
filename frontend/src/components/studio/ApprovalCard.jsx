import { payloadLines } from "../../lib/assignments";

export default function ApprovalCard({
  approval,
  onApprove,
  onDecline,
  busy = false,
  testid = "approval-card",
}) {
  if (!approval || approval.status !== "pending") return null;
  const lines = payloadLines(approval.payload);
  return (
    <section
      className="surface p-5"
      data-testid={testid}
      style={{ borderColor: "var(--accent)" }}
    >
      <div className="overline mb-2">needs approval</div>
      <p className="font-serif text-xl leading-snug" style={{ color: "var(--text-primary)" }}>
        {approval.summary || "This would leave Heirloom."}
      </p>
      <p className="mt-2 text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }} data-testid={`${testid}-kind`}>
        {approval.action_kind || "action"}
      </p>
      {lines.length ? (
        <dl className="mt-4 space-y-2 text-sm" data-testid={`${testid}-payload`}>
          {lines.map(([key, value]) => (
            <div key={key}>
              <dt className="overline">{key}</dt>
              <dd className="mt-1 whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-3 text-sm" style={{ color: "var(--text-muted)" }}>
          Nothing else would be sent.
        </p>
      )}
      <div className="mt-5 flex flex-wrap gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={() => onApprove?.(approval)}
          data-testid={`${testid}-approve`}
          className="px-4 py-2 text-sm font-medium rounded-sm disabled:opacity-50"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          Approve
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onDecline?.(approval)}
          data-testid={`${testid}-decline`}
          className="px-4 py-2 text-sm rounded-sm disabled:opacity-50"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
        >
          Decline
        </button>
      </div>
    </section>
  );
}
