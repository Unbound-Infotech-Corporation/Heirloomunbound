"""ComfyUI HTTP client used by photo restore and local avatar jobs."""
from __future__ import annotations

import io
import json
import os
import time
from typing import Optional

import requests


def run_comfy_media(
    base_url: str,
    api_key: str,
    workflow_str: str,
    image_bytes: bytes,
    prompt: str,
    model: str,
    *,
    timeout_sec: int = 300,
    default_workflow: Optional[dict] = None,
) -> tuple[bytes, str]:
    """Upload an image, run a workflow, return the first image/gif/video."""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    root = (base_url or "").rstrip("/")
    if not root:
        raise RuntimeError("comfyui: no base_url")

    up = requests.post(
        root + "/upload/image",
        headers=headers,
        files={"image": ("input.png", io.BytesIO(image_bytes), "image/png")},
        data={"overwrite": "true"},
        timeout=60,
    )
    up.raise_for_status()
    uploaded = up.json().get("name") or "input.png"

    if (workflow_str or "").strip():
        workflow = json.loads(workflow_str)
    elif default_workflow:
        blob = json.dumps(default_workflow).replace("input.png", uploaded)
        workflow = json.loads(blob)
    else:
        raise RuntimeError("comfyui: no workflow")

    # Let a pasted graph see the uploaded filename + prompt if it uses tokens.
    workflow = _inject_placeholders(workflow, uploaded, prompt, model)

    client_id = f"heirloom-{os.getpid()}"
    submit = requests.post(
        root + "/prompt",
        headers=headers,
        json={"prompt": workflow, "client_id": client_id},
        timeout=60,
    )
    submit.raise_for_status()
    prompt_id = submit.json().get("prompt_id")
    if not prompt_id:
        raise RuntimeError("comfyui: no prompt_id returned")

    deadline = time.time() + max(30, int(timeout_sec))
    while time.time() < deadline:
        hist = requests.get(root + f"/history/{prompt_id}", headers=headers, timeout=20)
        if hist.status_code == 200:
            data = hist.json() or {}
            record = data.get(prompt_id)
            if record and record.get("outputs"):
                found = _first_media(record["outputs"], root, headers)
                if found:
                    return found
                raise RuntimeError("comfyui: workflow completed but produced no image or video")
        time.sleep(1.5)
    raise RuntimeError(f"comfyui: timed out waiting for output ({timeout_sec}s)")


def _inject_placeholders(workflow: dict, image_name: str, prompt: str, model: str) -> dict:
    """Replace well-known string tokens so a pasted graph can stay generic."""
    blob = json.dumps(workflow)
    blob = blob.replace("__HEIRLOOM_IMAGE__", image_name)
    blob = blob.replace("__HEIRLOOM_PROMPT__", prompt.replace('"', '\\"'))
    if model:
        blob = blob.replace("__HEIRLOOM_MODEL__", model)
    return json.loads(blob)


def _first_media(outputs: dict, root: str, headers: dict) -> Optional[tuple[bytes, str]]:
    buckets = ("images", "gifs", "videos", "audio")
    for _node_id, out in (outputs or {}).items():
        if not isinstance(out, dict):
            continue
        for bucket in buckets:
            for item in out.get(bucket) or []:
                fn = (item or {}).get("filename")
                if not fn:
                    continue
                sub = item.get("subfolder") or ""
                typ = item.get("type") or "output"
                r = requests.get(
                    root + "/view",
                    headers=headers,
                    params={"filename": fn, "subfolder": sub, "type": typ},
                    timeout=90,
                )
                r.raise_for_status()
                ct = r.headers.get("content-type") or _guess_ct(fn)
                return r.content, ct
    return None


def _guess_ct(filename: str) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".mp4"):
        return "video/mp4"
    if lower.endswith(".webm"):
        return "video/webm"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".wav"):
        return "audio/wav"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    return "image/png"
