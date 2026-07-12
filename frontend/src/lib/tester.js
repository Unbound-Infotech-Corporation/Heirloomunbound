// Tester mode — a browser-local flag so invited testers never hit the paid
// funnel. Set it by visiting /test (the shareable tester link); it hides Buy /
// upgrade CTAs so nobody accidentally pays. The real sales funnel is untouched
// for normal visitors.
const KEY = "heirloom_tester";

export const isTester = () => {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch (_) {
    return false;
  }
};

export const setTester = (on) => {
  try {
    if (on) localStorage.setItem(KEY, "1");
    else localStorage.removeItem(KEY);
  } catch (_) {
    /* noop */
  }
};
