import { act } from "react";
import { createRoot } from "react-dom/client";
import HeirSharing from "./HeirSharing";
import CardSharingList from "./CardSharingList";
import FamilyNamesFields from "./FamilyNamesFields";

jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("../../lib/api", () => ({ api: { get: jest.fn(), post: jest.fn(), put: jest.fn() } }));
const { api } = require("../../lib/api");

const heirs = [
  { heir_id: "h_emma", name: "Emma", names: [] },
  { heir_id: "h_sam", name: "Sam", names: [{ person: "June", called: "Grandma" }] },
];
const baseCards = () => [
  { card_id: "c1", title: "How June and I met", story: "State Fair, Ferris wheel.", visibility: "owner", heir_ids: [], status: "approved" },
  { card_id: "c2", title: "First car", story: "A blue Nova.", visibility: "family", heir_ids: [], status: "approved" },
  { card_id: "c3", title: "The lake", story: "Pike Lake.", visibility: "family", heir_ids: ["h_sam"], status: "approved" },
];

function mount(ui) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  act(() => root.render(ui));
  return { el, unmount() { act(() => root.unmount()); el.remove(); } };
}
const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const click = (el, sel) => act(() => { el.querySelector(sel).click(); });
const q = (el, id) => el.querySelector(`[data-testid="${id}"]`);

describe("CardSharingList", () => {
  test("badges show who hears each memory", () => {
    const { el, unmount } = mount(<CardSharingList cards={baseCards()} heirs={heirs} onShare={jest.fn()} />);
    expect(q(el, "share-badge-c1").textContent).toBe("Only me");
    expect(q(el, "share-badge-c1").dataset.kind).toBe("only-me");
    expect(q(el, "share-badge-c2").textContent).toBe("Heard by: All heirs (2)");
    expect(q(el, "share-badge-c3").textContent).toBe("Heard by: Sam");
    unmount();
  });

  test("share one card with all heirs, with specific heirs, and stop sharing", async () => {
    const onShare = jest.fn().mockResolvedValue();
    const { el, unmount } = mount(<CardSharingList cards={baseCards()} heirs={heirs} onShare={onShare} />);
    click(el, '[data-testid="share-open-c1"]');
    click(el, '[data-testid="share-mode-all-c1"]');
    click(el, '[data-testid="share-save-c1"]');
    await tick();
    expect(onShare).toHaveBeenLastCalledWith(["c1"], { visibility: "family", heir_ids: [] });

    click(el, '[data-testid="share-open-c1"]');
    click(el, '[data-testid="share-mode-some-c1"]');
    click(el, '[data-testid="share-heir-h_emma-c1"]');
    click(el, '[data-testid="share-save-c1"]');
    await tick();
    expect(onShare).toHaveBeenLastCalledWith(["c1"], { visibility: "family", heir_ids: ["h_emma"] });

    click(el, '[data-testid="unshare-c2"]');
    await tick();
    expect(onShare).toHaveBeenLastCalledWith(["c2"], { visibility: "owner", heir_ids: [] });
    expect(q(el, "unshare-c1")).toBeNull(); // an owner-only card has nothing to stop
    unmount();
  });

  test("picking specific heirs with none ticked is refused", async () => {
    const onShare = jest.fn().mockResolvedValue();
    const { el, unmount } = mount(<CardSharingList cards={baseCards()} heirs={heirs} onShare={onShare} />);
    click(el, '[data-testid="share-open-c1"]');
    click(el, '[data-testid="share-mode-some-c1"]');
    click(el, '[data-testid="share-save-c1"]');
    await tick();
    expect(onShare).not.toHaveBeenCalled();
    expect(q(el, "share-error").textContent).toContain("Pick at least one heir");
    unmount();
  });

  test("bulk: share selected with all heirs, with picked heirs, and stop sharing selected", async () => {
    const onShare = jest.fn().mockResolvedValue();
    const { el, unmount } = mount(<CardSharingList cards={baseCards()} heirs={heirs} onShare={onShare} />);
    expect(q(el, "share-selected-all").disabled).toBe(true);
    click(el, '[data-testid="share-pick-c1"]');
    click(el, '[data-testid="share-pick-c3"]');
    click(el, '[data-testid="share-selected-all"]');
    await tick();
    expect(onShare).toHaveBeenLastCalledWith(["c1", "c3"], { visibility: "family", heir_ids: [] });

    click(el, '[data-testid="share-select-all"]');
    click(el, '[data-testid="share-selected-pick"]');
    click(el, '[data-testid="share-bulk-heirs"] input[type="checkbox"]');
    click(el, '[data-testid="share-bulk-save"]');
    await tick();
    expect(onShare).toHaveBeenLastCalledWith(["c1", "c2", "c3"], { visibility: "family", heir_ids: ["h_emma"] });

    click(el, '[data-testid="share-select-all"]');
    click(el, '[data-testid="unshare-selected"]');
    await tick();
    expect(onShare).toHaveBeenLastCalledWith(["c1", "c2", "c3"], { visibility: "owner", heir_ids: [] });
    unmount();
  });

  test("with no heirs, sharing is disabled and explains why", () => {
    const { el, unmount } = mount(<CardSharingList cards={baseCards()} heirs={[]} onShare={jest.fn()} />);
    expect(q(el, "share-no-heirs")).toBeTruthy();
    expect(q(el, "share-open-c1").disabled).toBe(true);
    unmount();
  });

  test("empty state", () => {
    const { el, unmount } = mount(<CardSharingList cards={[]} heirs={heirs} onShare={jest.fn()} />);
    expect(q(el, "share-empty")).toBeTruthy();
    unmount();
  });
});

