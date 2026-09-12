/** First Gift — owner vault path into existing sealed letters.
 *
 * Deep-link: /letters?gift=1
 * Presets only. Never invent biography or a letter body.
 */

export const FIRST_GIFT_TAGLINE = "Not a chatbot. A gift.";

export const FIRST_GIFT = {
  recipientName: "My children",
  trigger: "on_release",
  title: "",
  body: "",
  composePath: "/letters?gift=1",
  momentPath: "/first-gift",
  titlePlaceholder: "A title they will see first — leave blank if you like",
  bodyPlaceholder:
    "What do you want them to know, later?\n\nA memory they were too young to keep.\nSomething you hope they never doubt.\nOne ordinary day you do not want lost.",
};

/** Clearly labeled SAMPLE — not the owner's life, not a pre-filled draft. */
export const FIRST_GIFT_SAMPLE = {
  label: "SAMPLE",
  to: "My children",
  title: "When you open this",
  sealedCaption: "Sealed until the heir is released",
  openCaption: "Opened — this is a sample, not a real letter",
  body:
    "I wrote this while the house was quiet, so you would have my voice later — in my own words, not a machine speaking for me.\n\nWhen you read this, I hope you already know I loved you. This letter is only proof that I sat down and made it last.\n\nThis is a SAMPLE. Write yours in your own words.",
};

const TRUTHY = new Set(["1", "true", "yes", "gift"]);

export function isFirstGiftSearch(search) {
  const params =
    search instanceof URLSearchParams ? search : new URLSearchParams(search || "");
  const raw = (
    params.get("gift") ||
    params.get("firstGift") ||
    params.get("first") ||
    ""
  )
    .toString()
    .trim()
    .toLowerCase();
  return TRUTHY.has(raw);
}

export function firstGiftDraft(overrides = {}) {
  return {
    title: FIRST_GIFT.title,
    body: FIRST_GIFT.body,
    recipient_heir_id: "",
    recipient_name: FIRST_GIFT.recipientName,
    trigger: FIRST_GIFT.trigger,
    delivery_date: "",
    delivery_age: "",
    ...overrides,
  };
}
