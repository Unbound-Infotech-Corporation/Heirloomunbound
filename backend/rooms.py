"""Heirloom Room — capture a physical place, reconstruct later, sit with the twin.

Phase 1: owner-owned rooms with a pluggable reconstruction job. The default
backend is a **dev/mock** path that marks a room ready and attaches a
placeholder glTF scene (a simple enclosed volume). No paid photogrammetry,
NeRF, or splat vendor is required to merge.

Phase 2 (see UNBOUND.md): real capture vendors, Gaussian splat / photogrammetry,
Quest packaging, heir-enter-a-released-room.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

CAPTURE_STATUSES = ("pending", "processing", "ready", "failed")
SCENE_FORMAT = "gltf"
MAX_ASSETS = 24
MAX_BYTES = 50 * 1024 * 1024  # 50 MB per file
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/heic",
    "image/heif",
}
ALLOWED_VIDEO_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES

# Capture guidance shown in the studio (film from many angles).
CAPTURE_INSTRUCTIONS = (
    "Walk the room slowly. Film or photograph every wall, the floor, the ceiling, "
    "corners, and the furniture from several heights. Overlap each pass. Steady light "
    "helps. A phone video that circles the space once, then a second pass of stills "
    "of the corners, is enough for Phase 1."
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_room(doc: dict) -> dict:
    """Strip Mongo id; never leak storage internals beyond path metadata."""
    if not doc:
        return {}
    out = {k: v for k, v in doc.items() if k != "_id"}
    out.setdefault("assets", [])
    out.setdefault("scene", None)
    out.setdefault("job", None)
    return out


def placeholder_gltf(*, name: str = "Heirloom Room") -> dict:
    """Minimal glTF 2.0 of an enclosed volume. Documented export for Phase 2.

    Positions are metres. Origin is the centre of the floor. A headset or
    three.js viewer can load this as-is; a Gaussian splat vendor would replace
    `scene` + `meshes` later without changing the Room document shape.
    """
    title = (name or "Heirloom Room").strip()[:80] or "Heirloom Room"
    # Unit box: 4m x 3m x 4m. 8 corners, 12 triangles (floor + 4 walls, no ceiling
    # so the placeholder feels like a sitting room rather than a closed crate).
    positions = [
        -2.0, 0.0, -2.0,
         2.0, 0.0, -2.0,
         2.0, 0.0,  2.0,
        -2.0, 0.0,  2.0,
        -2.0, 2.6, -2.0,
         2.0, 2.6, -2.0,
         2.0, 2.6,  2.0,
        -2.0, 2.6,  2.0,
    ]
    indices = [
        0, 1, 2, 0, 2, 3,  # floor
        0, 1, 5, 0, 5, 4,  # -Z wall
        1, 2, 6, 1, 6, 5,  # +X
        2, 3, 7, 2, 7, 6,  # +Z
        3, 0, 4, 3, 4, 7,  # -X
    ]
    return {
        "asset": {
            "version": "2.0",
            "generator": "Heirloom Room mock (Phase 1)",
            "copyright": title,
        },
        "scene": 0,
        "scenes": [{"name": title, "nodes": [0]}],
        "nodes": [{"name": "room", "mesh": 0}],
        "meshes": [
            {
                "name": "placeholder_volume",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "mode": 4,
                    }
                ],
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 8,
                "type": "VEC3",
                "min": [-2.0, 0.0, -2.0],
                "max": [2.0, 2.6, 2.0],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": len(indices),
                "type": "SCALAR",
            },
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions) * 4, "target": 34962},
            {"buffer": 0, "byteOffset": len(positions) * 4, "byteLength": len(indices) * 2, "target": 34963},
        ],
        "buffers": [
            {
                "byteLength": len(positions) * 4 + len(indices) * 2,
                "extras": {
                    "positions": positions,
                    "indices": indices,
                    "note": "Phase 1 inline geometry. Phase 2 may replace with a URI to a .bin / splat.",
                },
            }
        ],
        "extras": {
            "heirloom": {
                "kind": "placeholder_room",
                "format": SCENE_FORMAT,
                "phase": 1,
            }
        },
    }


def mock_reconstruct(room: dict) -> dict:
    """Dev/mock reconstruction: pending/processing → ready with placeholder scene.

    Never calls a paid API. Optional vendor hooks live on `job.vendor` only.
    """
    now = now_iso()
    status = (room.get("capture_status") or "pending").strip().lower()
    if status == "ready" and room.get("scene"):
        return room
    if status == "failed":
        # Mock path can retry.
        pass
    scene = {
        "format": SCENE_FORMAT,
        "kind": "placeholder_room",
        "gltf": placeholder_gltf(name=room.get("name") or "Heirloom Room"),
        "ready_at": now,
        "backend": "mock",
    }
    job = dict(room.get("job") or {})
    job.update(
        {
            "backend": job.get("backend") or "mock",
            "vendor": job.get("vendor"),  # optional integration point only
            "started_at": job.get("started_at") or now,
            "finished_at": now,
            "error": None,
        }
    )
    room["capture_status"] = "ready"
    room["scene"] = scene
    room["job"] = job
    room["updated_at"] = now
    return room


def mark_processing(room: dict, *, backend: str = "mock", vendor: Optional[str] = None) -> dict:
    now = now_iso()
    room["capture_status"] = "processing"
    room["job"] = {
        "backend": backend or "mock",
        "vendor": vendor,
        "started_at": now,
        "finished_at": None,
        "error": None,
    }
    room["updated_at"] = now
    return room


def mark_failed(room: dict, error: str) -> dict:
    now = now_iso()
    job = dict(room.get("job") or {})
    job.update({"finished_at": now, "error": (error or "reconstruction failed")[:400]})
    room["capture_status"] = "failed"
    room["job"] = job
    room["updated_at"] = now
    return room


def asset_kind(content_type: str) -> str:
    ct = (content_type or "").lower()
    if ct in ALLOWED_VIDEO_TYPES:
        return "video"
    return "image"


def new_room_doc(user_id: str, name: str) -> dict:
    title = (name or "").strip()[:80] or "Untitled room"
    return {
        "room_id": "",  # filled by router
        "user_id": user_id,
        "name": title,
        "capture_status": "pending",
        "assets": [],
        "scene": None,
        "job": {"backend": "mock", "vendor": None, "started_at": None, "finished_at": None, "error": None},
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def scene_summary(room: dict) -> Optional[dict]:
    scene = room.get("scene") or None
    if not scene:
        return None
    return {
        "format": scene.get("format") or SCENE_FORMAT,
        "kind": scene.get("kind") or "placeholder_room",
        "backend": scene.get("backend") or (room.get("job") or {}).get("backend") or "mock",
        "ready_at": scene.get("ready_at"),
    }
