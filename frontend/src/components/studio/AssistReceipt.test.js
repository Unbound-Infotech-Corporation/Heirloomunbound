import { act } from "react";
import { createRoot } from "react-dom/client";
import AssistReceipt from "./AssistReceipt";

function mount(ui) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  act(() => {
    root.render(ui);
  });
  return {
    el,
    unmount() {
      act(() => root.unmount());
      el.remove();
    },
  };
}

describe("AssistReceipt", () => {
  test("renders Did chip and summary without a plan for one step", () => {
    const { el, unmount } = mount(
      <AssistReceipt
        receipt={{
          status: "did",
          summary: "Opened Chrome",
          steps: [{ id: "1", name: "open_on_pc", label: "Open on this PC", ok: true }],
          plan: null,
        }}
      />
    );
    expect(el.querySelector('[data-testid="assist-receipt-status"]').textContent).toContain("Did");
    expect(el.querySelector('[data-testid="assist-receipt-summary"]').textContent).toBe("Opened Chrome");
    expect(el.querySelector('[data-testid="assist-receipt-step-open_on_pc"]').textContent).toContain(
      "Open on this PC"
    );
    expect(el.querySelector('[data-testid="assist-receipt-plan"]')).toBeNull();
    expect(el.querySelector('[data-testid="assist-receipt-confirm"]')).toBeNull();
    unmount();
  });

  test("shows Plan then Waiting for Confirm", () => {
    const { el, unmount } = mount(
      <AssistReceipt
        receipt={{
          status: "waiting_confirm",
          summary: "Waiting for Confirm — Shutdown needs Confirm.",
          plan: ["Power control"],
          steps: [
            {
              id: "2",
              name: "power_action",
              label: "Power control",
              ok: false,
              needs_confirm: true,
              summary: "Shutdown needs Confirm",
            },
          ],
        }}
      />
    );
    expect(el.querySelector('[data-testid="assist-receipt-plan"]').textContent).toMatch(/Plan/);
    expect(el.querySelector('[data-testid="assist-receipt-plan"]').textContent).toMatch(/Power control/);
    expect(el.querySelector('[data-testid="assist-receipt-status"]').textContent).toContain(
      "Waiting for Confirm"
    );
    expect(el.querySelector('[data-testid="assist-receipt-confirm"]').textContent).toMatch(
      /Confirm in this document/
    );
    unmount();
  });

  test("failed step uses Failed chip", () => {
    const { el, unmount } = mount(
      <AssistReceipt
        receipt={{
          status: "failed",
          summary: "Command failed: access denied",
          steps: [{ id: "3", name: "run_command", label: "Run a command", ok: false }],
        }}
      />
    );
    expect(el.querySelector('[data-testid="assist-receipt-status"]').textContent).toContain("Failed");
    expect(el.querySelector('[data-testid="assist-receipt-summary"]').textContent).toMatch(/access denied/);
    unmount();
  });

  test("renders nothing without a receipt", () => {
    const { el, unmount } = mount(<AssistReceipt receipt={null} />);
    expect(el.querySelector('[data-testid="assist-receipt"]')).toBeNull();
    unmount();
  });
});
