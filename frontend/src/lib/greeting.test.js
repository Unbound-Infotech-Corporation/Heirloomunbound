import { firstSteps, greetingLine, greetingName, isFreshArchive } from "./greeting";

describe("greetingName", () => {
  test("prefers the onboarding name", () => {
    expect(greetingName({ preferred_name: "Chris Lee", name: "akindabigdeal" })).toBe("Chris");
  });
  test("uses the first word of a real name", () => {
    expect(greetingName({ name: "Ada Lovelace", email: "ada@example.com" })).toBe("Ada");
  });
  test("skips an account handle", () => {
    expect(greetingName({ name: "akindabigdeal", email: "akindabigdeal@gmail.com" })).toBe("");
    expect(greetingName({ name: "chris1987", email: "c@example.com" })).toBe("");
  });
  test("keeps a single capitalised name", () => {
    expect(greetingName({ name: "Grandpa", email: "g@example.com" })).toBe("Grandpa");
  });
  test("greets without a name when none is known", () => {
    expect(greetingLine("Good evening", { name: "akindabigdeal", email: "akindabigdeal@gmail.com" })).toBe("Good evening.");
    expect(greetingLine("Hello", { preferred_name: "Chris" })).toBe("Hello, Chris.");
    expect(greetingLine("Hello", null)).toBe("Hello.");
  });
});

describe("first steps", () => {
  test("a brand-new archive shows four open steps", () => {
    const steps = firstSteps({ total_entries: 0 });
    expect(steps).toHaveLength(4);
    expect(steps.every((s) => !s.done)).toBe(true);
    expect(isFreshArchive({ total_entries: 0, streak_days: 0 })).toBe(true);
  });
  test("steps tick off from real counts", () => {
    const steps = firstSteps({ total_entries: 0, twin_conversations: 2, heirs: 1 });
    expect(steps.filter((s) => s.done).map((s) => s.key)).toEqual(["twin", "heir"]);
  });
  test("an archive with entries shows the stats again", () => {
    expect(isFreshArchive({ total_entries: 3, streak_days: 0 })).toBe(false);
    expect(isFreshArchive(null)).toBe(false);
  });
});
