"""YuNet + SFace through OpenCV. Imported only when the camera service runs.

The API process does not need OpenCV. Unit tests do not import cv2.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from presence_models import (
    DEFAULT_VRAM_BUDGET_MIB,
    DETECTOR,
    RECOGNIZER,
    select_target,
)


class PresenceVisionError(RuntimeError):
    pass


def free_vram_mib() -> int | None:
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    line = output.decode("utf-8", errors="replace").splitlines()
    if not line:
        return None
    token = line[0].strip().split()[0] if line[0].strip() else ""
    if not token.isdigit():
        return None
    return int(token)


def cuda_built(cv2_module: object) -> bool:
    dnn = getattr(cv2_module, "dnn", None)
    return bool(dnn is not None and hasattr(dnn, "DNN_BACKEND_CUDA") and hasattr(dnn, "DNN_TARGET_CUDA"))


def choose_backend(cv2_module: object | None = None, free_mib: int | None = None, budget_mib: int | None = None) -> str:
    if cv2_module is None:
        return select_target(free_mib, cuda_available=False, budget_mib=budget_mib or DEFAULT_VRAM_BUDGET_MIB)
    budget = DEFAULT_VRAM_BUDGET_MIB if budget_mib is None else budget_mib
    return select_target(free_mib, cuda_available=cuda_built(cv2_module), budget_mib=budget)


def _import_cv2():
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise PresenceVisionError("python3-opencv is not installed") from exc
    if not hasattr(cv2, "FaceDetectorYN") or not hasattr(cv2, "FaceRecognizerSF"):
        raise PresenceVisionError("This OpenCV build has no YuNet or SFace API")
    return cv2


def load_models(model_dir: Path, *, backend: str):
    cv2 = _import_cv2()
    yunet = model_dir / DETECTOR.filename
    sface = model_dir / RECOGNIZER.filename
    if not yunet.is_file() or not sface.is_file():
        raise PresenceVisionError("YuNet or SFace weights are not on disk")
    cuda = backend == "cuda" and cuda_built(cv2)
    backend_id = cv2.dnn.DNN_BACKEND_CUDA if cuda else cv2.dnn.DNN_BACKEND_OPENCV
    target_id = cv2.dnn.DNN_TARGET_CUDA if cuda else cv2.dnn.DNN_TARGET_CPU
    try:
        detector = cv2.FaceDetectorYN.create(str(yunet), "", (320, 320), 0.9, 0.3, 5000, backend_id, target_id)
        recognizer = cv2.FaceRecognizerSF.create(str(sface), "", backend_id, target_id)
        used = "cuda" if cuda else "cpu"
    except Exception:
        detector = cv2.FaceDetectorYN.create(str(yunet), "", (320, 320), 0.9, 0.3, 5000)
        recognizer = cv2.FaceRecognizerSF.create(str(sface), "")
        used = "cpu"
    return cv2, detector, recognizer, used


def faces_from_frame(cv2, detector, recognizer, frame) -> list[dict]:
    """Return embeddings and a small JPEG crop. The full frame is not returned."""
    if frame is None:
        return []
    height, width = frame.shape[:2]
    if width < 16 or height < 16:
        return []
    detector.setInputSize((width, height))
    found = detector.detect(frame)
    rows = found[1] if isinstance(found, tuple) else found
    if rows is None or len(rows) == 0:
        return []
    results = []
    for row in rows:
        aligned = recognizer.alignCrop(frame, row)
        feature = recognizer.feature(aligned)
        flat = feature.reshape(-1)
        embedding = [float(value) for value in flat]
        x, y, w, h = (int(row[0]), int(row[1]), int(row[2]), int(row[3]))
        x = max(0, x)
        y = max(0, y)
        crop = frame[y:y + max(1, h), x:x + max(1, w)]
        if crop.size == 0:
            thumb = b""
        else:
            thumb_frame = cv2.resize(crop, (96, 96))
            ok, encoded = cv2.imencode(".jpg", thumb_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            thumb = encoded.tobytes() if ok else b""
        results.append({"embedding": embedding, "thumb": thumb, "area": float(w * h)})
    results.sort(key=lambda item: item["area"], reverse=True)
    return results


def largest_face(faces: list[dict]) -> dict | None:
    if not faces:
        return None
    return faces[0]


def model_label() -> str:
    return f"{DETECTOR.filename} + {RECOGNIZER.filename}"


def prepare_models(model_dir: Path, budget_mib: int = DEFAULT_VRAM_BUDGET_MIB):
    """Load YuNet and SFace on CUDA only when free VRAM covers the budget."""
    cv2 = _import_cv2()
    backend = choose_backend(cv2, free_vram_mib(), budget_mib)
    return load_models(model_dir, backend=backend)
