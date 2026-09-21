import { coachShouldShow, remainingCritical, stepById } from "./twinSetup";

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
