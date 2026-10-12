"""Face models Presence is allowed to load.

YuNet (detector) is MIT. SFace (recognizer) is Apache-2.0. Both files are the
copies published in the OpenCV Zoo. InsightFace pretrained weights are
non-commercial research only and are not selected, downloaded, or named here
as a runtime model.

The 2023-03 YuNet file has a fixed input shape that OpenCV 4.x on Ubuntu 24.04
can run. The newer dynamic YuNet export targets OpenCV 5.
"""
from __future__ import annotations

from dataclasses import dataclass

YUNET_FILENAME = "face_detection_yunet_2023mar.onnx"
SFACE_FILENAME = "face_recognition_sface_2021dec.onnx"

YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
SFACE_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_recognition_sface/face_recognition_sface_2021dec.onnx"
)
YUNET_LICENSE_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/LICENSE"
)
SFACE_LICENSE_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/LICENSE"
)

# Weights are tens of megabytes. Ask for this much free VRAM before CUDA,
# and stay on CPU when Ollama is using the card.
DEFAULT_VRAM_BUDGET_MIB = 512
# OpenCV's SFace sample treats cosine similarity at or above this as the same person.
DEFAULT_THRESHOLD = 0.36
DEFAULT_FPS = 3.0
MIN_FPS = 2.0
MAX_FPS = 5.0


@dataclass(frozen=True)
class FaceModel:
    role: str
    filename: str
    url: str
    license: str
    license_url: str


DETECTOR = FaceModel(
    role="detector",
    filename=YUNET_FILENAME,
    url=YUNET_URL,
    license="MIT",
    license_url=YUNET_LICENSE_URL,
)
RECOGNIZER = FaceModel(
    role="recognizer",
    filename=SFACE_FILENAME,
    url=SFACE_URL,
    license="Apache-2.0",
    license_url=SFACE_LICENSE_URL,
)


def select_target(free_mib: int | None, *, cuda_available: bool, budget_mib: int = DEFAULT_VRAM_BUDGET_MIB) -> str:
    """CUDA only when the build has it and the card has the budget left.

    Unknown free memory stays on CPU so Presence does not guess and take
    Ollama's VRAM.
    """
    if not cuda_available:
        return "cpu"
    if free_mib is None:
        return "cpu"
    try:
        free = int(free_mib)
        budget = int(budget_mib)
    except (TypeError, ValueError):
        return "cpu"
    if free < budget or budget <= 0:
        return "cpu"
    return "cuda"


def clamp_fps(raw: float | int | str | None, default: float = DEFAULT_FPS) -> float:
    try:
        value = float(raw if raw is not None and raw != "" else default)
    except (TypeError, ValueError):
        value = default
    if value < MIN_FPS:
        return MIN_FPS
    if value > MAX_FPS:
        return MAX_FPS
    return value
