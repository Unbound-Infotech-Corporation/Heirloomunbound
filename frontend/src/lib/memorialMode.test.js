import { memorialFormFrom, memorialPayload, memorialStatusLine } from "./memorialMode";

describe("memorial mode toggle", () => {
  test("a partial form saves posthumous mode and the optional date", () => {
    const body = memorialPayload({
      mode: "posthumous",
      date: "2019-04-03",
      contactName: "Ada",
      contactEmail: "ada@example.com",
      longSessionTurns: 12,
      sessionsPerDay: 4,
      longSessionMinutes: 60,
    });
    expect(body.mode).toBe("posthumous");
    expect(body.date).toBe("2019-04-03");
    expect(body.contact_name).toBe("Ada");
    expect(body.long_session_turns).toBe(12);
    expect(memorialStatusLine({ mode: "posthumous", date: "2019-04-03" })).toMatch(/2019-04-03/);
    expect(memorialStatusLine({ mode: "living" })).toMatch(/Living mode/);
  });

  test("unknown mode stays living and the form round-trips thresholds", () => {
    const form = memorialFormFrom({
      mode: "nope",
      contact_name: "Sam",
      grief: { long_session_turns: 15, sessions_per_day: 5, long_session_minutes: 90 },
    });
    expect(form.mode).toBe("living");
    expect(form.contactName).toBe("Sam");
    expect(memorialPayload(form).long_session_turns).toBe(15);
    expect(memorialPayload(form).sessions_per_day).toBe(5);
  });
});
