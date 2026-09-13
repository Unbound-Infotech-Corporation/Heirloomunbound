import { Check, CircleAlert, Clock3, ListTodo } from "lucide-react";
import {
  normalizeReceipt,
  receiptConfirmCopy,
  receiptStatusLabel,
} from "../../lib/assistReceipt";

const STATUS_TONE = {
  did: { color: "var(--accent)", border: "var(--accent)" },
  failed: { color: "var(--danger)", border: "var(--danger)" },
  waiting_confirm: { color: "var(--accent)", border: "var(--accent)" },
  planned: { color: "var(--text-muted)", border: "var(--border-default)" },
};

function Chip({ tone, children, testid, icon: Icon }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 text-[10px] tracking-wide uppercase rounded-sm"
      data-testid={testid}
      style={{
        border: `1px solid ${tone.border}`,
        color: tone.color,
        background: "transparent",
      }}
    >
      {Icon ? <Icon className="h-3 w-3" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

function stepTone(step) {
  if (step.needs_confirm) return STATUS_TONE.waiting_confirm;
  if (!step.ok) return STATUS_TONE.failed;
  return STATUS_TONE.did;
}

function stepIcon(step) {
  if (step.needs_confirm) return Clock3;
  if (!step.ok) return CircleAlert;
  return Check;
}

export default function AssistReceipt({ receipt, testid = "assist-receipt" }) {
  const data = normalizeReceipt(receipt);
  if (!data) return null;
  const tone = STATUS_TONE[data.status] || STATUS_TONE.did;
  const confirmCopy = receiptConfirmCopy(data);

  return (
    <div className="mt-4 space-y-2" data-testid={testid}>
      <div className="flex flex-wrap items-center gap-1.5" data-testid={`${testid}-chips`}>
        {data.plan?.length ? (
          <Chip tone={STATUS_TONE.planned} testid={`${testid}-plan`} icon={ListTodo}>
            Plan
            <span className="normal-case tracking-normal" style={{ color: "var(--text-muted)" }}>
              {data.plan.join(" · ")}
            </span>
          </Chip>
        ) : null}
        <Chip
          tone={tone}
          testid={`${testid}-status`}
          icon={data.status === "failed" ? CircleAlert : data.status === "waiting_confirm" ? Clock3 : Check}
        >
          {receiptStatusLabel(data.status)}
        </Chip>
        {data.steps.map((step) => (
          <Chip
            key={step.id || step.name}
            tone={stepTone(step)}
            testid={`${testid}-step-${step.name}`}
            icon={stepIcon(step)}
          >
            <span className="normal-case tracking-normal">{step.label}</span>
          </Chip>
        ))}
      </div>
      {data.summary ? (
        <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }} data-testid={`${testid}-summary`}>
          {data.summary}
        </p>
      ) : null}
      {confirmCopy ? (
        <p className="text-xs leading-relaxed" style={{ color: "var(--text-muted)" }} data-testid={`${testid}-confirm`}>
          {confirmCopy}
        </p>
      ) : null}
    </div>
  );
}
