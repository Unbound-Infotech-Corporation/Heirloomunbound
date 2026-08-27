#!/usr/bin/env python3
"""Heirloom Video studio sidecar: probe engines, living stills, concat.

Does not open ComfyUI, Pinokio, or a browser. Prints STATUS: lines, then one JSON object.
Motion models (Wan, LTX, Hunyuan) are used only when already on disk or ComfyUI is already running.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path


def status(msg: str) -> None:
    print(f"STATUS: {msg}", flush=True)


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def engine_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("HEIRLOOM_AVATAR_ENGINE", "").strip()
    if env:
        return Path(env)
    if Path("F:/HeirloomModels").exists() or Path("F:/").exists():
        return Path("F:/HeirloomModels/avatar-engine")
    local = Path(os.environ.get("LOCALAPPDATA", ".")) / "Heirloom" / "engines" / "avatar"
    return local


def ffmpeg_exe(root: Path) -> Path | None:
    bundled = root / "ffmpeg" / "ffmpeg.exe"
    if bundled.is_file():
        return bundled
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def probe_comfy(url: str) -> dict:
    base = (url or "").rstrip("/")
    if not base:
        return {"ok": False, "url": "", "engines": []}
    try:
        with urllib.request.urlopen(base + "/system_stats", timeout=2) as resp:
            resp.read(200)
        engines: list[str] = []
        try:
            with urllib.request.urlopen(base + "/object_info", timeout=4) as resp:
                info = json.loads(resp.read().decode("utf-8", "replace"))
            keys = " ".join(info.keys()).lower()
            if "ltx" in keys:
                engines.append("ltx")
            if "wan" in keys:
                engines.append("wan")
            if "hunyuan" in keys or "hyvideo" in keys:
                engines.append("hunyuan")
        except Exception:
            pass
        return {"ok": True, "url": base, "engines": engines}
    except Exception as exc:
        return {"ok": False, "url": base, "error": str(exc), "engines": []}


def scan_models() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {"ltx": [], "wan": [], "hunyuan": []}
    roots: list[Path] = []
    for raw in [
        os.environ.get("HEIRLOOM_MODELS", ""),
        r"F:\HeirloomModels",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Heirloom" / "models"),
        str(Path.home() / "ComfyUI" / "models" / "checkpoints"),
        str(Path.home() / "ComfyUI" / "models" / "diffusion_models"),
        r"C:\ComfyUI\models\checkpoints",
        r"C:\ComfyUI\models\diffusion_models",
    ]:
        if raw:
            roots.append(Path(raw))
    needles = {
        "ltx": ("ltx", "ltxv"),
        "wan": ("wan2", "wan-ai", "wan_"),
        "hunyuan": ("hunyuanvideo", "hunyuan-video", "hyvideo"),
    }
    for root in roots:
        if not root.exists():
            continue
        try:
            children = list(root.glob("*")) + list(root.glob("*/*")) + list(root.glob("*/*/*"))
        except OSError:
            continue
        for path in children:
            name = path.name.lower()
            path_s = str(path).lower().replace("\\", "/")
            for engine, tokens in needles.items():
                if any(token in name or token in path_s for token in tokens):
                    if str(path) not in found[engine]:
                        found[engine].append(str(path))
                    break
    return found


def run_ffmpeg(ffmpeg: Path, args: list[str]) -> None:
    cmd = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
        raise RuntimeError(err[-400:])


def living_still(ffmpeg: Path, image: str, audio: str | None, seconds: int, out: Path) -> None:
    status("Holding the photograph while the voice plays…")
    vf = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black"
    args: list[str] = ["-loop", "1", "-i", image]
    if audio:
        args += ["-i", audio, "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac", "-shortest"]
    else:
        args += ["-t", str(max(2, seconds)), "-c:v", "libx264", "-tune", "stillimage", "-an"]
    args += ["-pix_fmt", "yuv420p", "-vf", vf, "-r", "24", str(out)]
    run_ffmpeg(ffmpeg, args)


def concat(ffmpeg: Path, clips: list[str], out: Path) -> None:
    status("Joining the shots into one film…")
    listing = out.with_suffix(".concat.txt")
    lines = []
    for clip in clips:
        safe = Path(clip).resolve().as_posix().replace("'", r"'\''")
        lines.append(f"file '{safe}'")
    listing.write_text("\n".join(lines), encoding="utf-8")
    try:
        run_ffmpeg(
            ffmpeg,
            ["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)],
        )
    except RuntimeError:
        status("Re-encoding the film so every shot matches…")
        run_ffmpeg(
            ffmpeg,
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(out),
            ],
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="")
    parser.add_argument("--comfy", default=os.environ.get("HEIRLOOM_COMFY_URL", "http://127.0.0.1:8188"))
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--hold", action="store_true")
    parser.add_argument("--concat", action="store_true")
    parser.add_argument("--image", default="")
    parser.add_argument("--audio", default="")
    parser.add_argument("--seconds", type=int, default=6)
    parser.add_argument("--clips", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    root = engine_root(args.root or None)
    ffmpeg = ffmpeg_exe(root)
    comfy = probe_comfy(args.comfy)
    disk = scan_models()

    if args.probe:
        emit(
            {
                "ok": True,
                "ffmpeg": str(ffmpeg) if ffmpeg else "",
                "comfy_ok": bool(comfy.get("ok")),
                "comfy_engines": comfy.get("engines") or [],
                "ltx": bool(disk["ltx"] or "ltx" in (comfy.get("engines") or [])),
                "wan": bool(disk["wan"] or "wan" in (comfy.get("engines") or [])),
                "hunyuan": bool(disk["hunyuan"] or "hunyuan" in (comfy.get("engines") or [])),
                "paths": {k: v[:4] for k, v in disk.items()},
            }
        )
        return 0

    if not ffmpeg:
        emit({"ok": False, "error": "FFmpeg is not on this PC yet. Fetch the talking-picture engine once — it brings FFmpeg with it."})
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        if args.hold:
            if not args.image or not Path(args.image).is_file():
                emit({"ok": False, "error": "Need a photograph on disk for this beat."})
                return 1
            audio = args.audio if args.audio and Path(args.audio).is_file() else None
            living_still(ffmpeg, args.image, audio, args.seconds, out)
            emit({"ok": True, "path": str(out), "engine": "living-still"})
            return 0

        if args.concat:
            clips = [c for c in args.clips.split("|") if c and Path(c).is_file()]
            if not clips:
                emit({"ok": False, "error": "No shots were ready to join."})
                return 1
            concat(ffmpeg, clips, out)
            emit({"ok": True, "path": str(out), "engine": "concat"})
            return 0

        emit({"ok": False, "error": "Need --probe, --hold, or --concat."})
        return 1
    except Exception as exc:
        emit({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