describe("HeirSharing", () => {
  beforeEach(() => {
    let cards = baseCards();
    api.get.mockImplementation(async (url) => {
      if (url === "/life-story/cards") return { data: { cards } };
      if (url === "/heirs") return { data: heirs };
      if (url === "/memory-loop/sharing") return { data: { share_new_cards: false } };
      throw new Error(url);
    });
    api.post.mockImplementation(async (url, body) => {
      if (url === "/memory-loop/cards/share") {
        cards = cards.map((c) => (body.card_ids.includes(c.card_id) ? { ...c, visibility: body.visibility, heir_ids: body.heir_ids } : c));
        return { data: { shared: body.card_ids } };
      }
      throw new Error(url);
    });
    api.put.mockImplementation(async (url, body) => ({ data: body.names ? { names: body.names } : body }));
  });
  afterEach(() => jest.clearAllMocks());

  test("loads approved cards, shares through the route, and reloads the badge", async () => {
    const { el, unmount } = mount(<HeirSharing />);
    await tick();
    expect(api.get).toHaveBeenCalledWith("/life-story/cards", { params: { status: "approved" } });
    expect(q(el, "share-badge-c1").textContent).toBe("Only me");
    click(el, '[data-testid="share-pick-c1"]');
    click(el, '[data-testid="share-selected-all"]');
    await tick();
    expect(api.post).toHaveBeenCalledWith("/memory-loop/cards/share", { card_ids: ["c1"], visibility: "family", heir_ids: [] });
    expect(q(el, "share-badge-c1").textContent).toBe("Heard by: All heirs (2)");
    click(el, '[data-testid="unshare-c1"]');
    await tick();
    expect(api.post).toHaveBeenLastCalledWith("/memory-loop/cards/share", { card_ids: ["c1"], visibility: "owner", heir_ids: [] });
    expect(q(el, "share-badge-c1").textContent).toBe("Only me");
    unmount();
  });

  test("the default setting is off until the owner turns it on, and saves", async () => {
    const { el, unmount } = mount(<HeirSharing />);
    await tick();
    const toggle = q(el, "share-default-toggle");
    expect(toggle.checked).toBe(false);
    expect(q(el, "share-default").textContent).toContain("Share new approved cards with all heirs");
    click(el, '[data-testid="share-default-toggle"]');
    await tick();
    expect(api.put).toHaveBeenCalledWith("/memory-loop/sharing", { share_new_cards: true });
    expect(q(el, "share-default-toggle").checked).toBe(true);
    unmount();
  });

  test("family names save per heir as names only", async () => {
    const { el, unmount } = mount(<HeirSharing />);
    await tick();
    expect(q(el, "names-row-h_sam-0")).toBeTruthy();
    click(el, '[data-testid="names-save-h_sam"]');
    await tick();
    expect(api.put).toHaveBeenCalledWith("/heirs/h_sam/names", { names: [{ person: "June", called: "Grandma" }] });
    unmount();
  });

  test("a load failure shows a retry, not a blank page", async () => {
    api.get.mockRejectedValue({ response: { data: { detail: "owner_only" } } });
    const { el, unmount } = mount(<HeirSharing />);
    await tick();
    expect(q(el, "share-load-error").textContent).toContain("owner_only");
    unmount();
  });
});

describe("FamilyNamesFields", () => {
  test("renders nothing without heirs", () => {
    const { el, unmount } = mount(<FamilyNamesFields heirs={[]} onSave={jest.fn()} />);
    expect(q(el, "family-names")).toBeNull();
    unmount();
  });
});

describe("wiring", () => {
  const fs = require("fs");
  const path = require("path");
  const read = (p) => fs.readFileSync(path.join(__dirname, "..", "..", "pages", p), "utf8");
  test("Memory page and the life-story card review both show the sharing controls", () => {
    expect(read("Memory.jsx")).toContain("<HeirSharing />");
    const life = read("LifeStory.jsx");
    expect(life).toContain("<HeirSharing version={version}");
    expect(life).toContain('data-testid="review-approve-share"');
    expect(life).toContain('"/memory-loop/cards/share"');
  });
});
