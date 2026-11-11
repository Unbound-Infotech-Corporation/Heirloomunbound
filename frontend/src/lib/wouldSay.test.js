import { wouldSayLabel } from "./wouldSay";

describe("wouldSayLabel", () => {
  test("uses the signed-in display name", () => {
    expect(wouldSayLabel("Ada Lovelace")).toBe("Would Ada Lovelace say that?");
  });

  test("falls back when the owner has no name", () => {
    expect(wouldSayLabel("")).toBe("Would you say that?");
    expect(wouldSayLabel("   ")).toBe("Would you say that?");
    expect(wouldSayLabel(null)).toBe("Would you say that?");
  });
});
