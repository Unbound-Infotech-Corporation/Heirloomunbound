/** Heirloom Room VR compatibility — catalog helpers. Official free software only. */

import catalog from "../data/vr-headsets.json";

export const VR_SETUP_PATH = "/rooms/vr";
export const VR_MATRIX_PATH = "/rooms/vr/matrix";

export function vrCatalog() {
  return catalog;
}

export function isVrSetupRoute(pathname) {
  const path = String(pathname || "").split("?")[0];
  return path === VR_SETUP_PATH || path.startsWith(`${VR_SETUP_PATH}/`);
}

export function listHeadsets() {
  return catalog.headsets || [];
}

export function headsetById(id) {
  return listHeadsets().find((h) => h.id === id) || null;
}

export function softwareById(id) {
  const all = catalog.software || {};
  return all[id] ? { id, ...all[id] } : null;
}

export function pathById(id) {
  const all = catalog.paths || {};
  return all[id] ? { id, ...all[id] } : null;
}

export function checklistForPath(pathId) {
  const steps = (catalog.checklists || {})[pathId];
  return Array.isArray(steps) ? steps : [];
}

export function pathsForHeadset(headset) {
  const ids = headset?.paths || [];
  return ids.map((id) => pathById(id)).filter(Boolean);
}

export function recommendedPath(headset) {
  if (!headset) return null;
  return pathById(headset.recommended_path) || pathsForHeadset(headset)[0] || null;
}

export function simplePath(headset) {
  if (!headset) return pathById("webxr");
  return pathById(headset.simple_path) || pathById("webxr");
}

export function freeSoftwareLinks(path) {
  const ids = path?.software || [];
  return ids
    .map((id) => softwareById(id))
    .filter((s) => s && s.free !== false && s.kind !== "paid_optional");
}

export function paidOptionalLinks(path) {
  const ids = path?.software || [];
  return ids
    .map((id) => softwareById(id))
    .filter((s) => s && (s.free === false || s.kind === "paid_optional"));
}

export function matrixRows() {
  const pathOrder = [
    "meta_link",
    "air_link",
    "alvr",
    "pico_connect",
    "pico_openxr",
    "psvr2_adapter",
    "steamvr",
    "openxr",
    "webxr",
    "oasis",
    "virtual_desktop",
  ];
  return listHeadsets().map((headset) => ({
    headset,
    cells: pathOrder.map((pathId) => {
      const supported = (headset.paths || []).includes(pathId);
      const path = pathById(pathId);
      return {
        pathId,
        path,
        supported,
        recommended: headset.recommended_path === pathId,
        simple: headset.simple_path === pathId,
        free: path?.free !== false && !path?.optional_paid,
        hardwarePaid: Boolean(path?.hardware_paid),
        optionalPaid: Boolean(path?.optional_paid),
      };
    }),
  }));
}

export function matrixPathColumns() {
  const rows = matrixRows();
  return (rows[0]?.cells || []).map((c) => c.path);
}

export function headsetHintFromUa(ua) {
  const s = String(ua || "").toLowerCase();
  const ranked = listHeadsets().filter((h) => (h.ua || []).some((token) => s.includes(token)));
  if (ranked.length === 1) return ranked[0];
  if (s.includes("quest") || s.includes("oculus")) return headsetById("quest");
  if (s.includes("pico")) return headsetById("pico");
  if (s.includes("xros") || s.includes("visionos")) return headsetById("vision_pro");
  if (ranked.length) return ranked[0];
  return null;
}

export function coachHref(headsetId, pathId) {
  const params = new URLSearchParams();
  if (headsetId) params.set("headset", headsetId);
  if (pathId) params.set("path", pathId);
  const q = params.toString();
  return q ? `${VR_SETUP_PATH}?${q}` : VR_SETUP_PATH;
}

export function tierLabel(tier) {
  return (catalog.tiers || {})[tier]?.label || tier;
}

export function isPaidOptionalSoftware(item) {
  return Boolean(item && (item.free === false || item.kind === "paid_optional"));
}

export function officialDownloadOnly(item) {
  if (!item) return false;
  if (isPaidOptionalSoftware(item)) return false;
  return Boolean(item.url);
}
