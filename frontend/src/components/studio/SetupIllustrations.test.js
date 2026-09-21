import { act } from "react";
import { createRoot } from "react-dom/client";
import { SetupExampleRow } from "./SetupIllustrations";

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

describe("SetupExampleRow", () => {
  test("renders illustrated voice steps", () => {
    const { el, unmount } = mount(
      <SetupExampleRow
        examples={[
          { id: "quiet", title: "1. A quiet room", caption: "Close the door." },
          { id: "speak", title: "2. Speak", caption: "About 30 seconds." },
          { id: "ready", title: "3. Twin voice", caption: "Stock voices stay off." },
        ]}
      />
    );
    expect(el.querySelector('[data-testid="setup-examples"]')).toBeTruthy();
    expect(el.querySelector('[data-testid="setup-example-quiet"]')).toBeTruthy();
    expect(el.querySelector('[data-testid="setup-example-speak"]')).toBeTruthy();
    expect(el.textContent).toContain("A quiet room");
    unmount();
  });
});
