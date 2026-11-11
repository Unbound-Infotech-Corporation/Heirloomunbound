"""Filesystem routes belong on the owner's box or desktop, not the hosted site."""
from __future__ import annotations

import os
from pathlib import Path

_ON = frozenset({"1", "true", "yes", "on"})


class WorkstationOnly(Exception):
    """This route is hidden on the hosted service. Map it to HTTP 404."""


class PathRefused(Exception):
    """A path is outside the workspace the owner configured."""


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _ON


def workstation_mode() -> bool:
    """True for a Twin Box or a desktop-local API. False on the hosted site."""
    return _flag("HEIRLOOM_BOX") or _flag("HEIRLOOM_DESKTOP")


def require_workstation() -> None:
    if not workstation_mode():
        raise WorkstationOnly("Not found")


def _split_roots(raw: str) -> list[Path]:
    roots: list[Path] = []
    for part in (raw or "").split(os.pathsep):
        text = part.strip()
        if text:
            roots.append(Path(text).expanduser())
    return roots


def code_roots() -> list[Path]:
    configured = _split_roots(os.environ.get("HEIRLOOM_CODE_ROOTS") or "")
    if configured:
        return configured
    return [Path.home() / "Heirloom" / "workspace"]


def restore_roots() -> list[Path]:
    roots = _split_roots(os.environ.get("HEIRLOOM_RESTORE_ROOTS") or "")
    data = (os.environ.get("HEIRLOOM_DATA_ROOT") or "").strip()
    if data:
        roots.append(Path(data).expanduser())
    if roots:
        return roots
    return [Path.home() / "Heirloom"]


def path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.expanduser().resolve())
    except (ValueError, OSError):
        return False
    return True


def path_is_under_any(path: Path, roots: list[Path]) -> bool:
    return any(path_is_under(path, root) for root in roots)


def assert_restore_path(raw: str) -> Path:
    """Refuse a restore source or destination outside the restore roots."""
    text = (raw or "").strip()
    if not text:
        raise PathRefused("Choose a folder inside the Heirloom restore workspace.")
    path = Path(text)
    if not path_is_under_any(path, restore_roots()):
        raise PathRefused("That folder is outside the Heirloom restore workspace.")
    return path.resolve()
