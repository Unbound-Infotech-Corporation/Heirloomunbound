#!/usr/bin/env python3
"""Launcher for Heirloom Study Hall.

Listens on 127.0.0.1:8787. This is a local room for the owner, not a public site.
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


def main() -> None:
    host = (os.environ.get("STUDYHALL_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("STUDYHALL_PORT") or "8787")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
