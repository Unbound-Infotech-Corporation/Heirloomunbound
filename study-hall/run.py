#!/usr/bin/env python3
"""Launcher for Heirloom Study Hall.

Listens on 127.0.0.1, port 8788, or the next free port. This is a local room, not a public site.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

from studyhall.app import create_app
from studyhall.config import default_data_dir
from studyhall.port import DEFAULT_PORT, choose_port, write_listen_url


def main() -> None:
    host = (os.environ.get("STUDYHALL_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    preferred = int(os.environ.get("STUDYHALL_PORT") or DEFAULT_PORT)
    port = choose_port(host, preferred)
    url = f"http://{host}:{port}"
    write_listen_url(default_data_dir(), url)
    print(f"Study Hall: {url}", flush=True)
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
