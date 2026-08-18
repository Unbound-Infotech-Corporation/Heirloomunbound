"""Native WinUI sideload kit — unit tests, no live deploy required."""
from __future__ import annotations

import io
import zipfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from routers.companion import WINUI_README, build_winui_sideload_zip_bytes


def test_winui_sideload_zip_contains_readme():
    data = build_winui_sideload_zip_bytes("comp_test_token")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        assert "README.txt" in names
        assert "PAIR.txt" in names
        assert b"WinUI" in z.read("README.txt")
        assert b"comp_test_token" in z.read("PAIR.txt")
        assert "UnboundInfotech.Heirloom" in WINUI_README
