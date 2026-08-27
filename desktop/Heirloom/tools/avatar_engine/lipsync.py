#!/usr/bin/env python3
"""Heirloom sitting lip-sync: ByteDance LatentSync 1.6, optional ComfyUI probe.

Does not open Pinokio, Gradio, or a browser. Prints STATUS: lines, then one JSON object.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_URL = "https://github.com/bytedance/LatentSync.git"
FFMPEG_ZIP = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
UNET_REPO = "ByteDance/LatentSync-1.6"


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


def models_root(root: Path) -> Path:
    return root.parent if root.name == "avatar-engine" else root


def apply_cache_env(root: Path) -> None:
    models = models_root(root)
    os.environ.setdefault("UV_PYTHON_INSTALL_DIR", str(models / "python"))
    os.environ.setdefault("UV_CACHE_DIR", str(models / "uv-cache"))
    os.environ.setdefault("HF_HOME", str(models / "hf"))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(models / "hf" / "hub"))
    os.environ.setdefault("PIP_CACHE_DIR", str(models / "pip-cache"))
    os.environ.setdefault("TORCH_HOME", str(models / "torch"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def repo_dir(root: Path) -> Path:
    return root / "LatentSync"


def venv_python(root: Path) -> Path:
    return root / ".venv" / "Scripts" / "python.exe"


def ffmpeg_exe(root: Path) -> Path | None:
    bundled = root / "ffmpeg" / "ffmpeg.exe"
    if bundled.is_file():
        return bundled
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def checkpoints_ready(root: Path) -> bool:
    ckpt = repo_dir(root) / "checkpoints"
    return (ckpt / "latentsync_unet.pt").is_file() and (ckpt / "whisper" / "tiny.pt").is_file()


def probe_comfy(url: str) -> dict:
    base = url.rstrip("/")
    try:
        import urllib.request as u

        with u.urlopen(base + "/system_stats", timeout=2) as resp:
            body = resp.read()[:400]
        nodes = []
        try:
            with u.urlopen(base + "/object_info", timeout=3) as resp:
                info = json.loads(resp.read().decode("utf-8", "replace"))
            nodes = [name for name in info if "latent" in name.lower() or "musetalk" in name.lower() or "lipsync" in name.lower()]
        except Exception:
            pass
        return {"ok": True, "url": base, "nodes": nodes[:12]}
    except Exception as exc:
        return {"ok": False, "url": base, "error": str(exc)}


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    status(" ".join(cmd[:6]) + (" …" if len(cmd) > 6 else ""))
    proc = subprocess.run(cmd, cwd=cwd, env=merged, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def ensure_uv() -> list[str]:
    try:
        subprocess.run([sys.executable, "-m", "uv", "--version"], check=True, capture_output=True)
        return [sys.executable, "-m", "uv"]
    except Exception:
        status("Installing uv into this Python")
        run([sys.executable, "-m", "pip", "install", "--user", "uv"])
        return [sys.executable, "-m", "uv"]


def ensure_venv(root: Path) -> Path:
    py = venv_python(root)
    uv = ensure_uv()
    if not py.is_file():
        status("Installing Python 3.10 for LatentSync")
        run(uv + ["python", "install", "3.10"])
        status("Creating engine venv")
        run(uv + ["venv", str(root / ".venv"), "--python", "3.10", "--seed"])
    if not py.is_file():
        raise RuntimeError("venv python missing after uv venv")
    return py


def uv_pip(py: Path, args: list[str]) -> None:
    uv = ensure_uv()
    last_error = None
    for attempt in range(1, 4):
        try:
            run(uv + ["pip", "install", "--python", str(py)] + args)
            return
        except RuntimeError as exc:
            last_error = exc
            status(f"pip install retry {attempt}/3: {exc}")
    raise last_error if last_error else RuntimeError("pip install failed")


def ensure_repo(root: Path) -> Path:
    dest = repo_dir(root)
    if (dest / "scripts" / "inference.py").is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    git = shutil.which("git")
    if git:
        status("Cloning ByteDance LatentSync")
        run([git, "clone", "--depth", "1", REPO_URL, str(dest)])
        return dest
    status("git missing — downloading LatentSync zip")
    zip_path = root / "LatentSync.zip"
    urllib.request.urlretrieve("https://github.com/bytedance/LatentSync/archive/refs/heads/main.zip", zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(root / "_extract")
    extracted = next((root / "_extract").glob("LatentSync-*"))
    shutil.move(str(extracted), str(dest))
    zip_path.unlink(missing_ok=True)
    shutil.rmtree(root / "_extract", ignore_errors=True)
    return dest


def patch_face_detector(dest: Path) -> None:
    path = dest / "latentsync" / "utils" / "face_detector.py"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    old = 'providers=["CUDAExecutionProvider"],'
    new = 'providers=["CUDAExecutionProvider", "CPUExecutionProvider"],'
    if old in text and new not in text:
        path.write_text(text.replace(old, new), encoding="utf-8")
        status("Face detector will fall back to CPU ONNX if CUDA EP is missing")


def ensure_ffmpeg(root: Path) -> Path:
    existing = ffmpeg_exe(root)
    if existing:
        return existing
    status("Downloading ffmpeg")
    zip_path = root / "ffmpeg.zip"
    urllib.request.urlretrieve(FFMPEG_ZIP, zip_path)
    extract = root / "_ffmpeg"
    extract.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract)
    exe = next(extract.rglob("ffmpeg.exe"))
    target_dir = root / "ffmpeg"
    target_dir.mkdir(exist_ok=True)
    shutil.copy2(exe, target_dir / "ffmpeg.exe")
    ffprobe = exe.with_name("ffprobe.exe")
    if ffprobe.is_file():
        shutil.copy2(ffprobe, target_dir / "ffprobe.exe")
    zip_path.unlink(missing_ok=True)
    shutil.rmtree(extract, ignore_errors=True)
    return target_dir / "ffmpeg.exe"


def ensure_python_deps(py: Path, dest: Path) -> None:
    status("Installing PyTorch CUDA 12.8 (RTX 50-class)")
    uv_pip(
        py,
        [
            "torch",
            "torchvision",
            "torchaudio",
            "--index-url",
            "https://download.pytorch.org/whl/cu128",
        ],
    )
    req = dest / "requirements.txt"
    filtered = dest / "requirements.heirloom.txt"
    skip = {"torch", "torchvision", "torchaudio", "gradio", "decord"}
    lines = []
    if req.is_file():
        for raw in req.read_text(encoding="utf-8").splitlines():
            s = raw.strip()
            if not s or s.startswith("#") or s.startswith("--"):
                continue
            name = s.split("==")[0].split(">=")[0].split("[")[0].strip().lower()
            if name in skip:
                continue
            if name in {"onnxruntime-gpu", "huggingface-hub", "huggingface_hub"}:
                continue
            lines.append(s)
    lines += ["onnxruntime", "soundfile", "imageio-ffmpeg", "huggingface_hub"]
    filtered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    status("Installing LatentSync Python packages")
    uv_pip(py, ["-r", str(filtered)])


def ensure_weights(py: Path, dest: Path) -> None:
    ckpt = dest / "checkpoints"
    ckpt.mkdir(exist_ok=True)
    (ckpt / "whisper").mkdir(exist_ok=True)
    status("Fetching ByteDance/LatentSync-1.6 weights")
    run(
        [
            str(py),
            "-c",
            (
                "from huggingface_hub import hf_hub_download\n"
                f"hf_hub_download('{UNET_REPO}', 'latentsync_unet.pt', local_dir=r'{ckpt}')\n"
                f"hf_hub_download('{UNET_REPO}', 'whisper/tiny.pt', local_dir=r'{ckpt}')\n"
            ),
        ]
    )
    status("Fetching Stable Diffusion VAE used by LatentSync")
    run(
        [
            str(py),
            "-c",
            "from diffusers import AutoencoderKL; AutoencoderKL.from_pretrained('stabilityai/sd-vae-ft-mse')",
        ]
    )


def ensure(root: Path) -> dict:
    apply_cache_env(root)
    root.mkdir(parents=True, exist_ok=True)
    ffmpeg = ensure_ffmpeg(root)
    dest = ensure_repo(root)
    patch_face_detector(dest)
    py = ensure_venv(root)
    ensure_python_deps(py, dest)
    ensure_weights(py, dest)
    state = {
        "ok": True,
        "engine": "latentsync-1.6",
        "root": str(root),
        "python": str(py),
        "ffmpeg": str(ffmpeg),
        "ready": checkpoints_ready(root),
    }
    (root / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def probe(root: Path, comfy_url: str) -> dict:
    apply_cache_env(root)
    comfy = probe_comfy(comfy_url)
    py = venv_python(root)
    return {
        "ok": checkpoints_ready(root) and py.is_file(),
        "engine": "latentsync-1.6",
        "root": str(root),
        "python": str(py) if py.is_file() else "",
        "ffmpeg": str(ffmpeg_exe(root) or ""),
        "ready": checkpoints_ready(root),
        "comfy": comfy,
        "pinokio": "control plane not used",
    }


def prepend_ffmpeg(root: Path) -> None:
    exe = ffmpeg_exe(root)
    if exe:
        os.environ["PATH"] = str(exe.parent) + os.pathsep + os.environ.get("PATH", "")
        try:
            import imageio_ffmpeg

            os.environ["PATH"] = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent) + os.pathsep + os.environ["PATH"]
        except Exception:
            pass


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def media_duration(root: Path, media: Path) -> float:
    ffmpeg = ffmpeg_exe(root)
    if not ffmpeg:
        return 6.0
    probe = ffmpeg.with_name("ffprobe.exe")
    if not probe.is_file():
        return 6.0
    proc = subprocess.run(
        [
            str(probe),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return max(2.0, float((proc.stdout or "").strip()))
    except ValueError:
        return 6.0


def prepare_visual(root: Path, source: Path, wav: Path, work: Path) -> Path:
    if source.suffix.lower() not in IMAGE_EXTS:
        return source
    ffmpeg = ffmpeg_exe(root)
    if not ffmpeg:
        raise RuntimeError("ffmpeg missing")
    dest = work / "from_photo.mp4"
    duration = media_duration(root, wav) + 0.35
    status("Making a talking clip from your photo")
    run(
        [
            str(ffmpeg),
            "-y",
            "-nostdin",
            "-loop",
            "1",
            "-framerate",
            "25",
            "-i",
            str(source),
            "-i",
            str(wav),
            "-vf",
            "scale=720:720:force_original_aspect_ratio=decrease,pad=720:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-c:v",
            "libx264",
            "-tune",
            "stillimage",
            "-c:a",
            "aac",
            "-shortest",
            "-t",
            f"{duration:.3f}",
            str(dest),
        ]
    )
    if not dest.is_file() or dest.stat().st_size < 1024:
        raise RuntimeError("Could not turn the photo into a clip. Pick a clear face-on picture.")
    return dest


def convert_audio(root: Path, audio: Path, wav: Path) -> None:
    ffmpeg = ffmpeg_exe(root)
    if not ffmpeg:
        raise RuntimeError("ffmpeg missing")
    run(
        [
            str(ffmpeg),
            "-y",
            "-nostdin",
            "-i",
            str(audio),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(wav),
        ]
    )


def run_lipsync(root: Path, sitting: Path, audio: Path, out: Path) -> dict:
    apply_cache_env(root)
    if not checkpoints_ready(root):
        ensure(root)
    py = venv_python(root)
    dest = repo_dir(root)
    if not py.is_file() or not (dest / "scripts" / "inference.py").is_file():
        raise RuntimeError("LatentSync engine is not installed")
    prepend_ffmpeg(root)
    work = root / "work"
    work.mkdir(exist_ok=True)
    wav = work / "speech.wav"
    convert_audio(root, audio, wav)
    visual = prepare_visual(root, sitting, wav, work)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(py),
        "-m",
        "scripts.inference",
        "--unet_config_path",
        "configs/unet/stage2_512.yaml",
        "--inference_ckpt_path",
        "checkpoints/latentsync_unet.pt",
        "--inference_steps",
        "20",
        "--guidance_scale",
        "1.5",
        "--enable_deepcache",
        "--video_path",
        str(visual),
        "--audio_path",
        str(wav),
        "--video_out_path",
        str(out),
        "--temp_dir",
        str(work / "temp"),
    ]
    env = os.environ.copy()
    env["PATH"] = str((ffmpeg_exe(root) or Path(".")).parent) + os.pathsep + env.get("PATH", "")
    status("Running LatentSync 1.6 on the likeness")
    proc = subprocess.run(
        cmd,
        cwd=dest,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size < 1024:
        raise RuntimeError(humanize_engine_error((proc.stderr or "") + "\n" + (proc.stdout or "")))
    return {"ok": True, "engine": "latentsync-1.6", "path": str(out)}


def humanize_engine_error(text: str) -> str:
    lower = (text or "").lower()
    if "face not detected" in lower:
        return (
            "No usable face in that picture. File a face-on camera original of you alone — "
            "head and shoulders filling the frame, both eyes toward the lens. "
            "Group shots, chat thumbnails, and full-body landscapes fail."
        )
    if "out of memory" in lower or ("cuda" in lower and "memory" in lower):
        return "The GPU ran out of memory while making the likeness."
    tail = (text or "").strip()
    if len(tail) > 500:
        tail = tail[-500:]
    return tail or "LatentSync finished without a video. The photo or sitting must show a clear face."


def read_frame(source: Path):
    import cv2

    if source.suffix.lower() in IMAGE_EXTS:
        frame = cv2.imread(str(source))
        return frame
    cap = cv2.VideoCapture(str(source))
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def check_visual(root: Path, source: Path) -> dict:
    """Fast preflight: pixel size plus InsightFace count. Does not run LatentSync."""
    apply_cache_env(root)
    source = Path(source)
    if not source.is_file():
        return {"ok": False, "error": "That file is gone.", "faces": 0, "width": 0, "height": 0}
    width = height = 0
    try:
        from PIL import Image

        with Image.open(source) as im:
            width, height = im.size
    except Exception:
        pass
    issues: list[str] = []
    short = min(width, height) if width and height else 0
    if short and short < 480:
        issues.append(
            f"Too small ({width}×{height}). Use a camera original at least 720px on the short side — not a chat thumbnail or a crop from a group."
        )
    faces = 0
    largest = 0
    dest = repo_dir(root)
    cwd = os.getcwd()
    try:
        import sys as _sys

        if str(dest) not in _sys.path:
            _sys.path.insert(0, str(dest))
        os.chdir(dest)
        from insightface.app import FaceAnalysis

        frame = read_frame(source)
        if frame is None:
            issues.append("Could not read that file as a picture or video frame.")
        else:
            if width == 0 or height == 0:
                height, width = frame.shape[:2]
                short = min(width, height)
            app = FaceAnalysis(
                allowed_modules=["detection", "landmark_2d_106"],
                root="checkpoints/auxiliary",
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            app.prepare(ctx_id=0, det_size=(512, 512))
            detected = app.get(frame) or []
            scored = [face for face in detected if float(getattr(face, "det_score", 0)) >= 0.35]
            faces = len(scored)
            face_h = 0
            for face in scored:
                bbox = face.bbox.astype(int).tolist()
                area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                if area > largest:
                    largest = area
                    face_h = bbox[3] - bbox[1]
            if faces == 0:
                issues.append(
                    "No face found. Face the camera, both eyes visible, even light in front of you — not behind — and fill the frame with your head and shoulders."
                )
            elif faces > 1:
                issues.append(
                    f"{faces} faces in this picture. The engine locks onto the largest and can pick the wrong person. Use a photo of you alone."
                )
            elif face_h < 80 or (height and face_h < int(height * 0.22)):
                issues.append(
                    "The face is too small in the frame. Move closer — head and shoulders filling most of the picture, not a full-body landscape or a group crop."
                )
    except Exception as exc:
        if not issues:
            issues.append(f"Face finder could not run ({exc}). Size still has to be a camera original, not a thumbnail.")
    finally:
        os.chdir(cwd)
    error = issues[0] if issues else None
    return {
        "ok": not issues,
        "error": error,
        "width": width,
        "height": height,
        "faces": faces,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="")
    parser.add_argument("--comfy", default=os.environ.get("HEIRLOOM_COMFY_URL", "http://127.0.0.1:8188"))
    parser.add_argument("--ensure", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--check", default="")
    parser.add_argument("--sitting", default="")
    parser.add_argument("--audio", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    root = engine_root(args.root or None)
    try:
        if args.probe:
            emit(probe(root, args.comfy))
            return 0
        if args.ensure:
            emit(ensure(root))
            return 0
        if args.check:
            result = check_visual(root, Path(args.check))
            emit(result)
            return 0 if result.get("ok") else 1
        if args.sitting and args.audio and args.out:
            emit(run_lipsync(root, Path(args.sitting), Path(args.audio), Path(args.out)))
            return 0
        emit({"ok": False, "error": "pass --probe, --ensure, --check, or --sitting/--audio/--out"})
        return 2
    except Exception as exc:
        emit({"ok": False, "error": str(exc), "root": str(root)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
