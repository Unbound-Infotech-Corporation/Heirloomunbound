import { browserTimeZone } from "./captureTime";

describe("browserTimeZone", () => {
  test("reads the Intl zone", () => {
    const intl = {
      DateTimeFormat: () => ({ resolvedOptions: () => ({ timeZone: "America/Los_Angeles" }) }),
    };
    expect(browserTimeZone(intl)).toBe("America/Los_Angeles");
  });

  test("is empty when Intl fails", () => {
    expect(browserTimeZone({ DateTimeFormat: () => { throw new Error("nope"); } })).toBe("");
  });
});
