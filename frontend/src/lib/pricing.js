/** One-time Local Edition. Landing, buy, terms, and live pages share this. */

export const LOCAL_EDITION_PRICE = 79.99;
export const LOCAL_EDITION_NAME = "Local Edition";
export const LOCAL_EDITION_BILLING = "one-time";

export function formatPrice(amount = LOCAL_EDITION_PRICE) {
  const value = Number(amount);
  if (!Number.isFinite(value)) return `$${LOCAL_EDITION_PRICE.toFixed(2)}`;
  return `$${value.toFixed(2)}`;
}

export const LOCAL_EDITION_LABEL = formatPrice(LOCAL_EDITION_PRICE);
export const LOCAL_EDITION_LINE = `${LOCAL_EDITION_LABEL} ${LOCAL_EDITION_BILLING} ${LOCAL_EDITION_NAME}`;
