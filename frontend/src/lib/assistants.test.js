import {
  cloneIdOf,
  isPcSpecialist,
  matchAssistant,
  parseAssistantMention,
  slugifyAssistant,
  speakerLabel,
  speakerOptions,
} from "./assistants";

const CLONES = [
  {
    clone_id: "cln_research",
    assistant_id: "cln_research",
    slug: "research",
    name: "Research",
    enabled: true,
    speak_as: "specialist",
    tools_allowlist: ["web_search"],
  },
  {
    clone_id: "cln_pc",
    assistant_id: "cln_pc",
    slug: "pc",
    name: "PC",
    enabled: true,
    speak_as: "assist",
    tools_allowlist: ["open_on_pc"],
  },
  {
    clone_id: "cln_off",
    slug: "quiet",
    name: "Quiet",
    enabled: false,
    tools_allowlist: ["web_search"],
  },
];

describe("Twin clones", () => {
  test("Twin remains the default speaker", () => {
    const opts = speakerOptions(CLONES);
    expect(opts[0].name).toBe("Twin");
    expect(opts[0].clone_id).toBeNull();
    expect(opts.map((o) => o.slug)).toEqual(["twin", "research", "pc"]);
  });

  test("@mention parse and match", () => {
    const parsed = parseAssistantMention("@Research look this up");
    expect(parsed.mention).toBe("Research");
    expect(parsed.remainder).toBe("look this up");
    expect(matchAssistant(CLONES, { mention: "research" }).slug).toBe("research");
    expect(matchAssistant(CLONES, { mention: "quiet" })).toBeNull();
    expect(cloneIdOf(CLONES[0])).toBe("cln_research");
  });

  test("PC clone is Assist, not the twin", () => {
    expect(isPcSpecialist(CLONES[1])).toBe(true);
    expect(isPcSpecialist(CLONES[0])).toBe(false);
    expect(slugifyAssistant("Letters & notes")).toBe("letters-notes");
  });

  test("speaker label prefers specialist_name", () => {
    expect(speakerLabel({ specialist_name: "Research" }, CLONES)).toBe("Research");
    expect(speakerLabel({ clone_id: "cln_pc" }, CLONES)).toBe("PC");
    expect(speakerLabel({ role: "assistant" }, CLONES)).toBe("you (the twin)");
  });
});
