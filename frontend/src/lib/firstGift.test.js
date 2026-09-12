import {
  FIRST_GIFT,
  FIRST_GIFT_SAMPLE,
  FIRST_GIFT_TAGLINE,
  firstGiftDraft,
  isFirstGiftSearch,
} from "./firstGift";

describe("First Gift deep-link presets", () => {
  test("compose path opens sealed letters with gift flag", () => {
    expect(FIRST_GIFT.composePath).toBe("/letters?gift=1");
    expect(isFirstGiftSearch("?gift=1")).toBe(true);
    expect(isFirstGiftSearch(new URLSearchParams("gift=1"))).toBe(true);
    expect(isFirstGiftSearch("?firstGift=true")).toBe(true);
    expect(isFirstGiftSearch("?first=yes")).toBe(true);
  });

  test("ordinary letters URL does not apply the gift preset", () => {
    expect(isFirstGiftSearch("")).toBe(false);
    expect(isFirstGiftSearch("?gift=0")).toBe(false);
    expect(isFirstGiftSearch(new URLSearchParams())).toBe(false);
  });

  test("draft defaults to My children + on_release with a blank body", () => {
    const draft = firstGiftDraft();
    expect(draft.recipient_name).toBe("My children");
    expect(draft.trigger).toBe("on_release");
    expect(draft.body).toBe("");
    expect(draft.title).toBe("");
    expect(draft.recipient_heir_id).toBe("");
  });

  test("never invents biography in the empty composer", () => {
    const draft = firstGiftDraft();
    expect(draft.body).toBe("");
    expect(FIRST_GIFT.bodyPlaceholder).toMatch(/What do you want them to know/);
    expect(FIRST_GIFT.bodyPlaceholder).not.toMatch(/Elias|I remember when/);
    expect(FIRST_GIFT_TAGLINE).toBe("Not a chatbot. A gift.");
  });

  test("sample letter is labeled SAMPLE and is not used as the draft body", () => {
    expect(FIRST_GIFT_SAMPLE.label).toBe("SAMPLE");
    expect(FIRST_GIFT_SAMPLE.body).toMatch(/SAMPLE/);
    expect(firstGiftDraft().body).not.toBe(FIRST_GIFT_SAMPLE.body);
  });
});
