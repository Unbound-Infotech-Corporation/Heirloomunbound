import { LOCAL_EDITION_LABEL, LOCAL_EDITION_LINE, LOCAL_EDITION_PRICE, formatPrice } from "./pricing";

describe("Local Edition price", () => {
  test("is the one-time 79.99 price", () => {
    expect(LOCAL_EDITION_PRICE).toBe(79.99);
    expect(LOCAL_EDITION_LABEL).toBe("$79.99");
    expect(LOCAL_EDITION_LINE).toBe("$79.99 one-time Local Edition");
    expect(formatPrice(79.99)).toBe("$79.99");
    expect(LOCAL_EDITION_LINE).not.toMatch(/lifetime/i);
  });
});
