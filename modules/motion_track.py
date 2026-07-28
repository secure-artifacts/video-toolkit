"""Motion tracking helpers: OpenCV path follow + tracked region blur for export."""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path


def _hidden_kwargs():
    try:
        from .settings_page import hidden_kwargs
        return hidden_kwargs()
    except Exception:
        return {}


def _create_tracker():
    """Pick best available OpenCV tracker.

    Stock opencv-python (no contrib) often has only MIL / Nano / Vit / DaSiamRPN.
    CSRT/KCF need opencv-contrib. Prefer light trackers that work offline without models.
    """
    import cv2

    creators = []
    # Prefer classic online trackers (no external model files)
    for name in (
        "TrackerCSRT_create",
        "TrackerKCF_create",
        "TrackerMIL_create",
        "TrackerMOSSE_create",
        "TrackerMedianFlow_create",
    ):
        if hasattr(cv2, name):
            creators.append(getattr(cv2, name))
        legacy = getattr(cv2, "legacy", None)
        if legacy is not None and hasattr(legacy, name):
            creators.append(getattr(legacy, name))
    for create in creators:
        try:
            tracker = create()
            if tracker is not None:
                return tracker
        except Exception:
            continue
    return None


class _TemplateTracker:
    """Fallback when OpenCV has no classic Tracker_*: match a template each frame."""

    def __init__(self):
        self._template = None
        self._w = 0
        self._h = 0
        self._last = None

    def init(self, frame, roi):
        import cv2
        import numpy as np

        x, y, w, h = [int(v) for v in roi]
        if w < 8 or h < 8:
            return False
        fh, fw = frame.shape[:2]
        x = max(0, min(fw - 2, x))
        y = max(0, min(fh - 2, y))
        w = max(8, min(fw - x, w))
        h = max(8, min(fh - y, h))
        patch = frame[y:y + h, x:x + w]
        if patch.size == 0:
            return False
        self._template = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) if len(patch.shape) == 3 else patch.copy()
        self._w, self._h = w, h
        self._last = (float(x), float(y), float(w), float(h))
        return True

    def update(self, frame):
        import cv2
        import numpy as np

        if self._template is None or self._last is None:
            return False, None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        fh, fw = gray.shape[:2]
        lx, ly, lw, lh = self._last
        # Search near last position (±40% of box, at least 40px)
        margin_x = max(40, int(lw * 0.45))
        margin_y = max(40, int(lh * 0.45))
        x0 = max(0, int(lx) - margin_x)
        y0 = max(0, int(ly) - margin_y)
        x1 = min(fw, int(lx + lw) + margin_x)
        y1 = min(fh, int(ly + lh) + margin_y)
        region = gray[y0:y1, x0:x1]
        th, tw = self._template.shape[:2]
        if region.shape[0] < th or region.shape[1] < tw:
            return False, self._last
        res = cv2.matchTemplate(region, self._template, cv2.TM_CCOEFF_NORMED)
        _min_v, max_v, _min_l, max_loc = cv2.minMaxLoc(res)
        if max_v < 0.35:
            return False, self._last
        nx = float(x0 + max_loc[0])
        ny = float(y0 + max_loc[1])
        self._last = (nx, ny, float(self._w), float(self._h))
        # Refresh template slowly to follow appearance change
        if max_v > 0.55:
            patch = gray[int(ny):int(ny) + th, int(nx):int(nx) + tw]
            if patch.shape[:2] == (th, tw):
                self._template = cv2.addWeighted(self._template, 0.85, patch, 0.15, 0)
        return True, self._last


