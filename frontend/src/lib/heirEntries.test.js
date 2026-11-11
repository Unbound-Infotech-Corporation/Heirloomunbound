import { heirVisibleEntries } from "./heirEntries";

describe("heirVisibleEntries", () => {
  test("drops private and owner-only rows", () => {
    const rows = heirVisibleEntries([
      { entry_id: "gift", title: "The lake", visibility: "heir" },
      { entry_id: "worry", title: "Private worry", visibility: "private" },
      { entry_id: "note", title: "Owner note", visibility: "owner" },
      { entry_id: "old", title: "Unmarked gift" },
    ]);
    expect(rows.map((row) => row.entry_id)).toEqual(["gift", "old"]);
  });
});
