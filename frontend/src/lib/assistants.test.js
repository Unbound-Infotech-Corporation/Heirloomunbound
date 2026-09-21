import {
  isPcSpecialist,
  matchAssistant,
  parseAssistantMention,
  slugifyAssistant,
  speakerLabel,
  speakerOptions,
} from "./assistants";

const ASSISTANTS = [
  {
    assistant_id: "ast_research",
    slug: "research",
    name: "Research",
    enabled: true,
    speak_as: "specialist",
    tools_allowlist: ["web_search"],
  },
  {
    assistant_id: "ast_pc",
    slug: "pc",
    name: "PC",
    enabled: true,
    speak_as: "assist",
    tools_allowlist: ["open_on_pc"],
  },
  {
    assistant_id: "ast_off",
    slug: "quiet",
    name: "Quiet",
    enabled: false,
    tools_allowlist: ["web_search"],
  },
];

describe("Twin assistants", () => {
  test("Twin remains the default speaker", () => {
    const opts = speakerOptions(ASSISTANTS);
    expect(opts[0].name).toBe("Twin");
    expect(opts[0].assistant_id).toBeNull();
    expect(opts.map((o) => o.slug)).toEqual(["twin", "research", "pc"]);
  });

  test("@mention parse and match", () => {
    const parsed = parseAssistantMention("@Research look this up");
    expect(parsed.mention).toBe("Research");
    expect(parsed.remainder).toBe("look this up");
    expect(matchAssistant(ASSISTANTS, { mention: "research" }).slug).toBe("research");
    expect(matchAssistant(ASSISTANTS, { mention: "quiet" })).toBeNull();
  });

  test("PC specialist is Assist, not the twin", () => {
    expect(isPcSpecialist(ASSISTANTS[1])).toBe(true);
    expect(isPcSpecialist(ASSISTANTS[0])).toBe(false);
    expect(slugifyAssistant("Letters & notes")).toBe("letters-notes");
  });

  test("speaker label prefers specialist_name", () => {
    expect(speakerLabel({ specialist_name: "Research" }, ASSISTANTS)).toBe("Research");
    expect(speakerLabel({ role: "assistant" }, ASSISTANTS)).toBe("you (the twin)");
  });
});