def track_region(
    video_path,
    x_pct: float,
    y_pct: float,
    w_pct: float,
    h_pct: float,
    start_ms: int = 0,
    duration_ms: int = 0,
    max_points: int = 240,
    sample_every: int = 2,
    progress_cb=None,
) -> list[dict]:
    """Track a rectangle through the video.

    Coordinates are percentages of frame (0–100). Returns list of
    {t_ms, x, y, w, h} with x/y/w/h also as 0–100 percentages.
    """
    import cv2

    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到视频：{path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{path.name}")

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if frame_w < 8 or frame_h < 8:
            raise RuntimeError("视频分辨率无效。")

        start_ms = max(0, int(start_ms or 0))
        if duration_ms and duration_ms > 0:
            end_ms = start_ms + int(duration_ms)
        else:
            end_ms = int(round((total_frames / fps) * 1000)) if total_frames > 0 else start_ms + 30_000

        start_frame = int(round(start_ms / 1000.0 * fps))
        end_frame = max(start_frame + 1, int(round(end_ms / 1000.0 * fps)))
        if total_frames > 0:
            end_frame = min(end_frame, total_frames - 1)

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError("无法读取起始帧，请调整播放头后再试。")

        x = max(0.0, min(99.0, float(x_pct)))
        y = max(0.0, min(99.0, float(y_pct)))
        w = max(1.0, min(100.0 - x, float(w_pct)))
        h = max(1.0, min(100.0 - y, float(h_pct)))
        px = int(round(x / 100.0 * frame_w))
        py = int(round(y / 100.0 * frame_h))
        pw = max(8, int(round(w / 100.0 * frame_w)))
        ph = max(8, int(round(h / 100.0 * frame_h)))
        if px + pw > frame_w:
            pw = frame_w - px
        if py + ph > frame_h:
            ph = frame_h - py
        if pw < 8 or ph < 8:
            raise RuntimeError("追踪框太小，请放大区域。")

        tracker = _create_tracker()
        if tracker is None:
            tracker = _TemplateTracker()
        if not tracker.init(frame, (px, py, pw, ph)):
            # Last resort: template matcher
            tracker = _TemplateTracker()
            if not tracker.init(frame, (px, py, pw, ph)):
                raise RuntimeError("跟踪器初始化失败，请换一个更清晰、对比更强的区域。")

        points = [{
            "t_ms": start_ms,
            "x": round(px / frame_w * 100, 3),
            "y": round(py / frame_h * 100, 3),
            "w": round(pw / frame_w * 100, 3),
            "h": round(ph / frame_h * 100, 3),
        }]
        frame_i = start_frame
        sample_every = max(1, int(sample_every or 2))
        lost = 0
        while frame_i < end_frame:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            frame_i += 1
            if (frame_i - start_frame) % sample_every != 0:
                continue
            ok, box = tracker.update(frame)
            t_ms = int(round(frame_i / fps * 1000))
            if not ok or box is None:
                lost += 1
                if lost > 12:
                    break
                continue
            lost = 0
            bx, by, bw, bh = [float(v) for v in box]
            bx = max(0.0, min(frame_w - 2.0, bx))
            by = max(0.0, min(frame_h - 2.0, by))
            bw = max(4.0, min(frame_w - bx, bw))
            bh = max(4.0, min(frame_h - by, bh))
            points.append({
                "t_ms": t_ms,
                "x": round(bx / frame_w * 100, 3),
                "y": round(by / frame_h * 100, 3),
                "w": round(bw / frame_w * 100, 3),
                "h": round(bh / frame_h * 100, 3),
            })
            if progress_cb and len(points) % 8 == 0:
                try:
                    progress_cb(frame_i, end_frame, len(points))
                except Exception:
                    pass
            if len(points) >= max_points:
                break
        if len(points) < 2:
            raise RuntimeError("追踪点过少，请换高对比区域或缩短时长。")
        return points
    finally:
        cap.release()


def new_track_record(
    points: list[dict],
    mode: str = "blur",
    blur: int = 18,
    label: str = "",
    start_ms: int = 0,
) -> dict:
    return {
        "id": uuid.uuid4().hex[:10],
        "mode": "blur" if mode == "blur" else "label",
        "blur": max(3, min(48, int(blur or 18))),
        "label": str(label or "").strip(),
        "start_ms": int(start_ms or 0),
        "points": list(points or []),
    }


def _interp_box(points: list[dict], t_ms: int):
    if not points:
        return None
    if t_ms <= int(points[0]["t_ms"]):
        return points[0]
    if t_ms >= int(points[-1]["t_ms"]):
        return points[-1]
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        ta, tb = int(a["t_ms"]), int(b["t_ms"])
        if ta <= t_ms <= tb:
            if tb == ta:
                return a
            u = (t_ms - ta) / (tb - ta)
            return {
                "t_ms": t_ms,
                "x": a["x"] + (b["x"] - a["x"]) * u,
                "y": a["y"] + (b["y"] - a["y"]) * u,
                "w": a["w"] + (b["w"] - a["w"]) * u,
                "h": a["h"] + (b["h"] - a["h"]) * u,
            }
    return points[-1]


def apply_tracks_to_video(
    ffmpeg: str,
    video_path,
    tracks: list[dict],
    cache_dir,
    progress_cb=None,
) -> Path:
    """Render tracked blur (and optional label) onto a new mp4; return path.

    If no blur tracks, returns original path unchanged.
    """
    import cv2
    import numpy as np

    video_path = Path(video_path)
    blur_tracks = [
        t for t in (tracks or [])
        if isinstance(t, dict) and t.get("mode") == "blur" and t.get("points")
    ]
    if not blur_tracks:
        return video_path

    cache = Path(cache_dir) / ".motion_track_cache"
    cache.mkdir(parents=True, exist_ok=True)
    fingerprint = abs(hash(json.dumps(
        [{"id": t.get("id"), "blur": t.get("blur"), "n": len(t.get("points") or []),
          "p0": (t.get("points") or [None])[0], "p1": (t.get("points") or [None])[-1]}
         for t in blur_tracks],
        sort_keys=True, ensure_ascii=False,
    )))
    out = cache / f"tracked_{video_path.stem}_{fingerprint:x}.mp4"
    if out.is_file() and out.stat().st_size > 1024:
        return out

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频做追踪模糊：{video_path.name}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0) or 30.0
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    tmp_raw = out.with_suffix(".raw.avi")
    writer = cv2.VideoWriter(
        str(tmp_raw),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        (frame_w, frame_h),
    )
    if not writer.isOpened():
        cap.release()
        raise RuntimeError("无法创建追踪模糊中间文件。")

    try:
        frame_i = 0
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            t_ms = int(round(frame_i / fps * 1000))
            for track in blur_tracks:
                box = _interp_box(track.get("points") or [], t_ms)
                if not box:
                    continue
                x0 = int(round(float(box["x"]) / 100.0 * frame_w))
                y0 = int(round(float(box["y"]) / 100.0 * frame_h))
                ww = max(4, int(round(float(box["w"]) / 100.0 * frame_w)))
                hh = max(4, int(round(float(box["h"]) / 100.0 * frame_h)))
                x1 = min(frame_w, x0 + ww)
                y1 = min(frame_h, y0 + hh)
                x0 = max(0, x0)
                y0 = max(0, y0)
                if x1 - x0 < 4 or y1 - y0 < 4:
                    continue
                strength = max(3, min(48, int(track.get("blur") or 18)))
                # kernel odd
                k = strength * 2 + 1
                if k % 2 == 0:
                    k += 1
                roi = frame[y0:y1, x0:x1]
                if roi.size == 0:
                    continue
                blurred = cv2.GaussianBlur(roi, (k, k), 0)
                frame[y0:y1, x0:x1] = blurred
                label = str(track.get("label") or "").strip()
                if label:
                    cv2.putText(
                        frame, label, (x0, max(16, y0 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA,
                    )
            writer.write(frame)
            frame_i += 1
            if progress_cb and total and frame_i % 20 == 0:
                try:
                    progress_cb(frame_i, total)
                except Exception:
                    pass
    finally:
        writer.release()
        cap.release()

    # Remux with original audio via ffmpeg
    cmd = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(tmp_raw),
        "-i", str(video_path),
        "-map", "0:v:0", "-map", "1:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "copy",
        "-shortest", "-movflags", "+faststart",
        str(out),
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **_hidden_kwargs())
        if res.returncode != 0 or not out.is_file() or out.stat().st_size < 1024:
            # fall back: video only
            cmd2 = [
                str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(tmp_raw),
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-movflags", "+faststart", str(out),
            ]
            subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **_hidden_kwargs())
    finally:
        try:
            tmp_raw.unlink(missing_ok=True)
        except Exception:
            pass
    if not out.is_file() or out.stat().st_size < 1024:
        raise RuntimeError("追踪模糊编码失败。")
    return out


def tracks_fingerprint(tracks: list[dict]) -> str:
    try:
        payload = json.dumps(tracks or [], ensure_ascii=False, sort_keys=True)
    except Exception:
        payload = str(tracks)
    return str(abs(hash(payload)))
