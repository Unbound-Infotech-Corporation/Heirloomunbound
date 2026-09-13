import { act } from "react";
import { createRoot } from "react-dom/client";
import HeldFactsList from "./HeldFactsList";
import { MEMORY_COPY } from "../../lib/memoryStudio";

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

describe("HeldFactsList", () => {
  test("empty state uses archive-extracted copy", () => {
    const { el, unmount } = mount(<HeldFactsList facts={[]} onRemove={() => {}} />);
    const empty = el.querySelector('[data-testid="memory-facts-empty"]');
    expect(empty).toBeTruthy();
    expect(empty.textContent).toContain("Quiet so far");
    expect(empty.textContent).toContain(MEMORY_COPY.emptyFacts);
    expect(empty.textContent).not.toMatch(/Elias|Vermont/);
    unmount();
  });

  test("error state surfaces the message", () => {
    const { el, unmount } = mount(
      <HeldFactsList facts={[]} onRemove={() => {}} error={MEMORY_COPY.factsError} />
    );
    const err = el.querySelector('[data-testid="memory-facts-error"]');
    expect(err).toBeTruthy();
    expect(err.textContent).toBe(MEMORY_COPY.factsError);
    unmount();
  });

  test("sourced fact shows provenance and can be removed", () => {
    const onRemove = jest.fn();
    const { el, unmount } = mount(
      <HeldFactsList
        facts={[
          {
            fact_id: "fact_1",
            fact: "Has a lake house",
            kind: "place",
            source_entry_id: "entry_99",
            created_at: "2024-06-01T00:00:00Z",
          },
        ]}
        onRemove={onRemove}
      />
    );
    expect(el.querySelector('[data-testid="fact-fact_1"]').textContent).toContain("Has a lake house");
    expect(el.querySelector('[data-testid="fact-provenance-fact_1"]').textContent).toContain(
      "from archive #entry_99"
    );
    act(() => {
      el.querySelector('[data-testid="remove-fact-fact_1"]').click();
    });
    expect(onRemove).toHaveBeenCalledWith("fact_1");
    unmount();
  });
});
