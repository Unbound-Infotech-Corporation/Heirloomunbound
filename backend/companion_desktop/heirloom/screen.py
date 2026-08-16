"""Grab a still of the owner's screen for the twin to look at.

mss is preferred because it can capture fullscreen games that GDI/ImageGrab
misses. We capture the primary monitor only so text and HUD stay readable.
The JPEG is uploaded, analysed, then deleted on the server — never kept.
"""
from __future__ import annotations

import io


def grab_screen_jpeg(*, max_width: int = 1920, quality: int = 85) -> bytes:
    """Return a JPEG of the primary monitor. Raises if capture is impossible."""
    img = _grab_primary()
    img = img.convert("RGB")
    if img.width > max_width > 0:
        height = max(1, int(img.height * max_width / img.width))
        img = img.resize((max_width, height))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=max(60, min(95, int(quality))))
    return buf.getvalue()


def _grab_primary():
    # mss first — better for DirectX / fullscreen games than ImageGrab.
    try:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            monitors = sct.monitors
            # monitors[0] is the virtual desktop (all screens). Prefer [1].
            mon = monitors[1] if len(monitors) > 1 else monitors[0]
            raw = sct.grab(mon)
            return Image.frombytes("RGB", raw.size, raw.rgb)
    except Exception:
        from PIL import ImageGrab

        img = ImageGrab.grab()
        if img is None:
            raise RuntimeError("screen capture returned nothing")
        return img
