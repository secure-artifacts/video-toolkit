from __future__ import annotations

import subprocess
from functools import lru_cache

from .settings_page import hidden_kwargs


ENCODER_LABELS = {
    "auto": "自动硬件加速（推荐）",
    "qsv": "Intel Quick Sync",
    "nvenc": "NVIDIA NVENC",
    "amf": "AMD AMF",
    "cpu": "CPU 兼容模式",
}


def encoder_key(label_or_key):
    value = str(label_or_key or "auto")
    for key, label in ENCODER_LABELS.items():
        if value == key or value == label:
            return key
    return "auto"


@lru_cache(maxsize=16)
def encoder_available(ffmpeg, key):
    """Test a real short encode, not just whether FFmpeg lists the encoder."""
    codec = {"qsv": "h264_qsv", "nvenc": "h264_nvenc", "amf": "h264_amf"}.get(key)
    if not codec:
        return key == "cpu"
    command = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
        "color=black:s=320x240:d=0.12", "-c:v", codec, "-frames:v", "1", "-f", "null", "NUL",
    ]
    try:
        result = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5, **hidden_kwargs(),
        )
        return result.returncode == 0
    except Exception:
        return False


def resolve_encoder(ffmpeg, requested="auto"):
    requested = encoder_key(requested)
    if requested == "cpu":
        return "cpu"
    if requested != "auto":
        return requested if encoder_available(str(ffmpeg), requested) else "cpu"
    # Intel is checked first on this app's common Windows laptops. A listed but
    # unusable NVIDIA/AMD encoder is rejected by the real encode probe above.
    for key in ("qsv", "nvenc", "amf"):
        if encoder_available(str(ffmpeg), key):
            return key
    return "cpu"


def encoder_args(key, cpu_preset="veryfast", preview=False):
    """Return H.264 args with similar visual quality across hardware backends."""
    if key == "qsv":
        return ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "25" if preview else "21",
                "-pix_fmt", "nv12"]
    if key == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p2" if preview else "p3", "-tune", "hq",
                "-rc", "vbr", "-cq", "25" if preview else "21", "-b:v", "0", "-pix_fmt", "yuv420p"]
    if key == "amf":
        return ["-c:v", "h264_amf", "-quality", "speed" if preview else "balanced",
                "-rc", "cqp", "-qp_i", "25" if preview else "21", "-qp_p", "25" if preview else "21",
                "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "ultrafast" if preview else cpu_preset,
            "-crf", "25" if preview else "20", "-pix_fmt", "yuv420p"]
