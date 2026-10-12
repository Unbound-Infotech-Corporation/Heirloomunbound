import { TWIN_SEAT, controllerPttDown, keyboardPtt, playAtSeat, runVrTurn, seatPannerPosition } from "./vrTalk";

describe("VR twin talk", () => {
  test("the twin sits across from the owner and audio is placed there", () => {
    expect(TWIN_SEAT.z).toBeLessThan(0);
    expect(TWIN_SEAT.y).toBeGreaterThan(0.5);
    expect(seatPannerPosition().z).toBe(TWIN_SEAT.z);
  });

  test("push to talk is the trigger, the squeeze, or the keyboard", () => {
    expect(controllerPttDown({ buttons: [{ pressed: true }] })).toBe(true);
    expect(controllerPttDown({ buttons: [{ pressed: false }, { pressed: true }] })).toBe(true);
    expect(controllerPttDown({ buttons: [{ pressed: false }, { pressed: false }, { pressed: true }] })).toBe(false);
    expect(keyboardPtt({ code: "Space", repeat: false })).toBe(true);
    expect(keyboardPtt({ code: "KeyV", repeat: false })).toBe(true);
    expect(keyboardPtt({ code: "Space", repeat: true })).toBe(false);
    expect(keyboardPtt({ code: "Space", target: { tagName: "TEXTAREA" } })).toBe(false);
  });

  test("a turn uses speech, the chat reply, and the seat — heirs do not get a turn", async () => {
    const transcribe = jest.fn().mockResolvedValue("hello from the chair");
    const chat = jest.fn().mockResolvedValue("I remember the kitchen.");
    const speak = jest.fn().mockResolvedValue({ audio_base64: "aaa" });
    const turn = await runVrTurn({ blob: new Blob(["x"]), transcribe, chat, speak });
    expect(transcribe).toHaveBeenCalled();
    expect(chat).toHaveBeenCalledWith("hello from the chair");
    expect(speak).toHaveBeenCalledWith("I remember the kitchen.");
    expect(turn.ok).toBe(true);
    expect(turn.seat).toEqual(TWIN_SEAT);
    const heir = await runVrTurn({
      blob: new Blob(["x"]),
      audience: "heir",
      transcribe,
      chat,
      speak,
    });
    expect(heir.reason).toBe("heir");
    expect(transcribe).toHaveBeenCalledTimes(1);
  });

  test("missing audio does not invent a position", async () => {
    const result = await playAtSeat("", TWIN_SEAT, {});
    expect(result.played).toBe(false);
    expect(result.seat.z).toBe(TWIN_SEAT.z);
  });
});
