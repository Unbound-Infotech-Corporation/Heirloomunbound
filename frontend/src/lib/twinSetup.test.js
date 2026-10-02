import { coachShouldShow, remainingCritical, stepById, stepIndexFromHash } from "./twinSetup";

const incomplete = {
  remaining_critical: 2,
  all_critical_done: false,
  youre_set: false,
  coach_dismissed: false,
  steps: [
    { id: "voice", critical: true, done: false },
    { id: "likeness", critical: true, done: false },
    { id: "avatar", critical: false, done: false },
  ],
};

describe("twin setup coach visibility", () => {
  test("incomplete account shows the coach", () => {
    expect(coachShouldShow(incomplete)).toBe(true);
    expect(remainingCritical(incomplete)).toBe(2);
  });

  test("dismissed coach hides until reopened", () => {
    expect(coachShouldShow({ ...incomplete, coach_dismissed: true })).toBe(false);
    expect(coachShouldShow({ ...incomplete, coach_dismissed: true }, { dismissedOverride: false })).toBe(
      true
    );
  });

  test("voice and photos clear the coach", () => {
    const done = {
      remaining_critical: 0,
      all_critical_done: true,
      youre_set: true,
      coach_dismissed: false,
      steps: [
        { id: "voice", critical: true, done: true },
        { id: "likeness", critical: true, done: true },
      ],
    };
    expect(coachShouldShow(done)).toBe(false);
    expect(remainingCritical(done)).toBe(0);
  });

  test("finds the likeness step", () => {
    expect(stepById(incomplete, "likeness")?.critical).toBe(true);
    expect(stepById(incomplete, "nope")).toBeNull();
  });
});

const SETUP_IDS = ["welcome", "space", "email", "voice", "likeness", "phone", "done", "keys"];

describe("first-run hash step", () => {
  test("welcome is step 0, not skipped", () => {
    expect(stepIndexFromHash("#welcome", SETUP_IDS)).toBe(0);
    expect(stepIndexFromHash("welcome", SETUP_IDS)).toBe(0);
  });

  test("voice and likeness hashes resolve", () => {
    expect(stepIndexFromHash("#voice", SETUP_IDS)).toBe(3);
    expect(stepIndexFromHash("#likeness", SETUP_IDS)).toBe(4);
  });

  test("empty and unknown hashes do not select a step", () => {
    expect(stepIndexFromHash("", SETUP_IDS)).toBeNull();
    expect(stepIndexFromHash("#", SETUP_IDS)).toBeNull();
    expect(stepIndexFromHash("#nope", SETUP_IDS)).toBeNull();
  });
});
