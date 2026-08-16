"""Local Pinokio / ComfyUI avatar twin jobs.

The cloud queues `avatar_still` / `avatar_talk` / `avatar_look`. This module
runs on the home PC: it copies the owner's photos into ~/Heirloom/avatar,
writes a body-sheet prompt, optionally hits local ComfyUI, and opens the
matching Pinokio app so the owner can go live (webcam look-at-you) or render
a talking clip.
"""
from __future__ import annotations

import io
import json
import os
import webbrowser
from pathlib import Path
from typing import Any, Optional

import requests

from . import config


def _api(path: str) -> str:
    return f"{config.BACKEND_URL.rstrip('/')}/api{path}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.DEVICE_TOKEN}"}


def workspace(job_id: str) -> Path:
    safe = "".join(ch for ch in (job_id or "latest") if ch.isalnum() or ch in "-_")[:40]
    return Path.home() / "Heirloom" / "avatar" / (safe or "latest")


def run_avatar_job(payload: dict) -> tuple[str, str]:
    kind = (payload.get("kind") or "").strip().lower()
    job_id = (payload.get("job_id") or "").strip()
    if kind not in ("still", "talk", "look"):
        return "error", f"unknown avatar kind {kind}"
    if not job_id:
        return "error", "missing job_id"

    folder = workspace(job_id)
    folder.mkdir(parents=True, exist_ok=True)

    prompt = (payload.get("prompt") or "").strip()
    text = (payload.get("text") or "").strip()
    (folder / "prompt.txt").write_text(prompt or text or "", encoding="utf-8")
    (folder / "job.json").write_text(
        json.dumps({k: v for k, v in payload.items() if k != "provider" and k != "tts"}, indent=2),
        encoding="utf-8",
    )
    if text:
        (folder / "script.txt").write_text(text, encoding="utf-8")

    images = payload.get("images") or []
    saved = _download_images(folder, images)
    if not saved and kind in ("look", "talk", "still"):
        return _fail(job_id, "no reference photos reached this PC — upload a front photo in Avatar Studio first")

    wav = _maybe_tts(folder, payload.get("tts") or {}, text)

    pinokio_url = (payload.get("pinokio_url") or "").strip()
    prov = payload.get("provider") or {}
    media = _maybe_comfy(folder, saved, prompt or text, prov, wav=wav, timeout_sec=720 if kind == "talk" else 420)

    if media:
        status, detail = _upload_result(job_id, media[0], media[1], media[2])
        if status == "ok" and pinokio_url and kind == "look":
            webbrowser.open(pinokio_url)
        return status, detail

    if pinokio_url:
        webbrowser.open(pinokio_url)
    _open_folder(folder)
    hint = {
        "look": "LivePortrait is opening. Load front.jpg as the source and turn on your webcam as the driving video.",
        "talk": "ComfyUI / EchoMimic is opening. Load the photos in this folder and script.txt (plus speech.wav if present).",
        "still": "ComfyUI is opening. Load the photos as InstantID / IPAdapter refs and paste prompt.txt.",
    }.get(kind, "Opened the Pinokio app.")
    msg = f"{hint} Folder: {folder}"
    _note_ok(job_id, msg)
    return "ok", msg


def _download_images(folder: Path, images: list) -> list[Path]:
    saved: list[Path] = []
    for i, item in enumerate(images or []):
        if not isinstance(item, dict):
            continue
        image_id = (item.get("image_id") or "").strip()
        angle = "".join(ch for ch in (item.get("angle") or f"img{i}") if ch.isalnum() or ch == "_")[:24]
        url = (item.get("url") or "").strip()
        data: Optional[bytes] = None
        ct = "image/jpeg"
        if image_id:
            try:
                r = requests.get(
                    _api(f"/avatar-studio/companion-file/{image_id}"),
                    headers=_headers(),
                    timeout=45,
                )
                if r.status_code == 200:
                    data = r.content
                    ct = r.headers.get("content-type") or ct
            except Exception:
                data = None
        if data is None and url:
            try:
                r = requests.get(url, timeout=45)
                if r.status_code == 200:
                    data = r.content
                    ct = r.headers.get("content-type") or ct
            except Exception:
                data = None
        if not data:
            continue
        ext = "jpg"
        if "png" in ct:
            ext = "png"
        elif "webp" in ct:
            ext = "webp"
        dest = folder / f"{angle or f'img{i}'}.{ext}"
        dest.write_bytes(data)
        saved.append(dest)
        if angle == "front" or (i == 0 and not (folder / "front.jpg").exists() and not (folder / "front.png").exists()):
            # LivePortrait looks for a simple name.
            alias = folder / f"front.{ext}"
            if alias != dest:
                alias.write_bytes(data)
    return saved


