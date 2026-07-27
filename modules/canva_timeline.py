from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QProcess, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

# Timeline zoom: px per second. High end ≈ frame-level editing at 30fps
# (e.g. 900 px/s ≈ 30 px/frame). Low end is overview.
ZOOM_MIN_PPS = 12
ZOOM_MAX_PPS = 1800
ZOOM_DEFAULT_PPS = 42


_TIME_RE = re.compile(
    r"(?P<sh>\d{1,2}):(?P<sm>\d{2}):(?P<ss>\d{2})[,.](?P<sms>\d{3})"
    r"\s*-->\s*"
    r"(?P<eh>\d{1,2}):(?P<em>\d{2}):(?P<es>\d{2})[,.](?P<ems>\d{3})"
)


def _milliseconds(hours: str, minutes: str, seconds: str, millis: str) -> int:
    return (((int(hours) * 60 + int(minutes)) * 60) + int(seconds)) * 1000 + int(millis)


def _timestamp(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    seconds, millis = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


@dataclass
class CaptionClip:
    start: int
    end: int
    text: str


@dataclass
class MediaClip:
    start: int
    end: int
    source_start: int
    source_end: int
    name: str = ""

    def as_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "name": self.name,
        }


class TransitionPresetButton(QPushButton):
    """A normal preset button that can also be dragged onto the timeline."""

    MIME_TYPE = "application/x-video-transition"

    def __init__(self, text: str, transition_name: str, parent=None):
        super().__init__(text, parent)
        self.transition_name = str(transition_name)
        self._press_position = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(event)
        if (event.position().toPoint() - self._press_position).manhattanLength() < 8:
            return super().mouseMoveEvent(event)
        mime = QMimeData()
        mime.setData(self.MIME_TYPE, self.transition_name.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


def parse_srt(text: str) -> list[CaptionClip]:
    clips: list[CaptionClip] = []
    for block in re.split(r"\r?\n\s*\r?\n", str(text or "").strip()):
        lines = block.splitlines()
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        match = _TIME_RE.search(lines[timing_index])
        if not match:
            continue
        values = match.groupdict()
        start = _milliseconds(values["sh"], values["sm"], values["ss"], values["sms"])
        end = _milliseconds(values["eh"], values["em"], values["es"], values["ems"])
        copy = "\n".join(lines[timing_index + 1 :]).strip()
        if end > start:
            clips.append(CaptionClip(start, end, copy))
    return clips


def write_srt(clips: list[CaptionClip]) -> str:
    blocks = []
    for index, clip in enumerate(clips, 1):
        blocks.append(
            f"{index}\n{_timestamp(clip.start)} --> {_timestamp(clip.end)}\n{clip.text}".rstrip()
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


class TimelineCanvas(QWidget):
    srtChanged = Signal(str)
    seekRequested = Signal(int)
    timelineEdited = Signal(dict)
    # deltaY from wheel, x on canvas (for zoom-to-cursor)
    zoomWheel = Signal(int, int)

    LABEL_WIDTH = 112
    RULER_HEIGHT = 30
    TRACK_HEIGHT = 44

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration_ms = 10_000
        self.position_ms = 0
        self.pixels_per_second = ZOOM_DEFAULT_PPS
        self.clips: list[CaptionClip] = []
        self.video_waveform: list[float] = []
        self.bgm_waveform: list[float] = []
        self.tts_waveform: list[float] = []
        self.video_name = ""
        self.bgm_name = ""
        self.tts_name = ""
        self.original_audio_enabled = True
        self.transitions: list[dict] = []
        self.transition_names: list[str] = []
        self.transition_duration_ms = 500
        self.media_clips: dict[str, list[MediaClip]] = {
            "video": [],
            "original_audio": [],
            "bgm": [],
            "tts": [],
        }
        self.selected: tuple[str, int] | None = None
        self._drag: tuple[str, int, str, int, int, int, int] | None = None
        self._scrubbing = False
        self._project_key = ""
        self.setMinimumHeight(self.RULER_HEIGHT + self.TRACK_HEIGHT * 5 + 8)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)
        self._update_width()

    def _update_width(self):
        # Content-only width (track name column is a fixed rail outside the scroll area).
        content = math.ceil(self.duration_ms / 1000 * self.pixels_per_second)
        self.setMinimumWidth(max(640, content + 48))
        self.updateGeometry()
        self.update()
        rail = getattr(self, "label_rail", None)
        if rail is not None:
            rail.update()

    def set_zoom(self, value: int):
        self.pixels_per_second = max(ZOOM_MIN_PPS, min(ZOOM_MAX_PPS, int(value)))
        self._update_width()

    def wheelEvent(self, event: QWheelEvent):
        """Mouse wheel zooms the timeline (frame-level when zoomed in)."""
        delta = int(event.angleDelta().y())
        if delta == 0:
            # Some devices send pixelDelta only
            delta = int(event.pixelDelta().y())
        if delta == 0:
            super().wheelEvent(event)
            return
        self.zoomWheel.emit(delta, int(event.position().x()))
        event.accept()

    def set_project(
        self,
        duration_ms: int,
        video_name: str,
        srt: str,
        bgm_name: str = "",
        tts_name: str = "",
        original_audio_enabled: bool = True,
        edit_state: dict | None = None,
    ):
        self.duration_ms = max(1000, int(duration_ms or 0))
        self.video_name = str(video_name or "")
        self.bgm_name = str(bgm_name or "")
        self.tts_name = str(tts_name or "")
        self.original_audio_enabled = bool(original_audio_enabled)
        self.clips = parse_srt(srt)
        cue_end = max((clip.end for clip in self.clips), default=0)
        self.duration_ms = max(self.duration_ms, cue_end, 1000)
        project_key = str(video_name or "")
        if project_key != self._project_key:
            self._project_key = project_key
            base_name = Path(project_key).name if project_key else "视频"
            self.media_clips["video"] = [
                MediaClip(0, self.duration_ms, 0, self.duration_ms, base_name)
            ]
            self.media_clips["original_audio"] = [
                MediaClip(0, self.duration_ms, 0, self.duration_ms, "视频原声")
            ]
            self.media_clips["bgm"] = (
                [MediaClip(0, self.duration_ms, 0, self.duration_ms, Path(bgm_name).name)]
                if bgm_name
                else []
            )
            self.media_clips["tts"] = (
                [MediaClip(0, self.duration_ms, 0, self.duration_ms, Path(tts_name).name)]
                if tts_name
                else []
            )
            self.selected = None
            self.transitions = []
            tracks_state = (edit_state or {}).get("tracks", {})
            if tracks_state:
                for kind in self.media_clips:
                    restored = []
                    for item in tracks_state.get(kind, []):
                        try:
                            restored.append(
                                MediaClip(
                                    int(item["start"]), int(item["end"]),
                                    int(item["source_start"]), int(item["source_end"]),
                                    str(item.get("name", "")),
                                )
                            )
                        except (KeyError, TypeError, ValueError):
                            continue
                    self.media_clips[kind] = restored
            self.transitions = [
                {
                    "position": max(0, int(item.get("position", 0))),
                    "name": str(item.get("name", "")),
                    "duration_ms": max(100, int(item.get("duration_ms", 500))),
                }
                for item in (edit_state or {}).get("transitions", [])
                if item.get("name")
            ]
        else:
            saved_tracks=(edit_state or {}).get("tracks",{})
            if "bgm" not in saved_tracks:
                self._ensure_optional_track("bgm", bgm_name)
            if "tts" not in saved_tracks:
                self._ensure_optional_track("tts", tts_name)
        self.position_ms = min(self.position_ms, self.duration_ms)
        self._update_width()

    def set_transition_catalog(self, names: list[str], duration_ms: int = 500):
        self.transition_names = [str(name) for name in names if str(name).strip()]
        self.transition_duration_ms = max(100, int(duration_ms))

    def set_transition_duration(self, duration_ms: int):
        self.transition_duration_ms = max(100, int(duration_ms))

    def add_transition(self, name: str, position: int):
        name = str(name or "").strip()
        if not name:
            return
        position = max(80, min(int(position), self.duration_ms - 80))
        boundaries = sorted(
            {clip.end for clip in self.media_clips["video"][:-1]}
            | {clip.start for clip in self.media_clips["video"][1:]}
        )
        if boundaries:
            position = min(boundaries, key=lambda value: abs(value - position))
        else:
            for index, clip in enumerate(self.media_clips["video"]):
                if clip.start + 80 < position < clip.end - 80:
                    self._split_clip("video", index, position)
                    break
        marker = {
            "position": position,
            "name": name,
            "duration_ms": self.transition_duration_ms,
        }
        self.transitions = [
            item for item in self.transitions
            if abs(int(item.get("position", 0)) - position) > 40
        ]
        self.transitions.append(marker)
        self.transitions.sort(key=lambda item: int(item["position"]))
        self._emit_timeline_state()
        self.update()

    def _split_clip(self, kind: str, index: int, cut: int) -> bool:
        tracks = self.media_clips.get(kind, [])
        if not (0 <= index < len(tracks)):
            return False
        clip = tracks[index]
        if cut <= clip.start + 80 or cut >= clip.end - 80:
            return False
        source_cut = clip.source_start + (cut - clip.start)
        tracks[index:index + 1] = [
            MediaClip(clip.start, cut, clip.source_start, source_cut, clip.name),
            MediaClip(cut, clip.end, source_cut, clip.source_end, clip.name),
        ]
        if kind == "video":
            self._split_linked_original_audio(cut)
        return True

    def _ensure_optional_track(self, kind: str, name: str):
        if name and not self.media_clips[kind]:
            self.media_clips[kind] = [
                MediaClip(0, self.duration_ms, 0, self.duration_ms, Path(name).name)
            ]
        elif not name:
            self.media_clips[kind] = []

    def set_srt(self, srt: str):
        self.clips = parse_srt(srt)
        self.duration_ms = max(
            self.duration_ms, max((clip.end for clip in self.clips), default=0), 1000
        )
        self._update_width()

    def set_position(self, milliseconds: int):
        value = max(0, min(int(milliseconds), self.duration_ms))
        if value != self.position_ms:
            self.position_ms = value
            self.update()

    def set_waveform(self, kind: str, values: list[float]):
        if kind == "bgm":
            self.bgm_waveform = values
        elif kind == "tts":
            self.tts_waveform = values
        else:
            self.video_waveform = values
        self.update()

    def set_original_audio_enabled(self, enabled: bool):
        self.original_audio_enabled = bool(enabled)
        self._emit_timeline_state()
        self.update()
        rail = getattr(self, "label_rail", None)
        if rail is not None:
            rail.update()

    def _x(self, milliseconds: int) -> float:
        # Timeline content starts at x=0; track names live in the fixed left rail.
        return max(0.0, float(milliseconds)) / 1000.0 * self.pixels_per_second

    def _ms(self, x: float) -> int:
        return max(
            0,
            min(
                self.duration_ms,
                round(float(x) / max(1e-6, self.pixels_per_second) * 1000),
            ),
        )

    def track_label_rows(self):
        """Rows for the fixed left name rail: (title, detail)."""
        return (
            ("视频轨道", self.video_name),
            ("视频声音", "已静音" if not self.original_audio_enabled else "视频原声"),
            ("字幕时间块", ""),
            ("BGM 伴奏", self.bgm_name),
            ("文字配音", self.tts_name),
        )

    def _caption_y(self) -> int:
        return self.RULER_HEIGHT + self.TRACK_HEIGHT * 2

    @staticmethod
    def _track_index(kind: str) -> int:
        return {"video": 0, "original_audio": 1, "caption": 2, "bgm": 3, "tts": 4}[kind]

    def _track_y(self, kind: str) -> int:
        return self.RULER_HEIGHT + self._track_index(kind) * self.TRACK_HEIGHT

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111318"))

        # Track row backgrounds (full content width; names are on the fixed left rail).
        for index in range(5):
            y = self.RULER_HEIGHT + index * self.TRACK_HEIGHT
            painter.fillRect(
                0,
                y,
                self.width(),
                self.TRACK_HEIGHT - 1,
                QColor("#161922") if index % 2 == 0 else QColor("#13161d"),
            )
        # Ruler band
        painter.fillRect(0, 0, self.width(), self.RULER_HEIGHT, QColor("#14171e"))

        painter.setPen(QColor("#87909f"))
        painter.setFont(QFont("Consolas", 8))
        pps = self.pixels_per_second
        # Finer ticks when zoomed in so frame-level edits are readable.
        if pps >= 900:
            step_ms = 40          # ~1 frame @ 25fps
        elif pps >= 450:
            step_ms = 100         # 0.1s
        elif pps >= 200:
            step_ms = 200
        elif pps >= 100:
            step_ms = 500
        elif pps >= 52:
            step_ms = 1000
        elif pps >= 28:
            step_ms = 2000
        else:
            step_ms = 5000
        total_ms = max(step_ms, self.duration_ms)
        for ms in range(0, total_ms + step_ms, step_ms):
            x = self._x(ms)
            major = (ms % max(1000, step_ms * 5) == 0) or step_ms >= 1000
            painter.drawLine(QPointF(x, 14 if major else 20), QPointF(x, self.height()))
            if major or step_ms <= 100:
                seconds, millis = divmod(ms, 1000)
                minutes, seconds = divmod(seconds, 60)
                if step_ms < 1000:
                    label = f"{minutes}:{seconds:02d}.{millis:03d}"
                else:
                    label = f"{minutes}:{seconds:02d}"
                painter.drawText(int(x + 4), 17, label)

        self._draw_media_track(painter, "video", QColor("#334b73"), QColor("#73a7f5"), [])
        for transition in self.transitions:
            x = self._x(int(transition.get("position", 0)))
            y = self._track_y("video") + 22
            painter.setBrush(QColor("#f59e0b"))
            painter.setPen(QPen(QColor("#fff7d6"), 1))
            painter.drawPolygon(
                [
                    QPointF(x, y - 10), QPointF(x + 10, y),
                    QPointF(x, y + 10), QPointF(x - 10, y),
                ]
            )
            painter.setPen(QColor("#fef3c7"))
            painter.drawText(
                int(x + 12), int(y + 4),
                painter.fontMetrics().elidedText(
                    str(transition.get("name", "")),
                    Qt.TextElideMode.ElideRight, 90,
                ),
            )
        self._draw_media_track(
            painter,
            "original_audio",
            QColor("#30445f") if self.original_audio_enabled else QColor("#3f3237"),
            QColor("#7eb4e8") if self.original_audio_enabled else QColor("#8b5a66"),
            self.video_waveform if self.original_audio_enabled else [],
        )

        caption_y = self._caption_y() + 7
        for index, clip in enumerate(self.clips):
            left, right = self._x(clip.start), self._x(clip.end)
            width = max(4.0, right - left)
            painter.setPen(QPen(QColor("#b7a7ff"), 1))
            painter.setBrush(QColor("#765fd1"))
            painter.drawRoundedRect(int(left), caption_y, int(width), 40, 5, 5)
            painter.fillRect(int(left), caption_y, 4, 40, QColor("#e2dcff"))
            painter.fillRect(int(right - 4), caption_y, 4, 40, QColor("#e2dcff"))
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Microsoft YaHei UI", 8))
            text = " ".join(clip.text.splitlines())
            painter.drawText(
                int(left + 8),
                caption_y + 25,
                painter.fontMetrics().elidedText(
                    text, Qt.TextElideMode.ElideRight, max(0, int(width - 16))
                ),
            )

        self._draw_media_track(painter, "bgm", QColor("#275f50"), QColor("#6ee7b7"), self.bgm_waveform)
        self._draw_media_track(painter, "tts", QColor("#68461f"), QColor("#f6b95f"), self.tts_waveform)

        playhead_x = self._x(self.position_ms)
        painter.setPen(QPen(QColor("#f43f5e"), 2))
        painter.drawLine(QPointF(playhead_x, 0), QPointF(playhead_x, self.height()))
        painter.setBrush(QColor("#f43f5e"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(
            [QPointF(playhead_x - 6, 0), QPointF(playhead_x + 6, 0), QPointF(playhead_x, 9)]
        )

    def _draw_media_track(
        self,
        painter: QPainter,
        kind: str,
        fill: QColor,
        waveform_color: QColor,
        waveform: list[float],
    ):
        y = self._track_y(kind) + 4
        for index, clip in enumerate(self.media_clips.get(kind, [])):
            left, right = self._x(clip.start), self._x(clip.end)
            width = max(4, int(right - left))
            selected = self.selected == (kind, index)
            painter.setPen(QPen(QColor("#f8fafc") if selected else fill.lighter(135), 2 if selected else 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(int(left), y, width, 36, 5, 5)
            painter.setPen(QColor("#eef2ff"))
            painter.drawText(
                int(left + 8),
                y + 14,
                painter.fontMetrics().elidedText(
                    clip.name or kind, Qt.TextElideMode.ElideRight, max(0, width - 16)
                ),
            )
            if waveform:
                self._draw_waveform_segment(
                    painter, waveform, clip, y + 25, waveform_color
                )

    def _draw_waveform_segment(
        self, painter: QPainter, values: list[float], clip: MediaClip, center_y: int, color: QColor
    ):
        if not values:
            return
        left, right = self._x(clip.start), self._x(clip.end)
        path = QPainterPath(QPointF(left, center_y))
        sample_count = max(1, len(values) - 1)
        for index, value in enumerate(values):
            x = left + (right - left) * index / sample_count
            amplitude = min(1.0, abs(float(value))) * 9
            path.lineTo(x, center_y - amplitude)
            path.lineTo(x, center_y + amplitude)
        painter.setPen(QPen(color, 1))
        painter.drawPath(path)

    def _draw_waveform(self, painter: QPainter, values: list[float], center_y: int, color: QColor):
        if not values:
            painter.setPen(QPen(color.darker(150), 1))
            painter.drawLine(
                QPointF(self._x(0), center_y), QPointF(self._x(self.duration_ms), center_y)
            )
            return
        left, right = self._x(0), self._x(self.duration_ms)
        path = QPainterPath(QPointF(left, center_y))
        for index, value in enumerate(values):
            x = left + (right - left) * index / max(1, len(values) - 1)
            amplitude = min(1.0, abs(float(value))) * 16
            path.lineTo(x, center_y - amplitude)
            path.lineTo(x, center_y + amplitude)
        painter.setPen(QPen(color, 1))
        painter.drawPath(path)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        caption_top = self._caption_y()
        if caption_top <= y <= caption_top + self.TRACK_HEIGHT:
            for index, clip in enumerate(self.clips):
                left, right = self._x(clip.start), self._x(clip.end)
                if abs(x - left) <= 8:
                    self.selected = ("caption", index)
                    self._drag = ("caption", index, "start", clip.start, clip.end, 0, 0)
                    return
                if abs(x - right) <= 8:
                    self.selected = ("caption", index)
                    self._drag = ("caption", index, "end", clip.start, clip.end, 0, 0)
                    return
                if left <= x <= right:
                    self.selected = ("caption", index)
                    self.seekRequested.emit(clip.start)
                    self.update()
                    return
        for kind in ("video", "original_audio", "bgm", "tts"):
            top = self._track_y(kind)
            if not (top <= y <= top + self.TRACK_HEIGHT):
                continue
            for index, clip in enumerate(self.media_clips.get(kind, [])):
                left, right = self._x(clip.start), self._x(clip.end)
                if left <= x <= right:
                    edge = "start" if abs(x-left) <= 8 else "end" if abs(x-right) <= 8 else "move"
                    self.selected = (kind, index)
                    self._drag = (
                        kind, index, edge, clip.start, clip.end,
                        clip.source_start, clip.source_end,
                    )
                    self.seekRequested.emit(self._ms(x))
                    self.update()
                    return
        if x >= 0:
            self._scrubbing = True
            self.seekRequested.emit(self._ms(x))

    def mouseMoveEvent(self, event):
        if self._scrubbing:
            self.seekRequested.emit(self._ms(event.position().x()))
            return
        if not self._drag:
            return
        (
            kind, index, edge, original_start, original_end,
            original_source_start, original_source_end,
        ) = self._drag
        value = self._ms(event.position().x())
        if kind == "caption":
            if not (0 <= index < len(self.clips)):
                return
            clip = self.clips[index]
            if edge == "start":
                lower = self.clips[index - 1].end if index else 0
                clip.start = max(lower, min(value, clip.end - 80))
            else:
                upper = self.clips[index + 1].start if index + 1 < len(self.clips) else self.duration_ms
                clip.end = min(upper, max(value, clip.start + 80))
        else:
            tracks = self.media_clips.get(kind, [])
            if not (0 <= index < len(tracks)):
                return
            clip = tracks[index]
            if edge == "start":
                delta = max(-original_source_start, min(value - original_start, original_end - original_start - 80))
                clip.start = original_start + delta
                clip.source_start = original_source_start + delta
            elif edge == "end":
                delta = min(self.duration_ms-original_end, max(value-original_end, -(original_end-original_start-80)))
                clip.end = original_end + delta
                clip.source_end = original_source_end + delta
            else:
                length = original_end - original_start
                new_start = max(0, min(value - length // 2, self.duration_ms - length))
                clip.start, clip.end = new_start, new_start + length
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._scrubbing = False
        if self._drag:
            kind = self._drag[0]
            self._drag = None
            if kind == "caption":
                self.srtChanged.emit(write_srt(self.clips))
            else:
                self._emit_timeline_state()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(TransitionPresetButton.MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(TransitionPresetButton.MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(TransitionPresetButton.MIME_TYPE):
            return event.ignore()
        name = bytes(event.mimeData().data(TransitionPresetButton.MIME_TYPE)).decode(
            "utf-8", "replace"
        )
        self.add_transition(name, self._ms(event.position().x()))
        event.acceptProposedAction()

    def contextMenuEvent(self, event):
        if not self.transition_names:
            return super().contextMenuEvent(event)
        position = self._ms(event.pos().x())
        menu = QMenu(self)
        submenu = menu.addMenu("添加转场")
        for name in self.transition_names:
            action = submenu.addAction(name)
            action.triggered.connect(
                lambda checked=False, value=name, at=position: self.add_transition(value, at)
            )
        nearby = next(
            (
                item for item in self.transitions
                if abs(int(item.get("position", 0)) - position) <= 300
            ),
            None,
        )
        if nearby:
            menu.addSeparator()
            remove = menu.addAction("删除此处转场")
            remove.triggered.connect(lambda checked=False, item=nearby: self._remove_transition(item))
        menu.exec(event.globalPos())

    def _remove_transition(self, item: dict):
        if item in self.transitions:
            self.transitions.remove(item)
            self._emit_timeline_state()
            self.update()

    def split_at_playhead(self):
        selected = self.selected
        if not selected or selected[0] == "caption":
            selected = next(
                (("video", i) for i, clip in enumerate(self.media_clips["video"])
                 if clip.start < self.position_ms < clip.end),
                None,
            )
        if not selected:
            return
        kind, index = selected
        tracks = self.media_clips.get(kind, [])
        if not (0 <= index < len(tracks)):
            return
        cut = self.position_ms
        if not self._split_clip(kind, index, cut):
            return
        self.selected = (kind, index + 1)
        self._emit_timeline_state()
        self.update()

    def _split_linked_original_audio(self, cut: int):
        for index, clip in enumerate(self.media_clips["original_audio"]):
            if clip.start < cut < clip.end:
                source_cut = clip.source_start + (cut - clip.start)
                self.media_clips["original_audio"][index:index+1] = [
                    MediaClip(clip.start, cut, clip.source_start, source_cut, clip.name),
                    MediaClip(cut, clip.end, source_cut, clip.source_end, clip.name),
                ]
                return

    def delete_selected(self):
        if not self.selected:
            return
        kind, index = self.selected
        if kind == "caption":
            if 0 <= index < len(self.clips):
                self.clips.pop(index)
                self.srtChanged.emit(write_srt(self.clips))
        else:
            tracks = self.media_clips.get(kind, [])
            if 0 <= index < len(tracks):
                if kind == "video" and len(tracks) == 1:
                    return
                removed = tracks.pop(index)
                if kind == "video":
                    self._ripple_delete_range(removed.start, removed.end)
        self.selected = None
        self._emit_timeline_state()
        self.update()

    def _ripple_delete_range(self, start: int, end: int):
        delta = max(0, end - start)
        self.media_clips["video"] = self._delete_range_from_track(
            self.media_clips["video"], start, end, delta
        )
        for kind in ("original_audio", "bgm", "tts"):
            self.media_clips[kind] = self._delete_range_from_track(
                self.media_clips[kind], start, end, delta
            )
        kept: list[CaptionClip] = []
        for cue in self.clips:
            if cue.end <= start:
                kept.append(cue)
            elif cue.start >= end:
                kept.append(CaptionClip(cue.start-delta, cue.end-delta, cue.text))
            elif cue.start < start:
                kept.append(CaptionClip(cue.start, max(cue.start+80, start), cue.text))
        self.clips = kept
        adjusted_transitions = []
        for item in self.transitions:
            position = int(item.get("position", 0))
            if start <= position <= end:
                continue
            copy = dict(item)
            if position > end:
                copy["position"] = position - delta
            adjusted_transitions.append(copy)
        self.transitions = adjusted_transitions
        self.duration_ms = max(1000, self.duration_ms - delta)
        self.srtChanged.emit(write_srt(self.clips))
        self._update_width()

    @staticmethod
    def _delete_range_from_track(
        clips: list[MediaClip], start: int, end: int, delta: int
    ) -> list[MediaClip]:
        result = []
        for clip in clips:
            if clip.end <= start:
                result.append(clip)
            elif clip.start >= end:
                result.append(
                    MediaClip(
                        clip.start-delta, clip.end-delta,
                        clip.source_start, clip.source_end, clip.name,
                    )
                )
            else:
                if clip.start < start:
                    left_source_end = clip.source_start + (start - clip.start)
                    result.append(
                        MediaClip(
                            clip.start, start, clip.source_start, left_source_end, clip.name
                        )
                    )
                if clip.end > end:
                    right_source_start = clip.source_start + (end - clip.start)
                    result.append(
                        MediaClip(
                            start, clip.end-delta,
                            right_source_start, clip.source_end, clip.name,
                        )
                    )
        return result

    def _emit_timeline_state(self):
        self.timelineEdited.emit(
            {
                "duration_ms": self.duration_ms,
                "original_audio_enabled": self.original_audio_enabled,
                "transitions": [dict(item) for item in self.transitions],
                "tracks": {
                    kind: [clip.as_dict() for clip in clips]
                    for kind, clips in self.media_clips.items()
                },
            }
        )


class TrackLabelRail(QWidget):
    """Fixed left column for track names — does not scroll or zoom with the timeline."""

    def __init__(self, canvas: "TimelineCanvas", parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.setFixedWidth(TimelineCanvas.LABEL_WIDTH)
        self.setMinimumHeight(
            TimelineCanvas.RULER_HEIGHT + TimelineCanvas.TRACK_HEIGHT * 5 + 8
        )
        self.setStyleSheet("background:#181b22;border-right:1px solid #2a2f3a;")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#181b22"))
        painter.fillRect(0, 0, self.width(), TimelineCanvas.RULER_HEIGHT, QColor("#14171e"))
        painter.setPen(QColor("#64748b"))
        painter.setFont(QFont("Microsoft YaHei UI", 8))
        painter.drawText(8, 18, "轨道")

        rows = self.canvas.track_label_rows() if self.canvas else ()
        for index, (name, detail) in enumerate(rows):
            y = TimelineCanvas.RULER_HEIGHT + index * TimelineCanvas.TRACK_HEIGHT
            painter.fillRect(
                0,
                y,
                self.width(),
                TimelineCanvas.TRACK_HEIGHT - 1,
                QColor("#1a1e28") if index % 2 == 0 else QColor("#161a22"),
            )
            painter.setPen(QColor("#d8dbe5"))
            painter.setFont(QFont("Microsoft YaHei UI", 9, QFont.Weight.DemiBold))
            painter.drawText(10, y + 18, name)
            if detail:
                painter.setPen(QColor("#818898"))
                painter.setFont(QFont("Microsoft YaHei UI", 8))
                elided = painter.fontMetrics().elidedText(
                    Path(detail).name,
                    Qt.TextElideMode.ElideMiddle,
                    self.width() - 18,
                )
                painter.drawText(10, y + 34, elided)
        painter.setPen(QPen(QColor("#2a2f3a"), 1))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())


class CanvaTimelinePanel(QWidget):
    srtChanged = Signal(str)
    seekRequested = Signal(int)
    bgmVolumeChanged = Signal(int)
    timelineEdited = Signal(dict)
    originalAudioChanged = Signal(bool)

    def __init__(self, ffmpeg: str = "ffmpeg", parent=None):
        super().__init__(parent)
        self.ffmpeg = str(ffmpeg or "ffmpeg")
        self._processes: dict[str, QProcess] = {}
        self._paths: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(5)
        toolbar = QHBoxLayout()
        title = QLabel("多轨时间轴")
        title.setStyleSheet("font-weight:800;color:#f4f4f5;font-size:13px;")
        hint = QLabel("拖动字幕块左右边缘可校准时间 · 左侧轨道名固定 · 滚轮缩放内容")
        hint.setStyleSheet("color:#8b93a5;font-size:11px;")
        toolbar.addWidget(title)
        toolbar.addWidget(hint)
        cut = QPushButton("✂ 在播放头切片")
        cut.setToolTip("先选中轨道片段，再把播放头拖到切点")
        cut.clicked.connect(lambda: None)
        self.delete_button = QPushButton("删除选中片段")
        toolbar.addWidget(cut)
        toolbar.addWidget(self.delete_button)
        toolbar.addStretch()
        self.original_audio = QCheckBox("保留视频原声")
        self.original_audio.setChecked(True)
        toolbar.addWidget(self.original_audio)
        toolbar.addWidget(QLabel("BGM 音量"))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 200)
        self.volume.setValue(25)
        self.volume.setFixedWidth(110)
        self.volume.valueChanged.connect(self.bgmVolumeChanged)
        toolbar.addWidget(self.volume)
        toolbar.addWidget(QLabel("缩放"))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(ZOOM_MIN_PPS, ZOOM_MAX_PPS)
        self.zoom.setValue(ZOOM_DEFAULT_PPS)
        self.zoom.setSingleStep(8)
        self.zoom.setPageStep(80)
        self.zoom.setFixedWidth(130)
        self.zoom.setToolTip(
            "时间轴缩放（也可在轨道上滚轮缩放）\n"
            f"最小 {ZOOM_MIN_PPS}px/s · 最大 {ZOOM_MAX_PPS}px/s（可到帧级）\n"
            "左侧轨道名称固定不动"
        )
        toolbar.addWidget(self.zoom)
        self.zoom_value = QLabel(f"{ZOOM_DEFAULT_PPS}")
        self.zoom_value.setFixedWidth(36)
        self.zoom_value.setStyleSheet("color:#94a3b8;font-size:11px;")
        self.zoom_value.setToolTip("当前像素/秒")
        toolbar.addWidget(self.zoom_value)
        fit = QPushButton("适合窗口")
        fit.clicked.connect(self._fit)
        toolbar.addWidget(fit)
        root.addLayout(toolbar)

        # Fixed track-name rail + scrollable timeline content
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.canvas = TimelineCanvas()
        self.label_rail = TrackLabelRail(self.canvas)
        self.canvas.label_rail = self.label_rail
        body.addWidget(self.label_rail, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setStyleSheet("QScrollArea{border:none;background:#111318;}")
        self.scroll.setWidget(self.canvas)
        body.addWidget(self.scroll, 1)
        root.addLayout(body, 1)

        self.zoom.valueChanged.connect(self._on_zoom_slider)
        self.canvas.zoomWheel.connect(self._wheel_zoom)
        self.canvas.srtChanged.connect(self.srtChanged)
        self.canvas.seekRequested.connect(self.seekRequested)
        self.canvas.timelineEdited.connect(self.timelineEdited)
        cut.clicked.disconnect()
        cut.clicked.connect(self.canvas.split_at_playhead)
        self.delete_button.clicked.connect(self.canvas.delete_selected)
        self.original_audio.toggled.connect(self.canvas.set_original_audio_enabled)
        self.original_audio.toggled.connect(self.originalAudioChanged)
        self.setMinimumHeight(270)
        self.setStyleSheet(
            "CanvaTimelinePanel{background:#101218;border:1px solid #30343f;border-radius:8px;}"
        )
        # Let the scroll viewport also zoom with the wheel (when not over canvas chrome).
        self.scroll.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Wheel:
            # Zoom when wheel is used over empty viewport margins.
            delta = int(event.angleDelta().y()) or int(event.pixelDelta().y())
            if delta:
                # Map x into canvas coordinates
                canvas_pos = self.canvas.mapFrom(self.scroll.viewport(), event.position().toPoint())
                self._wheel_zoom(delta, int(canvas_pos.x()))
                return True
        return super().eventFilter(obj, event)

    def _on_zoom_slider(self, value: int):
        self.canvas.set_zoom(value)
        if hasattr(self, "zoom_value"):
            self.zoom_value.setText(str(int(value)))

    def _wheel_zoom(self, delta: int, canvas_x: int):
        """Zoom toward the cursor so frame-level edits stay under the pointer."""
        if not delta:
            return
        old = max(ZOOM_MIN_PPS, int(self.canvas.pixels_per_second))
        steps = max(1.0, abs(delta) / 120.0)
        factor = (1.22 ** steps) if delta > 0 else (1.0 / (1.22 ** steps))
        new = int(round(old * factor))
        new = max(ZOOM_MIN_PPS, min(ZOOM_MAX_PPS, new))
        if new == old:
            return
        time_ms = self.canvas._ms(canvas_x)
        # Keep the same media time under the cursor after width changes.
        global_pt = self.canvas.mapToGlobal(QPoint(int(canvas_x), 1))
        view_x = self.scroll.viewport().mapFromGlobal(global_pt).x()
        self.zoom.blockSignals(True)
        self.zoom.setValue(new)
        self.zoom.blockSignals(False)
        self._on_zoom_slider(new)
        new_x = self.canvas._x(time_ms)
        self.scroll.horizontalScrollBar().setValue(max(0, int(new_x - view_x)))

    def _fit(self):
        # Labels are outside the scroll area — use full viewport width for content.
        available = max(400, self.scroll.viewport().width() - 28)
        seconds = max(1.0, self.canvas.duration_ms / 1000)
        self.zoom.setValue(max(self.zoom.minimum(), min(self.zoom.maximum(), int(available / seconds))))

    def set_position(self, milliseconds: int):
        self.canvas.set_position(milliseconds)

    def set_transition_catalog(self, names: list[str], duration_ms: int = 500):
        self.canvas.set_transition_catalog(names, duration_ms)

    def set_transition_duration(self, duration_ms: int):
        self.canvas.set_transition_duration(duration_ms)

    def set_srt(self, srt: str):
        self.canvas.set_srt(srt)

    def set_project(
        self,
        video_path: str,
        duration_ms: int,
        srt: str,
        bgm_path: str = "",
        tts_path: str = "",
        original_audio_enabled: bool = True,
        edit_state: dict | None = None,
    ):
        self.original_audio.blockSignals(True)
        self.original_audio.setChecked(bool(original_audio_enabled))
        self.original_audio.blockSignals(False)
        self.canvas.set_project(
            duration_ms, video_path, srt, bgm_path, tts_path, original_audio_enabled, edit_state
        )
        self.canvas.set_waveform("video", [])
        self.canvas.set_waveform("bgm", [])
        self.canvas.set_waveform("tts", [])
        self._load_waveform("video", video_path)
        if bgm_path and Path(bgm_path).is_file():
            self._load_waveform("bgm", bgm_path)
        if tts_path and Path(tts_path).is_file():
            self._load_waveform("tts", tts_path)
        if hasattr(self, "label_rail"):
            self.label_rail.update()
        self._fit()

    def _load_waveform(self, kind: str, path: str):
        if not path or not Path(path).is_file():
            return
        previous = self._processes.pop(kind, None)
        if previous and previous.state() != QProcess.ProcessState.NotRunning:
            previous.kill()
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._processes[kind] = process
        self._paths[kind] = str(path)

        def finished(*_args):
            if self._processes.get(kind) is not process:
                process.deleteLater()
                return
            raw = bytes(process.readAllStandardOutput())
            values: list[float] = []
            if len(raw) >= 4:
                count = len(raw) // 4
                samples = struct.unpack(f"<{count}f", raw[: count * 4])
                bucket = max(1, count // 650)
                for offset in range(0, count, bucket):
                    chunk = samples[offset : offset + bucket]
                    values.append(min(1.0, max((abs(value) for value in chunk), default=0.0)))
            self.canvas.set_waveform(kind, values)
            self._processes.pop(kind, None)
            process.deleteLater()

        process.finished.connect(finished)
        process.start(
            self.ffmpeg,
            [
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-map",
                "0:a:0?",
                "-ac",
                "1",
                "-ar",
                "200",
                "-f",
                "f32le",
                "pipe:1",
            ],
        )
