/** Heirloom Room helpers — owner-only spatial capture. */

export const ROOMS_PATH = "/rooms";

export const CAPTURE_HINTS = [
  "Walk the room slowly. Overlap each pass.",
  "Film every wall, the floor, the ceiling, and the corners.",
  "Photograph furniture from more than one height.",
  "Steady light helps. A circling phone video plus stills of the corners is enough for Phase 1.",
];

export const STATUS_LABEL = {
  pending: "Waiting for capture",
  processing: "Building a stand-in scene",
  ready: "Ready to sit",
  failed: "Couldn't build this scene",
};

export function isOwnerRoomsRoute(pathname) {
  const path = String(pathname || "").split("?")[0];
  return path === ROOMS_PATH || path.startsWith(`${ROOMS_PATH}/`);
}

export function roomStatusLabel(status) {
  const key = String(status || "pending").toLowerCase();
  return STATUS_LABEL[key] || STATUS_LABEL.pending;
}

export function canEnterRoom(room) {
  return Boolean(room && room.capture_status === "ready" && room.scene);
}

export function twinSitHref(roomId) {
  const id = String(roomId || "").trim();
  if (!id) return "/twin";
  return `/twin?room=${encodeURIComponent(id)}`;
}

export function parseRoomGltf(gltf) {
  const extras = (((gltf || {}).buffers || [])[0] || {}).extras || {};
  const positions = Array.isArray(extras.positions) ? extras.positions : [];
  const indices = Array.isArray(extras.indices) ? extras.indices : [];
  return { positions, indices, name: gltf?.scenes?.[0]?.name || "Heirloom Room" };
}
