import {
  checklistForPath,
  coachHref,
  headsetById,
  headsetHintFromUa,
  isPublicVrSetupRoute,
  isVrSetupRoute,
  matrixRows,
  officialDownloadOnly,
  pathById,
  recommendedPath,
  softwareById,
  vrCatalog,
  vrCoachHomeHref,
  vrMatrixHref,
  vrSetupBase,
} from "./vrCompat";

describe("VR compatibility catalog", () => {
  test("coach and matrix live under owner rooms and public Help", () => {
    expect(isVrSetupRoute("/rooms/vr")).toBe(true);
    expect(isVrSetupRoute("/rooms/vr/matrix")).toBe(true);
    expect(isVrSetupRoute("/support/vr")).toBe(true);
    expect(isPublicVrSetupRoute("/support/vr/matrix")).toBe(true);
    expect(isPublicVrSetupRoute("/rooms/vr")).toBe(false);
    expect(isVrSetupRoute("/rooms/rm_abc/sit")).toBe(false);
    expect(vrSetupBase("/support/vr")).toBe("/support/vr");
    expect(vrMatrixHref("/support/vr")).toBe("/support/vr/matrix");
    expect(vrCoachHomeHref("/support/vr")).toBe("/support");
    expect(vrSetupBase("/rooms/vr")).toBe("/rooms/vr");
  });

  test("tier A vs guided workaround", () => {
    expect(headsetById("quest").tier).toBe("A");
    expect(headsetById("index").tier).toBe("A");
    expect(headsetById("pico").tier).toBe("B");
    expect(headsetById("psvr2").tier).toBe("B");
    expect(headsetById("vision_pro").tier).toBe("C");
    expect(headsetById("cardboard").tier).toBe("C");
    expect(headsetById("wmr").deprecated).toBe(true);
  });

  test("Quest recommends free Link; PSVR2 is not ALVR", () => {
    const quest = headsetById("quest");
    expect(recommendedPath(quest).id).toBe("meta_link");
    expect(softwareById("meta_horizon_link").free).toBe(true);
    const psvr = headsetById("psvr2");
    expect(psvr.paths).not.toContain("alvr");
    expect(pathById("psvr2_adapter").hardware_paid).toBe(true);
    const bodies = checklistForPath("psvr2_adapter").map((s) => s.body).join(" ");
    expect(bodies.toLowerCase()).toMatch(/alvr/);
    expect(bodies).toMatch(/DisplayPort|DP 1\.4/);
  });

  test("Virtual Desktop is paid optional, never a crack", () => {
    const vd = softwareById("virtual_desktop");
    expect(vd.free).toBe(false);
    expect(officialDownloadOnly(vd)).toBe(false);
    expect(vd.url).toMatch(/vrdesktop\.net/);
    expect(vrCatalog().legal.no_cracks).toBe(true);
    expect(JSON.stringify(vrCatalog()).toLowerCase()).not.toMatch(/crackme|nulled/);
  });

  test("ALVR points at GitHub releases", () => {
    expect(softwareById("alvr").url).toBe("https://github.com/alvr-org/ALVR/releases");
    expect(softwareById("pico_connect").url).toContain("picoxr.com");
  });

  test("matrix has a cell per headset path column", () => {
    const rows = matrixRows();
    expect(rows.length).toBe(vrCatalog().headsets.length);
    const quest = rows.find((r) => r.headset.id === "quest");
    const link = quest.cells.find((c) => c.pathId === "meta_link");
    expect(link.supported).toBe(true);
    expect(link.recommended).toBe(true);
    expect(link.free).toBe(true);
    const picoPsvr = rows.find((r) => r.headset.id === "pico").cells.find((c) => c.pathId === "psvr2_adapter");
    expect(picoPsvr.supported).toBe(false);
  });

  test("UA hint and coach deep link", () => {
    expect(headsetHintFromUa("Mozilla/5.0 Quest 3 OculusBrowser").id).toBe("quest");
    expect(headsetHintFromUa("PicoBrowser").id).toBe("pico");
    expect(coachHref("quest", "air_link")).toBe("/rooms/vr?headset=quest&path=air_link");
    expect(coachHref("quest", "air_link", "/support/vr")).toBe(
      "/support/vr?headset=quest&path=air_link",
    );
  });
});
