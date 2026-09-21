"""Phase 1 Heirloom Room — mock reconstruction and document shape."""
from rooms import (
    CAPTURE_STATUSES,
    mock_reconstruct,
    new_room_doc,
    placeholder_gltf,
    public_room,
    scene_summary,
)


def test_placeholder_gltf_is_valid_enough():
    gltf = placeholder_gltf(name="The kitchen")
    assert gltf["asset"]["version"] == "2.0"
    assert gltf["meshes"]
    extras = gltf["buffers"][0]["extras"]
    assert len(extras["positions"]) == 24
    assert extras["indices"]
    assert gltf["extras"]["heirloom"]["kind"] == "placeholder_room"
    assert "The kitchen" in gltf["scenes"][0]["name"]


def test_mock_reconstruct_marks_ready_without_vendor():
    room = new_room_doc("user-1", "Study")
    room["room_id"] = "rm_test"
    out = mock_reconstruct(room)
    assert out["capture_status"] == "ready"
    assert out["scene"]["backend"] == "mock"
    assert out["scene"]["format"] == "gltf"
    assert out["job"]["vendor"] is None
    assert out["job"]["error"] is None
    summary = scene_summary(out)
    assert summary["kind"] == "placeholder_room"
    public = public_room(out)
    assert "_id" not in public
    assert public["name"] == "Study"


def test_capture_status_vocabulary():
    assert CAPTURE_STATUSES == ("pending", "processing", "ready", "failed")


def test_new_room_starts_pending():
    room = new_room_doc("abc", "  Living room  ")
    assert room["capture_status"] == "pending"
    assert room["name"] == "Living room"
    assert room["assets"] == []
    assert room["user_id"] == "abc"
