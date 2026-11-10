"""Pick a local port and remember the URL the launcher should open."""
from __future__ import annotations

import socket
from pathlib import Path

DEFAULT_PORT = 8788


def choose_port(host: str, preferred: int = DEFAULT_PORT, *, span: int = 20) -> int:
    """Use the preferred port, or the next free one. Does not keep the socket."""
    for port in range(preferred, preferred + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(f"No free port from {preferred} to {preferred + span - 1}")


def write_listen_url(data_dir: Path, url: str) -> Path:
    path = Path(data_dir) / "listen.url"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(url.strip() + "\n", encoding="utf-8")
    return path
