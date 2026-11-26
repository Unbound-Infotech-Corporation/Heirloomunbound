import { groupNav, mergeMenus } from "./studioChrome";

const app = [
  { label: "File", items: [{ label: "Quick capture" }, { sep: true }, { label: "Sign out" }] },
  { label: "Edit", items: [{ label: "Settings…" }] },
  { label: "Window", items: [{ label: "Today" }, { label: "Twin" }] },
];

describe("mergeMenus", () => {
  test("a page menu with a new label lands right after File", () => {
    const out = mergeMenus(app, [{ label: "Today", items: [{ label: "Refresh" }] }]);
    expect(out.map((m) => m.label)).toEqual(["File", "Today", "Edit", "Window"]);
  });
  test("same-label menus merge after a separator without duplicates", () => {
    const out = mergeMenus(app, [{ label: "Window", items: [{ label: "Twin" }, { label: "Mixer" }] }]);
    const win = out.find((m) => m.label === "Window");
    expect(win.items.map((i) => (i.sep ? "—" : i.label))).toEqual(["Today", "Twin", "—", "Mixer"]);
  });
  test("nothing new adds no separator and leaves the app menus untouched", () => {
    const out = mergeMenus(app, [{ label: "Edit", items: [{ label: "Settings…" }] }]);
    expect(out.find((m) => m.label === "Edit").items).toHaveLength(1);
    expect(app[1].items).toHaveLength(1);
  });
});

describe("groupNav", () => {
  test("keeps order inside groups and drops empty groups", () => {
    const groups = groupNav([
      { to: "/today", group: "daily" },
      { to: "/twin", group: "twin" },
      { to: "/lab" },
      { to: "/reminders", group: "daily" },
    ]);
    expect(groups.map((g) => g.key)).toEqual(["daily", "twin", "studio"]);
    expect(groups[0].items.map((i) => i.to)).toEqual(["/today", "/reminders"]);
  });
});
