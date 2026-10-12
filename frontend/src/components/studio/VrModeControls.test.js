import { act } from "react";
import { createRoot } from "react-dom/client";
import VrModeControls from "./VrModeControls";

jest.mock("lucide-react", () => {
  const React = require("react");
  return {
    Headset: (props) => React.createElement("span", props),
  };
});

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

describe("VR mode controls", () => {
  test("rendering does not turn VR on", () => {
    const onToggleVr = jest.fn();
    const onEnter = jest.fn();
    const view = mount(
      <VrModeControls enabled={false} gazeEnabled={false} onToggleVr={onToggleVr} onEnter={onEnter} />,
    );
    expect(onToggleVr).not.toHaveBeenCalled();
    expect(onEnter).not.toHaveBeenCalled();
    expect(view.el.querySelector("[data-testid='vr-mode-toggle']").textContent).toMatch(/VR off/);
    expect(view.el.querySelector("[data-testid='vr-mode-enter']")).toBeNull();
    view.unmount();
  });

  test("the switches and the enter button are clicks", () => {
    const onToggleVr = jest.fn();
    const onToggleGaze = jest.fn();
    const onEnter = jest.fn();
    const onLeave = jest.fn();
    const saved = mount(
      <VrModeControls
        enabled
        gazeEnabled={false}
        sessionActive={false}
        onToggleVr={onToggleVr}
        onToggleGaze={onToggleGaze}
        onEnter={onEnter}
        onLeave={onLeave}
      />,
    );
    act(() => {
      saved.el.querySelector("[data-testid='vr-mode-enter']").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onEnter).toHaveBeenCalledTimes(1);
    act(() => {
      saved.el.querySelector("[data-testid='vr-mode-gaze']").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onToggleGaze).toHaveBeenCalledWith(true);
    saved.unmount();

    const live = mount(
      <VrModeControls enabled sessionActive onToggleVr={onToggleVr} onLeave={onLeave} />,
    );
    act(() => {
      live.el.querySelector("[data-testid='vr-mode-leave']").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onLeave).toHaveBeenCalledTimes(1);
    expect(live.el.querySelector("[data-testid='vr-mode-enter']")).toBeNull();
    live.unmount();
  });
});
