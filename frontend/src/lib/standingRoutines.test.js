import {
  ROUTINE_COPY,
  heirPortalMustExcludeRoutines,
  routineActionHref,
  routinesFromMe,
  routinesPayload,
  shouldShowNudge,
} from "./standingRoutines";

describe("standing routines helpers", () => {
  test("defaults stay off until the owner opts in", () => {
    expect(routinesFromMe(null)).toEqual({
      morning_brief: false,
      weekly_biographer: false,
      sealed_letter_nudge: false,
    });
    expect(routinesFromMe({ standing_routines: { morning_brief: { enabled: true } } })).toEqual({
      morning_brief: true,
      weekly_biographer: false,
      sealed_letter_nudge: false,
    });
  });

  test("payload is booleans only", () => {
    expect(routinesPayload({ morning_brief: true, weekly_biographer: 0 })).toEqual({
      morning_brief: true,
      weekly_biographer: false,
      sealed_letter_nudge: false,
    });
  });

  test("quiet and dismissed nudges do not render", () => {
    expect(shouldShowNudge({ quiet: true, title: "On the plate" })).toBe(false);
    expect(shouldShowNudge({ title: "On the plate", status: "dismissed" })).toBe(false);
    expect(shouldShowNudge({ title: "On the plate", status: "open" })).toBe(true);
    expect(shouldShowNudge(null)).toBe(false);
  });

  test("copy promises silence and never invents a life", () => {
    expect(ROUTINE_COPY.quiet).toMatch(/silent|quiet/i);
    expect(ROUTINE_COPY.ownerOnly).toMatch(/Heirs/);
    expect(ROUTINE_COPY.blurb).not.toMatch(/Elias|Vermont|son named/);
  });

  test("action hrefs stay on owner rails", () => {
    expect(routineActionHref({ kind: "morning_brief", action_href: "/reminders" })).toBe("/reminders");
    expect(routineActionHref({ kind: "sealed_letter_nudge" })).toBe("/letters");
    expect(routineActionHref({ kind: "weekly_biographer", action_prompt: "Describe the home" })).toContain(
      "/interviewer?topic="
    );
    expect(routineActionHref({ kind: "weekly_biographer", action_prompt: "Describe the home" })).toContain(
      "weekly_biographer"
    );
  });

  test("heir portal source must not include routine APIs", () => {
    expect(heirPortalMustExcludeRoutines("const tabs = ['welcome','letters']")).toBe(true);
    expect(heirPortalMustExcludeRoutines("api.put('/nudges/routines')")).toBe(false);
    expect(heirPortalMustExcludeRoutines("morning_brief")).toBe(false);
  });
});
