"""Object storage is a local directory unless the web deployment opts into Emergent."""
from __future__ import annotations

import pytest

import storage


def test_default_storage_is_the_local_filesystem(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("HEIRLOOM_STORAGE", raising=False)
    monkeypatch.delenv("HEIRLOOM_BOX", raising=False)

    def boom(*_args, **_kwargs):
        raise AssertionError("Emergent object storage was called")

    monkeypatch.setattr(storage.requests, "post", boom)
    monkeypatch.setattr(storage.requests, "put", boom)
    monkeypatch.setattr(storage.requests, "get", boom)
    storage._storage_key = None

    assert storage.storage_backend() == "local"
    assert storage.init_storage() == "local"
    saved = storage.put_object("heirloom/photos/owner/note.bin", b"abc", "application/octet-stream")
    assert saved["path"] == "heirloom/photos/owner/note.bin"
    assert saved["size"] == 3
    data, ctype = storage.get_object(saved["path"])
    assert data == b"abc"
    assert ctype == "application/octet-stream"
    with pytest.raises(ValueError):
        storage.put_object("../outside.bin", b"no", "text/plain")


def test_box_mode_refuses_emergent_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("HEIRLOOM_BOX", "1")
    monkeypatch.setenv("HEIRLOOM_STORAGE", "emergent")
    storage._logged_box_override = False
    assert storage.storage_backend() == "local"
    saved = storage.put_object("heirloom/a.txt", b"local", "text/plain")
    assert storage.get_object(saved["path"])[0] == b"local"


def test_web_can_opt_into_emergent_storage(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_BOX", raising=False)
    monkeypatch.setenv("HEIRLOOM_STORAGE", "emergent")
    assert storage.storage_backend() == "emergent"
