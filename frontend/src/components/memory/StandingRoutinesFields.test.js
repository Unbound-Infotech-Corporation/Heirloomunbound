import { act } from "react";
import { createRoot } from "react-dom/client";
import StandingRoutinesFields from "./StandingRoutinesFields";
import { ROUTINE_COPY } from "../../lib/standingRoutines";

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

describe("StandingRoutinesFields", () => {
  test("renders owner-only quiet copy and all three toggles off by default", () => {
    const { el, unmount } = mount(
      <StandingRoutinesFields
        routines={{ morning_brief: false, weekly_biographer: false, sealed_letter_nudge: false }}
        onChange={() => {}}
      />
    );
    const root = el.querySelector('[data-testid="standing-routines-section"]');
    expect(root).toBeTruthy();
    expect(root.textContent).toContain(ROUTINE_COPY.quiet);
    expect(root.textContent).toContain("Heirs");
    expect(el.querySelector('[data-testid="routine-checkbox-morning_brief"]').checked).toBe(false);
    expect(el.querySelector('[data-testid="routine-toggle-weekly_biographer"]')).toBeTruthy();
    expect(el.querySelector('[data-testid="routine-toggle-sealed_letter_nudge"]')).toBeTruthy();
    unmount();
  });

  test("toggling morning brief calls onChange with it enabled", () => {
    const onChange = jest.fn();
    const routines = { morning_brief: false, weekly_biographer: false, sealed_letter_nudge: false };
    const { el, unmount } = mount(
      <StandingRoutinesFields routines={routines} onChange={onChange} />
    );
    act(() => {
      el.querySelector('[data-testid="routine-checkbox-morning_brief"]').click();
    });
    expect(onChange).toHaveBeenCalledWith({ ...routines, morning_brief: true });
    unmount();
  });
});
