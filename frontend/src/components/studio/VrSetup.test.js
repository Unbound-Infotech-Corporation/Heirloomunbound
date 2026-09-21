import { act } from "react";
import { createRoot } from "react-dom/client";
import { HeadsetArt, StepArt } from "./VrIllustrations";

const mockNavigate = jest.fn();

jest.mock("react-router-dom", () => {
  const React = require("react");
  return {
    Link: ({ to, children, ...rest }) =>
      React.createElement("a", { href: typeof to === "string" ? to : "#", ...rest }, children),
    useSearchParams: () => {
      const raw = String(global.__VR_SEARCH || "").replace(/^\?/, "");
      const params = new URLSearchParams(raw);
      return [params, jest.fn()];
    },
    useLocation: () => ({
      pathname: "/rooms/vr",
      hash: global.__VR_HASH || "",
      search: global.__VR_SEARCH || "",
    }),
    useNavigate: () => mockNavigate,
  };
}, { virtual: true });

const VrSetup = require("../../pages/VrSetup").default;
const VrCompat = require("../../pages/VrCompat").default;

jest.mock("../../lib/api", () => ({
  api: { get: jest.fn().mockRejectedValue(new Error("offline")) },
}));

function mount(ui) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  act(() => {
    root.render(ui);
  });
  return {
    el,
    unmount() {
      act(() => root.unmount());
      el.remove();
    },
  };
}

describe("VR illustrations", () => {
  test("renders headset and step art", () => {
    const { el, unmount } = mount(
      <div>
        <HeadsetArt id="quest" />
        <StepArt id="openxr" />
      </div>,
    );
    expect(el.querySelector('[data-testid="vr-art-quest"]')).toBeTruthy();
    expect(el.querySelector('[data-testid="vr-art-openxr"]')).toBeTruthy();
    unmount();
  });
});

describe("VR setup coach", () => {
  test("Quest USB Link checklist uses the official Meta download", () => {
    global.__VR_SEARCH = "headset=quest&path=meta_link&step=checklist";
    global.__VR_HASH = "";
    const { el, unmount } = mount(<VrSetup />);
    expect(el.querySelector('[data-testid="vr-checklist"]')).toBeTruthy();
    const dl = el.querySelector('[data-testid="vr-dl-meta_horizon_link"]');
    expect(dl.getAttribute("href")).toBe("https://www.oculus.com/download_app/?id=1582076955407037");
    unmount();
  });

  test("PSVR2 checklist is Sony adapter + free Steam app", () => {
    global.__VR_SEARCH = "headset=psvr2&path=psvr2_adapter&step=checklist";
    global.__VR_HASH = "";
    const { el, unmount } = mount(<VrSetup />);
    expect(el.querySelector('[data-testid="vr-checklist"]').textContent).toMatch(/PC adapter/i);
    expect(el.querySelector('[data-testid="vr-dl-psvr2_app"]').getAttribute("href")).toContain(
      "PlayStationVR2_App",
    );
    unmount();
  });
});

describe("VR matrix", () => {
  test("lists Quest and official ALVR releases", () => {
    global.__VR_SEARCH = "";
    const { el, unmount } = mount(<VrCompat />);
    expect(el.querySelector('[data-testid="vr-matrix-row-quest"]')).toBeTruthy();
    expect(el.querySelector('[data-testid="vr-matrix-dl-alvr"]').getAttribute("href")).toBe(
      "https://github.com/alvr-org/ALVR/releases",
    );
    unmount();
  });
});
