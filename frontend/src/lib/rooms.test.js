import {
  canEnterRoom,
  isOwnerRoomsRoute,
  parseRoomGltf,
  roomStatusLabel,
  twinSitHref,
} from "./rooms";
import { isVrSetupRoute, VR_SETUP_PATH } from "./vrCompat";

describe("Heirloom Room helpers", () => {
  test("owner-only path is /rooms", () => {
    expect(isOwnerRoomsRoute("/rooms")).toBe(true);
    expect(isOwnerRoomsRoute("/rooms/rm_abc/sit")).toBe(true);
    expect(isOwnerRoomsRoute("/rooms/vr")).toBe(true);
    expect(isVrSetupRoute(VR_SETUP_PATH)).toBe(true);
    expect(isOwnerRoomsRoute("/heir/abc")).toBe(false);
    expect(isOwnerRoomsRoute("/twin")).toBe(false);
  });

  test("only ready rooms with a scene can be entered", () => {
    expect(canEnterRoom({ capture_status: "pending" })).toBe(false);
    expect(canEnterRoom({ capture_status: "ready" })).toBe(false);
    expect(canEnterRoom({ capture_status: "ready", scene: { format: "gltf" } })).toBe(true);
    expect(roomStatusLabel("ready")).toMatch(/Ready to sit/);
  });

  test("twin sit deep-link carries the room id", () => {
    expect(twinSitHref("rm_abc")).toBe("/twin?room=rm_abc");
  });

  test("gltf extras expose placeholder geometry", () => {
    const parsed = parseRoomGltf({
      scenes: [{ name: "Study" }],
      buffers: [{ extras: { positions: [0, 0, 0], indices: [0, 1, 2] } }],
    });
    expect(parsed.name).toBe("Study");
    expect(parsed.positions).toEqual([0, 0, 0]);
    expect(parsed.indices).toEqual([0, 1, 2]);
  });
});
