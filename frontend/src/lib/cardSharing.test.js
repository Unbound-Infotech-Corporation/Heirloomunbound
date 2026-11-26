import { bulkSharePayload, cardMode, cleanNames, isShared, pickedIds, sharePayload, sharedCount, whoHears } from "./cardSharing";

const heirs = [
  { heir_id: "h_emma", name: "Emma" },
  { heir_id: "h_sam", name: "Sam" },
];

describe("cardSharing", () => {
  test("approved cards are owner-only until shared", () => {
    expect(isShared({ visibility: "owner" })).toBe(false);
    expect(isShared({})).toBe(false);
    expect(isShared({ visibility: "private" })).toBe(false);
    expect(whoHears({ visibility: "owner" }, heirs)).toMatchObject({ kind: "only-me", label: "Only me" });
  });

  test("badges name who can hear it", () => {
    expect(whoHears({ visibility: "family", heir_ids: [] }, heirs)).toMatchObject({ kind: "all", label: "All heirs (2)" });
    expect(whoHears({ visibility: "family", heir_ids: ["h_sam"] }, heirs)).toMatchObject({ kind: "some", label: "Sam" });
    expect(whoHears({ visibility: "heir", heir_ids: ["h_emma", "h_sam"] }, heirs).label).toBe("Emma, Sam");
    expect(whoHears({ visibility: "family", heir_ids: ["h_gone"] }, heirs).kind).toBe("nobody");
  });

  test("payloads: all, specific, stop sharing", () => {
    expect(sharePayload("all")).toEqual({ visibility: "family", heir_ids: [] });
    expect(sharePayload("some", ["h_sam", "h_sam", ""])).toEqual({ visibility: "family", heir_ids: ["h_sam"] });
    expect(sharePayload("none", ["h_sam"])).toEqual({ visibility: "owner", heir_ids: [] });
    expect(() => sharePayload("some", [])).toThrow("Pick at least one heir");
    expect(bulkSharePayload(["a", "a", "b"], "all")).toEqual({ card_ids: ["a", "b"], visibility: "family", heir_ids: [] });
  });

  test("helpers", () => {
    expect(pickedIds({ a: true, b: false, c: true })).toEqual(["a", "c"]);
    expect(cardMode({ visibility: "family", heir_ids: ["h_sam"] })).toBe("some");
    expect(cardMode({ visibility: "family" })).toBe("all");
    expect(cardMode({ visibility: "owner" })).toBe("none");
    expect(sharedCount([{ visibility: "family" }, { visibility: "owner" }])).toBe(1);
  });

  test("family names are cleaned", () => {
    expect(cleanNames([{ person: " June ", called: "Grandma" }, { person: "june", called: "grandma" }, { person: "", called: "x" }, { person: "Walt", called: "walt" }]))
      .toEqual([{ person: "June", called: "Grandma" }]);
  });
});