def _maybe_tts(folder: Path, tts: dict, text: str) -> Optional[Path]:
    if not text or not (tts.get("base_url") or "").strip() or not tts.get("enabled"):
        return None
    base = str(tts.get("base_url") or "").rstrip("/")
    headers = {}
    key = (tts.get("api_key") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body: dict[str, Any] = {
        "model": (tts.get("model") or "tts-1").strip() or "tts-1",
        "input": text[:2000],
        "voice": (tts.get("voice") or "alloy").strip() or "alloy",
    }
    try:
        r = requests.post(base + "/audio/speech", headers=headers, json=body, timeout=120)
        r.raise_for_status()
        dest = folder / "speech.wav"
        dest.write_bytes(r.content)
        return dest
    except Exception:
        return None


def _maybe_comfy(
    folder: Path,
    saved: list[Path],
    prompt: str,
    prov: dict,
    *,
    wav: Optional[Path],
    timeout_sec: int,
) -> Optional[tuple[bytes, str, str]]:
    """Run a user-pasted Comfy workflow if one is configured. Otherwise skip."""
    ptype = (prov.get("provider_type") or "comfyui").lower()
    base = (prov.get("base_url") or "").rstrip("/")
    workflow = (prov.get("comfy_workflow") or "").strip()
    if ptype != "comfyui" or not base or not workflow or not saved:
        return None
    try:
        from .comfy_client import run_comfy_media
        image_bytes = saved[0].read_bytes()
        out, ct = run_comfy_media(
            base,
            (prov.get("api_key") or "").strip(),
            workflow,
            image_bytes,
            prompt,
            (prov.get("model") or "").strip(),
            timeout_sec=timeout_sec,
        )
        ext = "mp4" if "video" in (ct or "") else ("gif" if "gif" in (ct or "") else "png")
        name = f"result.{ext}"
        (folder / name).write_bytes(out)
        return out, ct, name
    except Exception as exc:  # noqa: BLE001
        (folder / "comfy_error.txt").write_text(str(exc), encoding="utf-8")
        return None


def _upload_result(job_id: str, data: bytes, content_type: str, filename: str) -> tuple[str, str]:
    files = {"file": (filename, io.BytesIO(data), content_type or "application/octet-stream")}
    try:
        r = requests.post(
            _api(f"/avatar-studio/jobs/{job_id}/result"),
            headers=_headers(),
            files=files,
            timeout=90,
        )
        if r.status_code == 200:
            return "ok", f"uploaded {filename}"
        return "error", f"result upload failed (HTTP {r.status_code})"
    except Exception as exc:  # noqa: BLE001
        return "error", f"result upload error: {exc}"


def _fail(job_id: str, reason: str) -> tuple[str, str]:
    try:
        requests.post(
            _api(f"/avatar-studio/jobs/{job_id}/fail"),
            headers=_headers(),
            json={"reason": reason[:400]},
            timeout=15,
        )
    except Exception:
        pass
    return "error", reason


def _note_ok(job_id: str, message: str) -> None:
    """Mark the job done even when we only prepared a folder + opened Pinokio."""
    try:
        requests.post(
            _api(f"/avatar-studio/jobs/{job_id}/note"),
            headers=_headers(),
            json={"message": message[:1500]},
            timeout=15,
        )
    except Exception:
        pass


def _open_folder(folder: Path) -> None:
    path = str(folder)
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception:
        pass
