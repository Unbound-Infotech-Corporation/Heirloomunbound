import {
  MEMORY_COPY,
  MEMORY_STUDIO_PATH,
  formatFactProvenance,
  heirPortalMustExclude,
  isOwnerMemoryRoute,
  nextSafeTopics,
  pairingFromMe,
  pairingPayload,
} from "./memoryStudio";

describe("Memory Studio helpers", () => {
  test("owner-only path is /memory", () => {
    expect(MEMORY_STUDIO_PATH).toBe("/memory");
    expect(isOwnerMemoryRoute("/memory")).toBe(true);
    expect(isOwnerMemoryRoute("/studio/memory")).toBe(true);
    expect(isOwnerMemoryRoute("/heir/abc")).toBe(false);
    expect(isOwnerMemoryRoute("/twin/live/x")).toBe(false);
    expect(isOwnerMemoryRoute("/")).toBe(false);
  });

  test("empty and error copy never invents biography", () => {
    expect(MEMORY_COPY.emptyFacts).toMatch(/never invented/);
    expect(MEMORY_COPY.emptyFacts).not.toMatch(/Elias|Vermont|son named/);
    expect(MEMORY_COPY.factsError).toMatch(/Couldn't load/);
    expect(MEMORY_COPY.prefsError).toMatch(/Couldn't load/);
    expect(MEMORY_COPY.ownerOnly).toMatch(/Heirs keep the gift voice/);
  });

  test("fact provenance prefers a source id and does not invent one", () => {
    const sourced = formatFactProvenance({
      kind: "family",
      source_entry_id: "entry_abc123",
      created_at: "2024-03-01T12:00:00Z",
    });
    expect(sourced.kind).toBe("family");
    expect(sourced.source).toBe("from archive #entry_abc123");
    expect(sourced.when).toBeTruthy();

    const unsourced = formatFactProvenance({ fact: "Lives somewhere", kind: "place" });
    expect(unsourced.source).toBe("held without a source entry");
    expect(unsourced.when).toBe("");

    const missing = formatFactProvenance(null);
    expect(missing.source).toBe("held without a source entry");
    expect(missing.kind).toBe("other");
  });

  test("pairing defaults stay teammate / act / close-loop", () => {
    expect(pairingFromMe(null)).toEqual({
      pairing_style: "teammate",
      act_default: true,
      close_loop: true,
      remember_prefs: true,
    });
    expect(pairingFromMe({ pairing_style: "WAIT", act_default: false })).toEqual({
      pairing_style: "wait",
      act_default: false,
      close_loop: true,
      remember_prefs: true,
    });
    expect(pairingFromMe({ pairing_style: "bogus" }).pairing_style).toBe("teammate");
    expect(pairingPayload({ pairing_style: "proactive", act_default: true, close_loop: false, remember_prefs: true })).toEqual({
      pairing_style: "proactive",
      act_default: true,
      close_loop: false,
      remember_prefs: true,
    });
  });

  test("safe-topic add is unique and capped at 25", () => {
    expect(nextSafeTopics([], "  politics  ")).toEqual(["politics"]);
    expect(nextSafeTopics(["politics"], "politics")).toEqual(["politics"]);
    expect(nextSafeTopics(["a"], "")).toEqual(["a"]);
    const many = Array.from({ length: 25 }, (_, i) => `t${i}`);
    expect(nextSafeTopics(many, "extra")).toHaveLength(25);
  });

  test("heir portal source must not include Memory Studio APIs", () => {
    expect(heirPortalMustExclude("const tabs = ['welcome','letters']")).toBe(true);
    expect(heirPortalMustExclude("navigate('/memory')")).toBe(false);
    expect(heirPortalMustExclude("api.get('/memory/facts')")).toBe(false);
    expect(heirPortalMustExclude("PUT /auth/me/preferences")).toBe(false);
    expect(heirPortalMustExclude("api.put('/nudges/routines')")).toBe(false);
    expect(heirPortalMustExclude("standing_routines")).toBe(false);
  });
});
